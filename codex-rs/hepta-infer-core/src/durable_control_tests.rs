use super::*;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn path(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    std::env::temp_dir().join(format!("hepta-infer-control-{label}-{nonce}.journal"))
}

fn request() -> InferenceRequest {
    InferenceRequest {
        request_id: "request.1".to_string(),
        principal_id: "principal.1".to_string(),
        model_digest: "1".repeat(64),
        payload_digest: "2".repeat(64),
        maximum_tokens: 128,
        deadline_ms: 10_000,
        semantic_digest: "3".repeat(64),
    }
}

fn reservation() -> Reservation {
    Reservation {
        reservation_id: "reservation.1".to_string(),
        quota_units: 100,
        maximum_tokens: 128,
        authority_epoch: 4,
        valid_until_ms: 9_000,
    }
}

fn assignment() -> Assignment {
    Assignment {
        worker_id: "worker.1".to_string(),
        worker_generation: 2,
        assignment_digest: "4".repeat(64),
    }
}

#[test]
fn reopens_exact_committed_state() {
    let path = path("reopen");
    {
        let mut control = DurableInferenceControl::open(&path, 32).expect("open");
        assert_eq!(control.submit(100, request()).expect("submit").revision, 1);
        assert_eq!(
            control
                .reserve(100, "request.1", 1, reservation())
                .expect("reserve")
                .revision,
            2
        );
        assert_eq!(
            control
                .assign("request.1", 2, assignment())
                .expect("assign")
                .revision,
            3
        );
    }
    let reopened = DurableInferenceControl::open(&path, 32).expect("reopen");
    let record = reopened.get("request.1").expect("record");
    assert_eq!(record.state, RequestState::Assigned);
    assert_eq!(record.revision, 3);
    fs::remove_file(path).expect("cleanup");
}

#[test]
fn cancellation_after_assignment_waits_for_observation_and_accounts_usage() {
    let path = path("cancel-race");
    let mut control = DurableInferenceControl::open(&path, 32).expect("open");
    control.submit(100, request()).expect("submit");
    control
        .reserve(100, "request.1", 1, reservation())
        .expect("reserve");
    control
        .assign("request.1", 2, assignment())
        .expect("assign");
    assert_eq!(
        control.cancel("request.1", 3).expect("cancel").state,
        RequestState::Cancelling
    );
    let observation = TerminalObservation {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        worker_id: "worker.1".to_string(),
        worker_generation: 2,
        model_digest: "1".repeat(64),
        payload_digest: "2".repeat(64),
        terminal_observed: true,
        terminal_status: Some(RequestState::Completed),
        output_digest: Some("5".repeat(64)),
        consumed_tokens: 64,
        usage_units: 50,
    };
    let receipt = control
        .settle("request.1", 4, "6".repeat(64), observation)
        .expect("settle");
    assert_eq!(receipt.state, RequestState::Completed);
    let record = control.get("request.1").expect("record");
    assert_eq!(record.consumed_tokens, 64);
    assert_eq!(record.usage_units, 50);
    fs::remove_file(path).expect("cleanup");
}

#[test]
fn missing_terminal_observation_becomes_indeterminate() {
    let path = path("indeterminate");
    let mut control = DurableInferenceControl::open(&path, 32).expect("open");
    control.submit(100, request()).expect("submit");
    control
        .reserve(100, "request.1", 1, reservation())
        .expect("reserve");
    control
        .assign("request.1", 2, assignment())
        .expect("assign");
    let observation = TerminalObservation {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        worker_id: "worker.1".to_string(),
        worker_generation: 2,
        model_digest: "1".repeat(64),
        payload_digest: "2".repeat(64),
        terminal_observed: false,
        terminal_status: None,
        output_digest: None,
        consumed_tokens: 10,
        usage_units: 8,
    };
    let receipt = control
        .settle("request.1", 3, "6".repeat(64), observation)
        .expect("settle");
    assert_eq!(receipt.state, RequestState::Indeterminate);
    assert!(!receipt.terminal_observed);
    fs::remove_file(path).expect("cleanup");
}

