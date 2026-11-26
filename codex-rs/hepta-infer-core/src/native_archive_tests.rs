use super::*;
use crate::durable_control::InferenceRequest;
use crate::durable_control::native::NativeBoundaryStatus;
use crate::durable_control::native::NativeDispatch;
use crate::durable_control::native::NativeOwnerAuthority;
use crate::durable_control::native::NativeRequest;
use crate::durable_control::native::NativeRunOutput;
use crate::durable_control::native::NativeRunStatus;
use crate::durable_control::native::NativeTerminalOwnerBinding;

fn directory() -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!(
        "hepta-native-archive-{:032x}",
        rand::random::<u128>()
    ));
    std::fs::create_dir_all(&path).unwrap();
    path
}

fn request(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.to_string(),
        principal_id: "agent-1".to_string(),
        worker_generation: 1,
        model: "model".to_string(),
        payload_digest: "a".repeat(64),
    }
}

fn dispatch() -> NativeDispatch {
    NativeDispatch {
        thread_id: "thread-1".to_string(),
        model_provider: "provider".to_string(),
        context_digest: "b".repeat(64),
        owner_context_digest: None,
        codex_payload_digest: None,
        codex_request_digest: None,
        app_server_version: None,
        protocol_id: None,
        codex_source_admission_digest: None,
        codex_home_digest: None,
        codex_connection_id: None,
        codex_session_id: None,
        codex_deadline_ms: None,
        codex_authority_epoch: None,
        codex_revocation_revision: None,
        codex_revocation_head_sha256: None,
        codex_authority_witness_sha256: None,
    }
}

#[test]
fn small_capacity_survives_many_rounds_reload_and_never_replays_history() {
    let directory = directory();
    let path = directory.join("control.journal");
    let mut control = DurableInferenceControl::open(&path, 3).unwrap();
    let generic = InferenceRequest {
        request_id: "generic".to_string(),
        principal_id: "agent-1".to_string(),
        model_digest: "a".repeat(64),
        payload_digest: "b".repeat(64),
        maximum_tokens: 1,
        deadline_ms: 20_000,
        semantic_digest: "c".repeat(64),
    };
    control.submit(1, generic).unwrap();
    let generic_before = control.get("generic").unwrap().clone();
    assert!(
        !control
            .maintain_native_history(1, Duration::from_secs(5))
            .unwrap()
            .journal_compacted
    );
    control.reserve_native(request("unknown"), 2).unwrap();
    control.dispatch_native("unknown", dispatch()).unwrap();
    let unknown = control.native_record("unknown").unwrap().clone();
    let rounds = control.capacity * 4;
    for round in 0..rounds {
        let id = format!("round-{round}");
        control.reserve_native(request(&id), 2).unwrap();
        let released = control
            .stop_native_before_dispatch(&id, "not sent".to_string())
            .unwrap();
        let receipt = control
            .maintain_native_history(1, Duration::from_secs(5))
            .unwrap();
        assert_eq!(receipt.archived_records, 1);
        assert_eq!(receipt.resident_native_records, 1);
        // Retirement is durable even when its budget expires before journal
        // compaction. Reopening below must retain receipt and replay fences.
        assert!(control.native_record(&id).is_none());
        assert_eq!(
            control.native_record_resolved(&id).unwrap(),
            Some(released.clone())
        );
        assert_eq!(control.reserve_native(request(&id), 2).unwrap(), released);
        let mut changed = request(&id);
        changed.payload_digest = "d".repeat(64);
        assert_eq!(control.reserve_native(changed, 2), Err(Error::Conflict));
        drop(control);
        control = DurableInferenceControl::open(&path, 3).unwrap();
        assert_eq!(control.native_record("unknown"), Some(&unknown));
        assert_eq!(control.get("generic"), Some(&generic_before));
        assert_eq!(control.native_record_resolved(&id).unwrap(), Some(released));
        // The original in-flight policy remains frozen after every replacement.
        assert_eq!(
            control.reserve_native(request("wrong-policy"), 1),
            Err(Error::Conflict)
        );
        assert!(DurableInferenceControl::open(&path, 3).is_err());
    }
    // A later maintenance call must actually compact any pending retirement;
    // merely loosening the timing assertion would not prove bounded history.
    let mut compacted = !control.native.compaction_pending;
    for _ in 0..3 {
        if compacted {
            break;
        }
        let receipt = control
            .maintain_native_history(1, Duration::from_secs(5))
            .unwrap();
        assert_eq!(receipt.archived_records, 0);
        compacted = receipt.journal_compacted;
    }
    assert!(compacted);
    assert!(control.journal_bytes < 4096);
    drop(control);
    let control = DurableInferenceControl::open(&path, 3).unwrap();
    assert_eq!(control.native_record("unknown"), Some(&unknown));
    assert_eq!(control.get("generic"), Some(&generic_before));
    for round in 0..rounds {
        let id = format!("round-{round}");
        assert!(control.native_record_resolved(&id).unwrap().is_some());
    }
    drop(control);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn maintenance_batch_retires_available_settled_records_under_a_smaller_owner_capacity() {
    let directory = directory();
    let path = directory.join("batch.journal");
    let mut control = DurableInferenceControl::open(&path, 3).unwrap();
    control.reserve_native(request("unknown"), 2).unwrap();
    control.dispatch_native("unknown", dispatch()).unwrap();
    let unknown = control.native_record("unknown").unwrap().clone();
    let mut stopped = Vec::new();
    for id in ["closed-a", "closed-b"] {
        control.reserve_native(request(id), 2).unwrap();
        stopped.push(
            control
                .stop_native_before_dispatch(id, "not sent".to_string())
                .unwrap(),
        );
    }
    let receipt = control
        .maintain_native_history(/*maximum_records*/ 32, Duration::from_secs(5))
        .unwrap();
    assert_eq!(receipt.archived_records, 2);
    assert_eq!(receipt.resident_native_records, 1);
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 3).unwrap();
    assert_eq!(control.native_record("unknown"), Some(&unknown));
    for record in stopped {
        assert_eq!(
            control
                .native_record_resolved(&record.request.request_id)
                .unwrap(),
            Some(record.clone())
        );
        assert_eq!(
            control.reserve_native(record.request.clone(), 2).unwrap(),
            record
        );
    }
    control.reserve_native(request("new-work"), 2).unwrap();
}

