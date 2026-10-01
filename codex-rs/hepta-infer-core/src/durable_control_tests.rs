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

fn observation() -> TerminalObservation {
    TerminalObservation {
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
    }
}

#[test]
fn reservation_rejects_request_that_expired_after_submission() {
    let path = path("expired-request");
    let mut control = DurableInferenceControl::open(&path, 32).expect("open");
    control.submit(100, request()).expect("submit");
    let mut live_reservation = reservation();
    live_reservation.valid_until_ms = 20_000;
    assert_eq!(
        control.reserve(10_000, "request.1", 1, live_reservation),
        Err(Error::InvalidTime)
    );
    assert_eq!(
        control.get("request.1").expect("record").state,
        RequestState::Pending
    );
    drop(control);
    fs::remove_file(path).expect("cleanup");
}

#[test]
fn settlement_rejects_quota_overrun_and_same_digest_usage_drift() {
    let path = path("usage-binding");
    let mut control = DurableInferenceControl::open(&path, 32).expect("open");
    control.submit(100, request()).expect("submit");
    control
        .reserve(100, "request.1", 1, reservation())
        .expect("reserve");
    control
        .assign("request.1", 2, assignment())
        .expect("assign");
    let mut excessive = observation();
    excessive.usage_units = 101;
    assert_eq!(
        control.settle("request.1", 3, "6".repeat(64), excessive),
        Err(Error::UsageExceeded)
    );
    control
        .settle("request.1", 3, "6".repeat(64), observation())
        .expect("settle");
    assert!(
        control
            .settle("request.1", 4, "6".repeat(64), observation())
            .expect("retry")
            .idempotent
    );
    let mut changed = observation();
    changed.usage_units = 51;
    assert_eq!(
        control.settle("request.1", 4, "6".repeat(64), changed),
        Err(Error::Conflict)
    );
    drop(control);
    fs::remove_file(path).expect("cleanup");
}

#[test]
fn same_digest_output_drift_is_rejected_before_and_after_legacy_journal_replay() {
    let path = path("full-observation-binding");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 32).expect("open");
    control.submit(/*now_ms*/ 100, request()).expect("submit");
    control
        .reserve(
            /*now_ms*/ 100,
            "request.1",
            /*expected_revision*/ 1,
            reservation(),
        )
        .expect("reserve");
    control
        .assign("request.1", /*expected_revision*/ 2, assignment())
        .expect("assign");
    control
        .settle(
            "request.1",
            /*expected_revision*/ 3,
            "6".repeat(64),
            observation(),
        )
        .expect("settle");
    let original_bytes = fs::read(&path).expect("original V1 journal bytes");
    for reopen in [false, true] {
        if reopen {
            drop(control);
            control = DurableInferenceControl::open(&path, /*capacity*/ 32)
                .expect("replay unchanged V1 journal");
        }
        let original = control.get("request.1").expect("original record").clone();
        assert!(
            control
                .settle(
                    "request.1",
                    /*expected_revision*/ 4,
                    "6".repeat(64),
                    observation()
                )
                .expect("exact retry")
                .idempotent
        );
        let mut changed = observation();
        changed.output_digest = Some("7".repeat(64));
        assert_eq!(
            control.settle(
                "request.1",
                /*expected_revision*/ 4,
                "6".repeat(64),
                changed
            ),
            Err(Error::Conflict)
        );
        assert_eq!(
            control.settle(
                "request.1",
                /*expected_revision*/ 3,
                "6".repeat(64),
                observation()
            ),
            Err(Error::StaleRevision)
        );
        assert_eq!(control.get("request.1"), Some(&original));
        assert_eq!(fs::read(&path).expect("unchanged journal"), original_bytes);
    }
    drop(control);
    fs::remove_file(path).expect("cleanup");
}

#[test]
fn replay_revalidates_event_semantics_and_terminal_bindings() {
    let mut invalid_request = request();
    invalid_request.model_digest = "0".repeat(64);
    let mut invalid_reservation = reservation();
    invalid_reservation.maximum_tokens = 1;
    let mut invalid_assignment = assignment();
    invalid_assignment.worker_generation = 0;
    let mut wrong_worker = observation();
    wrong_worker.worker_id = "worker.other".to_string();
    let mut missing_output = observation();
    missing_output.output_digest = None;
    let mut excessive_usage = observation();
    excessive_usage.usage_units = 101;
    let valid_prefix = [
        Event::Submit(request()),
        Event::Reserve {
            request_id: "request.1".to_string(),
            expected_revision: 1,
            reservation: reservation(),
        },
        Event::Assign {
            request_id: "request.1".to_string(),
            expected_revision: 2,
            assignment: assignment(),
        },
    ];
    let invalid_events = [
        (0, Event::Submit(invalid_request)),
        (
            1,
            Event::Reserve {
                request_id: "request.1".to_string(),
                expected_revision: 1,
                reservation: invalid_reservation,
            },
        ),
        (
            2,
            Event::Assign {
                request_id: "request.1".to_string(),
                expected_revision: 2,
                assignment: invalid_assignment,
            },
        ),
        (
            3,
            Event::Settle {
                request_id: "request.1".to_string(),
                expected_revision: 3,
                observation_digest: "6".repeat(64),
                observation: wrong_worker,
            },
        ),
        (
            3,
            Event::Settle {
                request_id: "request.1".to_string(),
                expected_revision: 3,
                observation_digest: "6".repeat(64),
                observation: missing_output,
            },
        ),
        (
            3,
            Event::Settle {
                request_id: "request.1".to_string(),
                expected_revision: 3,
                observation_digest: "6".repeat(64),
                observation: excessive_usage,
            },
        ),
    ];
    for (prefix_length, event) in invalid_events {
        let path = path("invalid-replay");
        let journal = valid_prefix[..prefix_length]
            .iter()
            .chain(std::iter::once(&event))
            .map(|event| format!("{}\n", encode_event(event)))
            .collect::<String>();
        fs::write(&path, journal).expect("write fixture");
        assert!(DurableInferenceControl::open(&path, 32).is_err());
        fs::remove_file(path).expect("cleanup");
    }
}