#[test]
fn checkpoint_roundtrips_every_reachable_legacy_state_shape() {
    fn request_for(id: &str) -> InferenceRequest {
        InferenceRequest {
            request_id: id.to_string(),
            principal_id: "principal.legacy".to_string(),
            model_digest: "1".repeat(64),
            payload_digest: "2".repeat(64),
            maximum_tokens: 128,
            deadline_ms: 10_000,
            semantic_digest: "3".repeat(64),
        }
    }

    fn reservation_for(id: &str) -> Reservation {
        Reservation {
            reservation_id: format!("reservation.{id}"),
            quota_units: 100,
            maximum_tokens: 128,
            authority_epoch: 4,
            valid_until_ms: 9_000,
        }
    }

    fn assignment_for(id: &str) -> Assignment {
        Assignment {
            worker_id: format!("worker.{id}"),
            worker_generation: 2,
            assignment_digest: "4".repeat(64),
        }
    }

    fn observation_for(
        id: &str,
        status: Option<RequestState>,
        terminal_observed: bool,
    ) -> TerminalObservation {
        TerminalObservation {
            request_id: id.to_string(),
            reservation_id: format!("reservation.{id}"),
            worker_id: format!("worker.{id}"),
            worker_generation: 2,
            model_digest: "1".repeat(64),
            payload_digest: "2".repeat(64),
            terminal_observed,
            terminal_status: status,
            output_digest: terminal_observed.then(|| "5".repeat(64)),
            consumed_tokens: 64,
            usage_units: 50,
        }
    }

    fn submit_reserved_assigned(control: &mut DurableInferenceControl, id: &str) {
        control.submit(100, request_for(id)).unwrap();
        control.reserve(100, id, 1, reservation_for(id)).unwrap();
        control.assign(id, 2, assignment_for(id)).unwrap();
    }

    let path = path("checkpoint-all-legacy-states");
    let mut control = DurableInferenceControl::open(&path, 64).unwrap();

    control.submit(100, request_for("pending")).unwrap();

    control.submit(100, request_for("reserved")).unwrap();
    control
        .reserve(100, "reserved", 1, reservation_for("reserved"))
        .unwrap();

    submit_reserved_assigned(&mut control, "assigned");

    control.submit(100, request_for("cancel-pending")).unwrap();
    control.cancel("cancel-pending", 1).unwrap();

    control.submit(100, request_for("cancel-reserved")).unwrap();
    control
        .reserve(
            100,
            "cancel-reserved",
            1,
            reservation_for("cancel-reserved"),
        )
        .unwrap();
    control.cancel("cancel-reserved", 2).unwrap();

    submit_reserved_assigned(&mut control, "cancelling");
    control.cancel("cancelling", 3).unwrap();

    submit_reserved_assigned(&mut control, "completed");
    control
        .settle(
            "completed",
            3,
            "6".repeat(64),
            observation_for("completed", Some(RequestState::Completed), true),
        )
        .unwrap();

    submit_reserved_assigned(&mut control, "failed");
    control
        .settle(
            "failed",
            3,
            "6".repeat(64),
            observation_for("failed", Some(RequestState::Failed), true),
        )
        .unwrap();

    submit_reserved_assigned(&mut control, "cancelled-terminal");
    control.cancel("cancelled-terminal", 3).unwrap();
    control
        .settle(
            "cancelled-terminal",
            4,
            "6".repeat(64),
            observation_for("cancelled-terminal", Some(RequestState::Cancelled), true),
        )
        .unwrap();

    submit_reserved_assigned(&mut control, "indeterminate");
    control
        .settle(
            "indeterminate",
            3,
            "6".repeat(64),
            observation_for("indeterminate", None, false),
        )
        .unwrap();

    let expected = control.records.clone();
    let expected_headroom = control.journal_capacity_status().reserved_headroom_bytes;
    let receipt = control.compact_journal().unwrap();
    assert_eq!(receipt.legacy_records, expected.len());
    assert_eq!(receipt.native_records, 0);
    assert_eq!(receipt.reserved_headroom_bytes, expected_headroom);
    drop(control);

    let reopened = DurableInferenceControl::open(&path, 64).unwrap();
    assert_eq!(reopened.records, expected);
    assert_eq!(
        reopened.journal_capacity_status().reserved_headroom_bytes,
        expected_headroom
    );
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn one_writer_is_held_until_owner_drop() {
    let path = path("single-writer");
    let control = DurableInferenceControl::open(&path, 32).expect("first owner");
    assert!(matches!(
        DurableInferenceControl::open(&path, 32),
        Err(Error::WriterUnavailable)
    ));
    drop(control);
    let reopened = DurableInferenceControl::open(&path, 32).expect("owner releases on drop");
    drop(reopened);
    std::fs::remove_file(path).expect("cleanup");
}

#[test]
fn invalid_event_is_rejected_before_append() {
    let path = path("rejected-event");
    let mut control = DurableInferenceControl::open(&path, 32).expect("owner");
    assert_eq!(
        control.commit(Event::Cancel {
            request_id: "missing".to_string(),
            expected_revision: 1
        }),
        Err(Error::RequestNotFound)
    );
    assert_eq!(std::fs::metadata(&path).expect("metadata").len(), 0);
    drop(control);
    let reopened =
        DurableInferenceControl::open(&path, 32).expect("rejected event did not corrupt replay");
    drop(reopened);
    std::fs::remove_file(path).expect("cleanup");
}

#[path = "durable_incremental_tests.rs"]
mod incremental;
