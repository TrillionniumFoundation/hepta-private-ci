use std::fmt::Debug;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_cognitive_read::ReadFieldV1;
use codex_hepta_cognitive_read::ReadIdsRequestV1;
use codex_hepta_cognitive_read::read_ids_v1;
use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::*;
use crate::PlannerStoreV1;

static NONCE: AtomicU64 = AtomicU64::new(1);

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn snapshot() -> CognitiveSnapshot {
    must(build_snapshot(
        must(Generation::new(3)),
        vec![MemoryRecord {
            record_id: id("memory:a"),
            revision: must(Revision::new(1)),
            kind: MemoryKind::Fact,
            content_digest: digest("content-a"),
            predecessor_digest: None,
            citations: vec![],
            state: RecordState::Live,
        }],
    ))
}

fn request_binding() -> ContextRequestBindingV1 {
    ContextRequestBindingV1 {
        request_identity_digest: digest("request-id"),
        query_digest: digest("query"),
        retrieval_profile_digest: digest("retrieval-profile"),
        ranker_policy_digest: Some(digest("ranker-policy")),
        response_profile_digest: digest("response-profile"),
    }
}

struct TempRoot(PathBuf);

impl TempRoot {
    fn new(label: &str) -> Self {
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-authenticated-context-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir(&path).expect("create context planner root");
        Self(path)
    }
}

impl Drop for TempRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn canonical_read_count_drives_plan_and_durable_entry_revalidates() {
    let snapshot = snapshot();
    let read = must(read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:a")],
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: 4096,
        },
    ));
    let encoded_context = br#"{"items":[{"id":"memory:a"}]}"#;
    let owner_cut_digest = digest("owner-cut");
    let plan = must(plan_authenticated_context(AuthenticatedContextV1 {
        owner_id: id("owner"),
        body_generation: must(Generation::new(3)),
        read: &read,
        owner_cut_digest,
        encoded_context,
        maximum_context_bytes: 4096,
        request: request_binding(),
        observed_at_micros: 10,
        expires_at_micros: 100,
    }));
    assert!(plan.read_allowed);
    assert_eq!(plan.context_digest, Digest32::of_bytes(encoded_context));

    let root = TempRoot::new("roundtrip");
    let mut store = must(PlannerStoreV1::open(&root.0));
    let entry = must(store.append_envelope(must(plan.decision_envelope())));
    let verified = must(verify_context_decision_entry(
        &entry,
        plan.evaluation.plan.receipt_digest(),
        plan.context_digest,
        plan.request_binding_digest,
        read.receipt_digest(),
        owner_cut_digest,
        1,
        true,
        50,
    ));
    assert_eq!(verified.plan_receipt_digest, plan.evaluation.plan.receipt_digest());
    assert_eq!(verified.verified_item_count, 1);
    assert!(verified.read_allowed);
}

#[test]
fn missing_authenticated_record_is_not_converted_to_zero_utility() {
    let snapshot = snapshot();
    let read = must(read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:missing")],
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: 4096,
        },
    ));
    assert_eq!(
        plan_authenticated_context(AuthenticatedContextV1 {
            owner_id: id("owner"),
            body_generation: must(Generation::new(3)),
            read: &read,
            owner_cut_digest: digest("owner-cut"),
            encoded_context: b"{}",
            maximum_context_bytes: 4096,
            request: request_binding(),
            observed_at_micros: 10,
            expires_at_micros: 100,
        })
        .expect_err("missing record must fail before planning"),
        AuthenticatedContextError::MissingRecord
    );
}

#[test]
fn plan_receipt_context_request_and_expiry_drift_fail_final_use() {
    let snapshot = snapshot();
    let read = must(read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:a")],
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: 4096,
        },
    ));
    let plan = must(plan_authenticated_context(AuthenticatedContextV1 {
        owner_id: id("owner"),
        body_generation: must(Generation::new(3)),
        read: &read,
        owner_cut_digest: digest("owner-cut"),
        encoded_context: b"context",
        maximum_context_bytes: 4096,
        request: request_binding(),
        observed_at_micros: 10,
        expires_at_micros: 100,
    }));
    let root = TempRoot::new("drift");
    let mut store = must(PlannerStoreV1::open(&root.0));
    let entry = must(store.append_envelope(must(plan.decision_envelope())));

    assert_eq!(
        verify_context_decision_entry(
            &entry,
            digest("substituted-plan-receipt"),
            plan.context_digest,
            plan.request_binding_digest,
            read.receipt_digest(),
            digest("owner-cut"),
            1,
            true,
            50,
        )
        .expect_err("plan receipt drift must reject"),
        AuthenticatedContextError::DecisionMismatch
    );
    assert_eq!(
        verify_context_decision_entry(
            &entry,
            plan.evaluation.plan.receipt_digest(),
            digest("substituted-context"),
            plan.request_binding_digest,
            read.receipt_digest(),
            digest("owner-cut"),
            1,
            true,
            50,
        )
        .expect_err("context drift must reject"),
        AuthenticatedContextError::DecisionMismatch
    );
    assert_eq!(
        verify_context_decision_entry(
            &entry,
            plan.evaluation.plan.receipt_digest(),
            plan.context_digest,
            digest("substituted-request"),
            read.receipt_digest(),
            digest("owner-cut"),
            1,
            true,
            50,
        )
        .expect_err("request binding drift must reject"),
        AuthenticatedContextError::DecisionMismatch
    );
    assert_eq!(
        verify_context_decision_entry(
            &entry,
            plan.evaluation.plan.receipt_digest(),
            plan.context_digest,
            plan.request_binding_digest,
            read.receipt_digest(),
            digest("owner-cut"),
            1,
            true,
            100,
        )
        .expect_err("expired decision must reject"),
        AuthenticatedContextError::DecisionExpired
    );
}
