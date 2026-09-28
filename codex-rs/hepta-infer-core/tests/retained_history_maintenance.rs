use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error;
use codex_hepta_infer_core::durable_control::semantic::{
    SemanticAdmissionV1, SemanticCompletionV1, SemanticPhaseV1, SemanticRecordV1,
};
use codex_hepta_infer_core::{RetrievalSourceV1, SemanticRetrievalRequestV1};
use codex_hepta_types::Digest32;

static NONCE: AtomicU64 = AtomicU64::new(0);

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

struct JournalPath(PathBuf);

impl JournalPath {
    fn new() -> Self {
        let nonce = NONCE.fetch_add(1, Ordering::Relaxed);
        let stamp = checked(SystemTime::now().duration_since(UNIX_EPOCH)).as_nanos();
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
        request_wire: checked(request(id).encode()),
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
    reply.extend_from_slice(Digest32::of_bytes(&checked(input.encode())).as_array());
    reply.extend_from_slice(&[0x33; 32]);
    reply.extend_from_slice(&2_u32.to_be_bytes());
    reply.extend_from_slice(&100_000_u32.to_be_bytes());
    reply.extend_from_slice(&900_000_u32.to_be_bytes());
    reply.extend_from_slice(&12_u64.to_be_bytes());
    reply.extend_from_slice(&0_u64.to_be_bytes());
    reply.extend_from_slice(&7_u64.to_be_bytes());
    checked(input.decode_reply(&reply));
    SemanticCompletionV1 {
        reply_wire: reply,
        observed_memory_bytes: Some(64),
    }
}

fn append_terminal(control: &mut DurableInferenceControl, id: &str) {
    let reserved = checked(control.reserve_semantic(100, admission(id), 1));
    checked(control.fence_semantic_dispatch(id, reserved.revision, 101));
    checked(control.complete_semantic(id, completion(id)));
    checked(control.acknowledge_semantic_delivery(id, "5".repeat(64)));
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

/// Reopen through distinct exclusive owners without treating an unknown effect
/// as a free slot or a new worker's permission to run it. This is sequential
/// ownership turnover, not concurrent writers, incremental replay or compaction.
#[test]
#[ignore = "explicit exclusive-owner turnover and retained-history measurement"]
fn exclusive_owner_turnover_retains_unknown_and_completed_work() {
    let path = JournalPath::new();
    let pending_id = "pending.original";
    let original = admission(pending_id);
    let mut owner = DurableInferenceControl::open(&path.0, 64).expect("owner");
    let reserved = owner
        .reserve_semantic(100, original.clone(), 2)
        .expect("reserve original");
    owner
        .fence_semantic_dispatch(pending_id, reserved.revision, 101)
        .expect("original dispatch fence");
    let pending = owner.cancel_semantic(pending_id).expect("cancel unknown");
    assert!(pending.execution_unknown());
    assert!(pending.cancel_requested);
    drop(owner);

    let mut terminals: Vec<(String, SemanticRecordV1)> = Vec::new();
    let mut curve = Vec::new();
    for generation in 4..20 {
        let before_bytes = fs::metadata(&path.0).expect("journal length").len();
        let started = Instant::now();
        let mut owner = DurableInferenceControl::open(&path.0, 64).expect("successor");
        let reopen_us = started.elapsed().as_micros();
        assert!(matches!(
            DurableInferenceControl::open(&path.0, 64),
            Err(Error::WriterUnavailable)
        ));
        assert_eq!(
            owner
                .reserve_semantic(10_000, original.clone(), 2)
                .expect("history"),
            pending
        );
        assert!(
            owner
                .fence_semantic_dispatch(pending_id, pending.revision, 102)
                .is_err()
        );
        let mut substituted = original.clone();
        substituted.worker_id = format!("worker.{generation}");
        substituted.worker_generation = generation;
        assert!(owner.reserve_semantic(100, substituted, 2).is_err());
        for (id, expected) in &terminals {
            assert_eq!(owner.semantic_record(id).expect("retained"), Some(expected));
        }
        assert_eq!(
            fs::metadata(&path.0).expect("read-only history").len(),
            before_bytes
        );

        let id = format!("successor.{generation}");
        let mut current = admission(&id);
        let mut input = request(&id);
        input.generation = generation;
        current.request_wire = input.encode().expect("new-generation request");
        current.worker_generation = generation;
        current.worker_id = format!("worker.{generation}");
        let active = owner
            .reserve_semantic(100, current.clone(), 2)
            .expect("new work");
        // Cancellation did not free the original unknown operation's slot.
        assert!(matches!(
            owner.reserve_semantic(100, admission("excess.work"), 2),
            Err(Error::CapacityExceeded)
        ));
        owner
            .fence_semantic_dispatch(&id, active.revision, 101)
            .expect("new fence");
        let mut observed = completion(&id);
        // Bind the existing binary reply to this exact generation's request.
        observed.reply_wire[8..40]
            .copy_from_slice(Digest32::of_bytes(&current.request_wire).as_array());
        input
            .decode_reply(&observed.reply_wire)
            .expect("new-generation reply");
        owner.complete_semantic(&id, observed).expect("terminal");
        let terminal = owner
            .acknowledge_semantic_delivery(&id, "5".repeat(64))
            .expect("ack");
        terminals.push((id, terminal));
        let after_bytes = fs::metadata(&path.0).expect("appended journal").len();
        assert!(after_bytes > before_bytes);
        curve.push(serde_json::json!({
            "generation": generation,
            "retained_terminals": terminals.len(),
            "unknown_operations": 1,
            "reopen_us": reopen_us,
            "journal_bytes": after_bytes,
            "history_lookup_appended_bytes": 0
        }));
        drop(owner);
    }
    let mut owner = DurableInferenceControl::open(&path.0, 64).expect("final successor");
    assert_eq!(
        owner.semantic_record(pending_id).expect("pending history"),
        Some(&pending)
    );
    let settled = owner
        .complete_semantic(pending_id, completion(pending_id))
        .expect("observed completion");
    assert!(!settled.execution_unknown());
    // A late physical result cannot undo a prior cancellation or authorize use.
    assert!(settled.cancel_requested);
    assert!(!settled.delivery_pending());
    drop(owner);
    let owner = DurableInferenceControl::open(&path.0, 64).expect("settled reopen");
    assert_eq!(
        owner.semantic_record(pending_id).expect("settled history"),
        Some(&settled)
    );
    for (id, expected) in &terminals {
        assert_eq!(
            owner.semantic_record(id).expect("terminal history"),
            Some(expected)
        );
    }
    println!(
        "HEPTA_OWNER_TURNOVER={}",
        serde_json::json!({
            "schema": "hepta.semantic-owner.turnover.v1",
            "curve": curve,
            "concurrent_writers_allowed": false,
            "unknown_operation_replayed": false,
            "model_executed": false,
            "compaction_performed": false,
            "resource_reclamation_attested": false,
            "long_term_slo_established": false
        })
    );
}

#[test]
fn semantic_reservation_identity_survives_all_terminal_states_and_reopen() {
    for terminal in ["cancel", "stop", "complete"] {
        let path = JournalPath::new();
        let mut owner = DurableInferenceControl::open(&path.0, 32).expect("owner");
        let first = admission("identity.original");
        let reserved = owner
            .reserve_semantic(100, first.clone(), 2)
            .expect("reserve");
        match terminal {
            "cancel" => {
                owner.cancel_semantic("identity.original").expect("cancel");
            }
            "stop" => {
                owner
                    .stop_semantic_before_dispatch("identity.original", "not_entered".to_string())
                    .expect("stop");
            }
            _ => {
                owner
                    .fence_semantic_dispatch("identity.original", reserved.revision, 101)
                    .expect("fence");
                owner
                    .complete_semantic("identity.original", completion("identity.original"))
                    .expect("complete");
                owner
                    .acknowledge_semantic_delivery("identity.original", "5".repeat(64))
                    .expect("ack");
            }
        }
        let mut collision = admission("identity.other");
        collision.reservation_id = first.reservation_id.clone();
        let bytes = fs::metadata(&path.0).expect("length").len();
        assert!(matches!(
            owner.reserve_semantic(100, collision.clone(), 2),
            Err(Error::Conflict)
        ));
        assert_eq!(fs::metadata(&path.0).expect("unchanged").len(), bytes);
        drop(owner);
        let mut owner = DurableInferenceControl::open(&path.0, 32).expect("reopen");
        assert!(matches!(
            owner.reserve_semantic(100, collision, 2),
            Err(Error::Conflict)
        ));
        assert_eq!(
            fs::metadata(&path.0).expect("unchanged replay").len(),
            bytes
        );
        assert!(owner.reserve_semantic(10_000, first, 2).is_ok());
    }
}

#[test]
fn failed_admission_does_not_publish_a_reservation_identity() {
    let path = JournalPath::new();
    let mut owner = DurableInferenceControl::open(&path.0, 32).expect("owner");
    owner
        .reserve_semantic(100, admission("occupied"), 1)
        .expect("occupied");
    let attempted = admission("retry.admission");
    let bytes = fs::metadata(&path.0).expect("length").len();
    assert!(matches!(
        owner.reserve_semantic(100, attempted.clone(), 1),
        Err(Error::CapacityExceeded)
    ));
    assert_eq!(fs::metadata(&path.0).expect("unchanged").len(), bytes);
    owner
        .cancel_semantic("occupied")
        .expect("cancel before dispatch");
    assert!(owner.reserve_semantic(100, attempted.clone(), 1).is_ok());
    drop(owner);
    let mut owner = DurableInferenceControl::open(&path.0, 32).expect("reopen");
    assert!(owner.reserve_semantic(10_000, attempted, 1).is_ok());
}

#[test]
fn duplicate_reservation_in_a_replayed_event_rejects_owner_recovery() {
    let path = JournalPath::new();
    let mut owner = DurableInferenceControl::open(&path.0, 32).expect("owner");
    let first = admission("reserved.original");
    owner
        .reserve_semantic(100, first.clone(), 1)
        .expect("reserve");
    owner.cancel_semantic("reserved.original").expect("cancel");
    drop(owner);
    let mut collision = admission("reserved.substitution");
    collision.reservation_id = first.reservation_id;
    let event = serde_json::json!({"Reserve": {
        "admission": collision, "maximum_in_flight": 1, "now_ms": 100
    }});
    let mut file = fs::OpenOptions::new()
        .append(true)
        .open(&path.0)
        .expect("append fixture");
    writeln!(file, "semantic-retrieval-v1|{event}").expect("fixture event");
    file.sync_all().expect("fixture sync");
    drop(file);
    assert!(matches!(
        DurableInferenceControl::open(&path.0, 32),
        Err(Error::Conflict)
    ));
}