#[test]
fn crash_cut_after_receipt_before_journal_retirement_is_recoverable() {
    let directory = directory();
    let path = directory.join("control.journal");
    let mut control = DurableInferenceControl::open(&path, 1).unwrap();
    control.reserve_native(request("cut"), 1).unwrap();
    let released = control
        .stop_native_before_dispatch("cut", "not sent".to_string())
        .unwrap();
    archive_store::persist(&path, &released).unwrap();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 1).unwrap();
    assert_eq!(control.native_record("cut"), Some(&released));
    let maintained = control
        .maintain_native_history(1, Duration::from_secs(5))
        .unwrap();
    assert_eq!(maintained.archived_records, 1);
    control.reserve_native(request("successor"), 1).unwrap();
    assert_eq!(
        control.native_record_resolved("cut").unwrap(),
        Some(released)
    );
    drop(control);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn removed_or_corrupt_receipt_is_not_readmitted_when_tombstone_survives() {
    let directory = directory();
    let path = directory.join("control.journal");
    let mut control = DurableInferenceControl::open(&path, 1).unwrap();
    control.reserve_native(request("receipt"), 1).unwrap();
    control
        .stop_native_before_dispatch("receipt", "not sent".to_string())
        .unwrap();
    control
        .maintain_native_history(1, Duration::from_secs(5))
        .unwrap();
    let key = codex_hepta_types::Digest32::of_bytes(b"receipt").to_string();
    let receipt = archive_store::history_root(&path)
        .join(&key[..2])
        .join(&key[2..4])
        .join(format!("{key}.json"));
    let original = std::fs::read(&receipt).unwrap();
    std::fs::remove_file(&receipt).unwrap();
    assert!(control.reserve_native(request("receipt"), 1).is_err());
    std::fs::write(&receipt, b"corrupt receipt").unwrap();
    assert!(control.native_record_resolved("receipt").is_err());
    std::fs::write(&receipt, original).unwrap();
    assert!(control.native_record_resolved("receipt").unwrap().is_some());
    assert!(control.native_record("receipt").is_none());
    drop(control);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn retirement_before_compaction_reloads_and_journal_names_keep_history_isolated() {
    let directory = directory();
    let mut histories = Vec::new();
    for (name, digest) in [("control.journal", "a"), ("control.log", "b")] {
        let path = directory.join(name);
        let mut control = DurableInferenceControl::open(&path, 1).unwrap();
        let mut operation = request("same-id");
        operation.payload_digest = digest.repeat(64);
        control.reserve_native(operation, 1).unwrap();
        let released = control
            .stop_native_before_dispatch("same-id", "not sent".to_string())
            .unwrap();
        let digest = archive_store::persist(&path, &released).unwrap();
        control.commit_native_archive("same-id", digest).unwrap();
        assert!(
            !control
                .compact_native_history(
                    Instant::now() - Duration::from_secs(1),
                    Duration::from_millis(10)
                )
                .unwrap()
        );
        assert!(control.native.compaction_pending);

        drop(control); // Durable retirement exists but no compaction happened.
        histories.push((path, released));
    }
    for (path, released) in histories {
        let mut control = DurableInferenceControl::open(&path, 1).unwrap();
        assert!(control.native_record("same-id").is_none());
        assert_eq!(
            control.native_record_resolved("same-id").unwrap(),
            Some(released)
        );
        let receipt = control
            .maintain_native_history(1, Duration::from_secs(5))
            .unwrap();
        assert_eq!(receipt.archived_records, 0);
        assert!(receipt.journal_compacted);
    }
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn pending_terminal_publication_is_never_archived() {
    let directory = directory();
    let path = directory.join("control.journal");
    let mut control = DurableInferenceControl::open(&path, 1).unwrap();
    control.reserve_native(request("pending"), 1).unwrap();
    let (_, _proof) = control
        .dispatch_native_with_pre_effect_abort_bound(
            "pending",
            dispatch(),
            NativeTerminalOwnerBinding {
                run_id: "owner-run".to_string(),
                owner_dispatch_revision: 2,
                context_digest: "c".repeat(64),
                envelope_digest: "d".repeat(64),
            },
        )
        .unwrap();
    control
        .native_started("pending", "turn-1".to_string())
        .unwrap();
    control
        .settle_native(
            "pending",
            NativeRunOutput {
                thread_id: "thread-1".to_string(),
                turn_id: "turn-1".to_string(),
                model: "model".to_string(),
                model_provider: "provider".to_string(),
                status: NativeRunStatus::Failed,
                boundary_status: NativeBoundaryStatus::Failed,
                output: String::new(),
                observed_output_tokens: Some(1),
                terminal_observed: true,
                stop_reason: None,
                owner_authority: NativeOwnerAuthority::ObservedReady,
                codex_terminal_correlation_digest: Some("f".repeat(64)),
            },
        )
        .unwrap();
    // Provider terminality releases a slot but its owner outbox still needs
    // exact acknowledgement. Retirement must not erase that pending work.
    let pending = control.native_record("pending").unwrap().clone();
    assert_eq!(pending.state, NativeReservationState::Released);
    assert!(pending.terminal_publication.as_ref().unwrap().pending());
    let receipt = control
        .maintain_native_history(1, Duration::from_secs(5))
        .unwrap();
    assert_eq!(receipt.archived_records, 0);
    assert!(!receipt.journal_compacted);
    assert_eq!(control.native_record("pending"), Some(&pending));
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 1).unwrap();
    assert_eq!(control.native_record("pending"), Some(&pending));
    let publication = pending.terminal_publication.as_ref().unwrap();
    let acknowledged = control
        .acknowledge_native_terminal_publication("pending", &publication.publication_digest, 3)
        .unwrap();
    assert_eq!(
        control
            .maintain_native_history(1, Duration::from_secs(5))
            .unwrap()
            .archived_records,
        1
    );
    assert_eq!(
        control.native_record_resolved("pending").unwrap(),
        Some(acknowledged)
    );
    drop(control);
    std::fs::remove_dir_all(directory).unwrap();
}
