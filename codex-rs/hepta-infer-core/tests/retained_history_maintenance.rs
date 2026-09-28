use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::semantic::{
    SemanticAdmissionV1, SemanticCompletionV1, SemanticPhaseV1,
};
use codex_hepta_infer_core::{RetrievalSourceV1, SemanticRetrievalRequestV1};
use codex_hepta_types::Digest32;

static NONCE: AtomicU64 = AtomicU64::new(0);

struct JournalPath(PathBuf);

impl JournalPath {
    fn new() -> Self {
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time")
            .as_nanos();
        Self(std::env::temp_dir().join(format!(
            "hepta-semantic-maintenance-{}-{stamp}-{nonce}.journal",
            std::process::id()
        )))
    }
}

impl Drop for JournalPath {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn request(id: &str) -> SemanticRetrievalRequestV1 {
    SemanticRetrievalRequestV1 {
        operation_id: id.to_string(),
        workspace_id: "workspace.maintenance".to_string(),
        generation: 3,
        objective_digest: "1".repeat(64),
        observation_digest: "2".repeat(64),
        bundle_digest: "3".repeat(64),
        deadline_ms: 9_000,
        query: "retained history".to_string(),
        sources: vec![RetrievalSourceV1 {
            source_id: "source.maintenance".to_string(),
            revision: 7,
            content_sha256: Digest32::of_bytes(b"alpha").to_string(),
            text: "alpha".to_string(),
        }],
    }
}

fn admission(id: &str) -> SemanticAdmissionV1 {
    SemanticAdmissionV1 {
        request_wire: request(id).encode().expect("request"),
        principal_id: "principal.maintenance".to_string(),
        reservation_id: format!("reservation.{id}"),
        worker_id: "worker.maintenance".to_string(),
        worker_generation: 3,
        maximum_tokens: 128,
        maximum_memory_bytes: 1_024,
        authority_binding_digest: "4".repeat(64),
    }
}

fn completion(id: &str) -> SemanticCompletionV1 {
    let input = request(id);
    let mut reply = b"HPTARS\x01\x00".to_vec();
    reply.extend_from_slice(Digest32::of_bytes(&input.encode().expect("wire")).as_array());
    reply.extend_from_slice(&[0x33; 32]);
    reply.extend_from_slice(&2_u32.to_be_bytes());
    reply.extend_from_slice(&100_000_u32.to_be_bytes());
    reply.extend_from_slice(&900_000_u32.to_be_bytes());
    reply.extend_from_slice(&12_u64.to_be_bytes());
    reply.extend_from_slice(&0_u64.to_be_bytes());
    reply.extend_from_slice(&7_u64.to_be_bytes());
    input.decode_reply(&reply).expect("valid reply");
    SemanticCompletionV1 {
        reply_wire: reply,
        observed_memory_bytes: Some(64),
    }
}

fn append_terminal(control: &mut DurableInferenceControl, id: &str) {
    let reserved = control
        .reserve_semantic(100, admission(id), 1)
        .expect("reserve");
    control
        .fence_semantic_dispatch(id, reserved.revision, 101)
        .expect("fence");
    control
        .complete_semantic(id, completion(id))
        .expect("complete");
    control
        .acknowledge_semantic_delivery(id, "5".repeat(64))
        .expect("acknowledge");
}

/// Compatibility selector for the historical architecture-workflow filter.
/// This measures retained append/fsync/reopen growth; it performs no compaction.
#[test]
#[ignore = "explicit retained-history fsync/reopen measurement selected by architecture CI"]
fn post_compaction_multi_generation_curve() {
    let path = JournalPath::new();
    let mut previous = 0;
    let mut previous_bytes = 0;
    let mut curve = Vec::new();

    for count in [64, 256, 1_024] {
        let mut control = DurableInferenceControl::open(&path.0, 2_048).expect("owner");
        let started = Instant::now();
        for index in previous..count {
            append_terminal(&mut control, &format!("measured.{index}"));
        }
        let append_us = started.elapsed().as_micros();
        drop(control);

        let bytes = fs::metadata(&path.0).expect("journal length").len();
        assert!(bytes > previous_bytes);

        let started = Instant::now();
        let mut control = DurableInferenceControl::open(&path.0, 2_048).expect("reopen");
        let reopen_us = started.elapsed().as_micros();
        for index in 0..count {
            let id = format!("measured.{index}");
            let recovered = control
                .reserve_semantic(10_000, admission(&id), 1)
                .expect("replay");
            assert_eq!(recovered.phase, SemanticPhaseV1::Completed);
            assert_eq!(recovered.completion, Some(completion(&id)));
            assert_eq!(recovered.delivery_ack_digest, Some("5".repeat(64)));
            assert!(!recovered.delivery_pending());
            assert!(!recovered.execution_unknown());
        }
        assert_eq!(fs::metadata(&path.0).expect("replay length").len(), bytes);
        drop(control);

        curve.push(serde_json::json!({
            "retained_records": count,
            "new_records": count - previous,
            "journal_bytes": bytes,
            "append_and_fsync_us": append_us,
            "reopen_us": reopen_us,
            "all_results_replayed": true,
            "replay_appended_bytes": 0
        }));
        previous = count;
        previous_bytes = bytes;
    }

    println!(
        "HEPTA_SEMANTIC_GROWTH={}",
        serde_json::json!({
            "schema": "hepta.semantic-journal.growth.v1",
            "curve": curve,
            "compaction_performed": false,
            "model_executed": false,
            "long_term_slo_established": false,
            "legacy_filter_compatibility": true
        })
    );
}
