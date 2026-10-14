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


#[test]
fn signed_effect_marker_is_fsynced_and_recovered_without_reexecution() {
    let journal = path("signed-effect-recover");
    let digest = "a".repeat(64);
    {
        let mut control = DurableInferenceControl::open(&journal, 32).expect("exclusive journal");
        control.submit(100, request()).expect("submit");
        control.reserve(100, "request.1", 1, reservation()).expect("reserve");
        control.assign("request.1", 2, assignment()).expect("assign");
        let entered = control
            .begin_effect("request.1", 3, digest.clone())
            .expect("durable pre-effect marker");
        assert_eq!(entered.revision, 4);
        assert_eq!(entered.state, RequestState::Assigned);
        assert!(!entered.terminal_observed);
        assert_eq!(
            control.get("request.1").unwrap().effect_binding_digest.as_deref(),
            Some(digest.as_str())
        );
        assert_eq!(
            control.begin_effect("request.1", 4, digest.clone()),
            Err(Error::InvalidTransition),
        );
        assert_eq!(
            control.begin_effect("request.1", 3, digest.clone()),
            Err(Error::StaleRevision),
        );
        assert_eq!(
            DurableInferenceControl::open(&journal, 32).unwrap_err(),
            Error::WriterUnavailable,
        );
    }
    let mut recovered =
        DurableInferenceControl::open(&journal, 32).expect("replay exact effect fence");
    let existing = recovered.get("request.1").expect("replayed record");
    assert_eq!(existing.state, RequestState::Assigned);
    assert_eq!(existing.revision, 4);
    assert_eq!(existing.effect_binding_digest.as_deref(), Some(digest.as_str()));
    // This is not evidence of a completed effect; a restarted Worker MUST
    // reconcile rather than resending the already marked dispatch.
    assert_eq!(
        recovered.begin_effect("request.1", 4, digest),
        Err(Error::InvalidTransition),
    );
    drop(recovered);
    std::fs::remove_file(journal).expect("cleanup");
}

#[test]
fn failed_effect_marker_never_mutates_the_wal_or_allows_late_cancelled_entry() {
    let journal = path("effect-denials");
    let mut control = DurableInferenceControl::open(&journal, 16).expect("journal");
    control.submit(100, request()).expect("submit");
    let original_len = std::fs::metadata(&journal).unwrap().len();
    assert_eq!(
        control.begin_effect("request.1", 1, "b".repeat(64)),
        Err(Error::InvalidTransition),
    );
    assert_eq!(
        control.begin_effect("request.1", 1, "0".repeat(64)),
        Err(Error::InvalidDigest("final-use binding")),
    );
    assert_eq!(std::fs::metadata(&journal).unwrap().len(), original_len);
    control.reserve(100, "request.1", 1, reservation()).expect("reserve");
    control.assign("request.1", 2, assignment()).expect("assign");
    control.cancel("request.1", 3).expect("cancel");
    assert_eq!(
        control.begin_effect("request.1", 4, "b".repeat(64)),
        Err(Error::InvalidTransition),
    );
    assert!(control.get("request.1").unwrap().effect_binding_digest.is_none());
    drop(control);
    std::fs::remove_file(journal).expect("cleanup");
}

#[test]
fn effect_marker_does_not_forge_terminal_receipt_or_change_legacy_settlement() {
    let journal = path("effect-settle");
    let mut control = DurableInferenceControl::open(&journal, 8).expect("journal");
    control.submit(100, request()).expect("submit");
    control.reserve(100, "request.1", 1, reservation()).expect("reserve");
    control.assign("request.1", 2, assignment()).expect("assign");
    control
        .begin_effect("request.1", 3, "a".repeat(64))
        .expect("pre-effect write");
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
        consumed_tokens: 0,
        usage_units: 0,
    };
    let settled = control
        .settle("request.1", 4, "d".repeat(64), observation)
        .expect("record uncertain terminal observation");
    assert_eq!(settled.state, RequestState::Indeterminate);
    assert!(!settled.terminal_observed);
    assert_eq!(
        control.get("request.1").unwrap().effect_binding_digest.as_deref(),
        Some("a".repeat(64).as_str()),
    );
    drop(control);
    let reopened = DurableInferenceControl::open(&journal, 8).unwrap();
    assert_eq!(reopened.get("request.1").unwrap().state, RequestState::Indeterminate);
    drop(reopened);
    std::fs::remove_file(journal).expect("cleanup");
}
