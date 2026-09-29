use super::*;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use crate::RetrievalSourceV1;

static NONCE: AtomicU64 = AtomicU64::new(0);

struct JournalPath(PathBuf);

impl JournalPath {
    fn new() -> Self {
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("time")
            .as_nanos();
        Self(std::env::temp_dir().join(format!(
            "hepta-semantic-{}-{stamp}-{nonce}.journal",
            std::process::id()
        )))
    }

    fn open(&self) -> DurableInferenceControl {
        DurableInferenceControl::open(&self.0, 32).expect("open existing owner journal")
    }
}

impl Drop for JournalPath {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
        let _ = fs::remove_file(self.0.with_extension("ready"));
    }
}

fn request(id: &str) -> SemanticRetrievalRequestV1 {
    SemanticRetrievalRequestV1 {
        operation_id: id.to_string(),
        workspace_id: "workspace.1".to_string(),
        generation: 3,
        objective_digest: "1".repeat(64),
        observation_digest: "2".repeat(64),
        bundle_digest: "3".repeat(64),
        deadline_ms: 9000,
        query: "q".to_string(),
        sources: vec![RetrievalSourceV1 {
            source_id: "source.1".to_string(),
            revision: 7,
            content_sha256: Digest32::of_bytes(b"alpha").to_string(),
            text: "alpha".to_string(),
        }],
    }
}

fn admission(id: &str) -> SemanticAdmissionV1 {
    SemanticAdmissionV1 {
        request_wire: request(id).encode().expect("request"),
        principal_id: "principal.1".to_string(),
        reservation_id: format!("reservation.{id}"),
        worker_id: "worker.1".to_string(),
        worker_generation: 3,
        maximum_tokens: 128,
        maximum_memory_bytes: 1024,
        authority_binding_digest: "4".repeat(64),
    }
}

#[test]
fn resource_tuple_reopens_and_cannot_be_rebound_or_downgraded() {
    let path = JournalPath::new();
    let limits = SemanticResourceLimitsV2 {
        model_id: "model.1".to_string(),
        resident_bytes: 512,
        kv_bytes: 128,
        transient_bytes: 384,
    };
    let mut owner = path.open();
    let record = owner
        .reserve_semantic_with_resources(100, admission("op.v2"), 1, limits.clone())
        .expect("resource admission");
    drop(owner);
    let mut owner = path.open();
    assert_eq!(
        owner.semantic_record("op.v2").expect("lookup"),
        Some(&record)
    );
    let original = fs::read(&path.0).expect("bytes");
    assert_eq!(
        owner
            .reserve_semantic_with_resources(10000, admission("op.v2"), 1, limits.clone())
            .expect("history"),
        record
    );
    let mut changed = limits;
    changed.kv_bytes += 1;
    changed.transient_bytes -= 1;
    assert!(
        owner
            .reserve_semantic_with_resources(101, admission("op.v2"), 1, changed)
            .is_err()
    );
    assert!(owner.reserve_semantic(101, admission("op.v2"), 1).is_err());
    assert_eq!(fs::read(&path.0).expect("unchanged"), original);
    assert!(
        String::from_utf8(original)
            .expect("journal")
            .contains("ReserveResourcesV2")
    );
}

#[test]
fn invalid_resource_admission_never_mutates_journal() {
    let path = JournalPath::new();
    let mut owner = path.open();
    let original = fs::read(&path.0).expect("bytes");
    for limits in [
        SemanticResourceLimitsV2 {
            model_id: "model.1".to_string(),
            resident_bytes: 0,
            kv_bytes: 0,
            transient_bytes: 1024,
        },
        SemanticResourceLimitsV2 {
            model_id: "model.1".to_string(),
            resident_bytes: u64::MAX,
            kv_bytes: 1,
            transient_bytes: 0,
        },
        SemanticResourceLimitsV2 {
            model_id: "model.1".to_string(),
            resident_bytes: 512,
            kv_bytes: 128,
            transient_bytes: 383,
        },
    ] {
        assert!(
            owner
                .reserve_semantic_with_resources(100, admission("op.invalid"), 1, limits)
                .is_err()
        );
        assert_eq!(fs::read(&path.0).expect("unchanged"), original);
    }
}
