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
fn committed_transition_retries_are_exactly_idempotent() {
    let path = path("exact-idempotence");
    let mut control = DurableInferenceControl::open(&path, 32).expect("open");
    control.submit(100, request()).expect("submit");

    let reserved = control
        .reserve(100, "request.1", 1, reservation())
        .expect("reserve");
    let after_reserve = fs::read(&path).expect("reserve bytes");
    let reserve_replay = control
        .reserve(100, "request.1", 1, reservation())
        .expect("reserve replay");
    assert!(reserve_replay.idempotent);
    assert_eq!(reserve_replay.revision, reserved.revision);
    assert_eq!(fs::read(&path).expect("reserve replay bytes"), after_reserve);

    let assigned = control
        .assign("request.1", 2, assignment())
        .expect("assign");
    let after_assign = fs::read(&path).expect("assign bytes");
    let assign_replay = control
        .assign("request.1", 2, assignment())
        .expect("assign replay");
    assert!(assign_replay.idempotent);
    assert_eq!(assign_replay.revision, assigned.revision);
    assert_eq!(fs::read(&path).expect("assign replay bytes"), after_assign);

    let cancelling = control.cancel("request.1", 3).expect("cancel");
    let after_cancel = fs::read(&path).expect("cancel bytes");
    let cancel_replay = control.cancel("request.1", 3).expect("cancel replay");
    assert!(cancel_replay.idempotent);
    assert_eq!(cancel_replay.revision, cancelling.revision);
    assert_eq!(fs::read(&path).expect("cancel replay bytes"), after_cancel);

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
    let settled = control
        .settle("request.1", 4, "6".repeat(64), observation.clone())
        .expect("settle");
    let after_settle = fs::read(&path).expect("settle bytes");
    let settle_replay = control
        .settle("request.1", 4, "6".repeat(64), observation)
        .expect("settle replay");
    assert!(settle_replay.idempotent);
    assert_eq!(settle_replay.revision, settled.revision);
    assert_eq!(fs::read(&path).expect("settle replay bytes"), after_settle);

    drop(control);
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
fn missing_terminal_observation_remains_open_until_terminal_reconciliation() {
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
        .expect("indeterminate settle");
    assert_eq!(receipt.state, RequestState::Indeterminate);
    assert!(!receipt.terminal_observed);
    drop(control);

    let mut reopened = DurableInferenceControl::open(&path, 32).expect("reopen");
    let before = fs::read(&path).expect("journal bytes");
    let repeated_unknown = TerminalObservation {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        worker_id: "worker.1".to_string(),
        worker_generation: 2,
        model_digest: "1".repeat(64),
        payload_digest: "2".repeat(64),
        terminal_observed: false,
        terminal_status: None,
        output_digest: None,
        consumed_tokens: 11,
        usage_units: 9,
    };
    assert_eq!(
        reopened.settle("request.1", 4, "7".repeat(64), repeated_unknown),
        Err(Error::InvalidTransition)
    );
    assert_eq!(fs::read(&path).expect("unchanged bytes"), before);

    let terminal = TerminalObservation {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        worker_id: "worker.1".to_string(),
        worker_generation: 2,
        model_digest: "1".repeat(64),
        payload_digest: "2".repeat(64),
        terminal_observed: true,
        terminal_status: Some(RequestState::Completed),
        output_digest: Some("5".repeat(64)),
        consumed_tokens: 12,
        usage_units: 10,
    };
    let reconciled = reopened
        .settle("request.1", 4, "8".repeat(64), terminal)
        .expect("terminal reconciliation");
    assert_eq!(reconciled.state, RequestState::Completed);
    assert!(reconciled.terminal_observed);
    drop(reopened);

    let final_reopen = DurableInferenceControl::open(&path, 32).expect("final reopen");
    assert_eq!(
        final_reopen.get("request.1").expect("record").state,
        RequestState::Completed
    );
    drop(final_reopen);
    fs::remove_file(path).expect("cleanup");
}

#[test]
fn independent_handles_share_only_short_mutation_writer_fences() {
    let path = path("short-writer-fence");
    let mut first = DurableInferenceControl::open(&path, 32).expect("first owner");
    let mut second = DurableInferenceControl::open(&path, 32).expect("second owner");
    first.submit(100, request()).expect("first mutation");
    assert_eq!(
        second.submit(100, request()).expect("peer refresh"),
        ControlReceipt {
            request_id: "request.1".to_string(),
            revision: 1,
            state: RequestState::Pending,
            idempotent: true,
            terminal_observed: false,
        }
    );
    drop(first);
    drop(second);
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
