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
fn fsynced_neuron_dispatch_claim_survives_reopen_and_blocks_reexecution() {
    let path = path("single-use-dispatch");
    let mut control = DurableInferenceControl::open(&path, 32).expect("owner");
    control.submit(100, request()).expect("submit");
    control
        .reserve(100, "request.1", 1, reservation())
        .expect("reserve");
    control
        .assign("request.1", 2, assignment())
        .expect("assign");
    let before = fs::metadata(&path).expect("before").len();
    let claimed = control
        .claim_dispatch(100, "request.1", 3, "reservation.1", &assignment())
        .expect("fsynced claim");
    assert_eq!(claimed.state, RequestState::Dispatching);
    assert_eq!(claimed.revision, 4);
    assert!(!claimed.idempotent);
    let after = fs::metadata(&path).expect("after").len();
    assert!(
        after > before,
        "claim must be present in the same durable WAL"
    );
    assert_eq!(
        control.claim_dispatch(100, "request.1", 4, "reservation.1", &assignment()),
        Err(Error::InvalidTransition)
    );
    assert_eq!(fs::metadata(&path).unwrap().len(), after);
    drop(control);
    let mut recovered = DurableInferenceControl::open(&path, 32).expect("reopen");
    assert_eq!(
        recovered.get("request.1").unwrap().state,
        RequestState::Dispatching
    );
    assert_eq!(
        recovered.claim_dispatch(100, "request.1", 4, "reservation.1", &assignment()),
        Err(Error::InvalidTransition),
        "reopened Assigned must never be reconstructed from a Dispatching WAL"
    );
    assert_eq!(
        recovered.cancel("request.1", 4).unwrap().state,
        RequestState::Cancelling
    );
    let unobserved = TerminalObservation {
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
    let receipt = recovered
        .settle("request.1", 5, "9".repeat(64), unobserved)
        .expect("record uncertain terminal without false success");
    assert_eq!(receipt.state, RequestState::Indeterminate);
    drop(recovered);
    let opened = DurableInferenceControl::open(&path, 32).expect("reopen terminal");
    assert_eq!(
        opened.get("request.1").unwrap().state,
        RequestState::Indeterminate
    );
    drop(opened);
    fs::remove_file(path).expect("cleanup");
}

#[test]
fn dispatch_claim_rejects_mismatched_or_expired_inputs_without_appending() {
    let path = path("dispatch-preflight");
    let mut owner = DurableInferenceControl::open(&path, 32).unwrap();
    owner.submit(100, request()).unwrap();
    owner.reserve(100, "request.1", 1, reservation()).unwrap();
    owner.assign("request.1", 2, assignment()).unwrap();
    let before = fs::metadata(&path).unwrap().len();

    assert_eq!(
        owner.claim_dispatch(9_000, "request.1", 3, "reservation.1", &assignment()),
        Err(Error::InvalidTime)
    );
    assert_eq!(
        owner.claim_dispatch(100, "request.1", 3, "different", &assignment()),
        Err(Error::ReservationMismatch)
    );
    let mut wrong_worker = assignment();
    wrong_worker.worker_generation += 1;
    assert_eq!(
        owner.claim_dispatch(100, "request.1", 3, "reservation.1", &wrong_worker),
        Err(Error::AssignmentMismatch)
    );
    assert_eq!(
        owner.claim_dispatch(100, "request.1", 2, "reservation.1", &assignment()),
        Err(Error::StaleRevision)
    );
    assert_eq!(fs::metadata(&path).unwrap().len(), before);
    assert_eq!(
        owner.get("request.1").unwrap().state,
        RequestState::Assigned
    );
    drop(owner);
    fs::remove_file(path).unwrap();
}

#[test]
fn forged_dispatch_record_is_rejected_on_journal_replay() {
    let path = path("dispatch-forgery");
    let mut owner = DurableInferenceControl::open(&path, 32).unwrap();
    owner.submit(100, request()).unwrap();
    owner.reserve(100, "request.1", 1, reservation()).unwrap();
    owner.assign("request.1", 2, assignment()).unwrap();
    drop(owner);
    let mut file = OpenOptions::new().append(true).open(&path).unwrap();
    file.write_all(
        format!(
            "dispatch|request.1|3|not-the-reservation|worker.1|2|{}\n",
            "4".repeat(64)
        )
        .as_bytes(),
    )
    .unwrap();
    file.sync_all().unwrap();
    drop(file);
    assert!(matches!(
        DurableInferenceControl::open(&path, 32),
        Err(Error::ReservationMismatch)
    ));
    fs::remove_file(path).unwrap();
}

#[test]
fn reservation_id_cannot_move_between_requests_even_after_recovery() {
    let journal = path("global-reservation-id");
    let mut owner = DurableInferenceControl::open(&journal, 32).unwrap();
    let mut second = request();
    second.request_id = "request.2".to_string();
    second.semantic_digest = "a".repeat(64);
    owner.submit(100, request()).unwrap();
    owner.submit(100, second).unwrap();
    owner.reserve(100, "request.1", 1, reservation()).unwrap();

    let journal_before = fs::metadata(&journal).unwrap().len();
    assert_eq!(
        owner.reserve(100, "request.2", 1, reservation()),
        Err(Error::Conflict)
    );
    assert_eq!(fs::metadata(&journal).unwrap().len(), journal_before);
    assert_eq!(owner.get("request.2").unwrap().state, RequestState::Pending);
    let replay = owner.reserve(100, "request.1", 2, reservation()).unwrap();
    assert!(replay.idempotent);

    owner.cancel("request.1", 2).unwrap();
    assert_eq!(
        owner.reserve(100, "request.2", 1, reservation()),
        Err(Error::Conflict)
    );
    drop(owner);

    let mut reopened = DurableInferenceControl::open(&journal, 32).unwrap();
    assert_eq!(
        reopened.reserve(100, "request.2", 1, reservation()),
        Err(Error::Conflict)
    );
    let mut fresh = reservation();
    fresh.reservation_id = "reservation.2".to_string();
    assert_eq!(
        reopened
            .reserve(100, "request.2", 1, fresh)
            .unwrap()
            .revision,
        2
    );
    drop(reopened);
    let recovered = DurableInferenceControl::open(&journal, 32).unwrap();
    assert_eq!(
        recovered.get("request.2").unwrap().state,
        RequestState::Reserved
    );
    drop(recovered);
    fs::remove_file(&journal).unwrap();
}

#[test]
fn duplicate_reservation_id_in_durable_wal_fails_closed() {
    let journal = path("duplicate-reservation-id");
    let mut owner = DurableInferenceControl::open(&journal, 32).unwrap();
    let mut second = request();
    second.request_id = "request.2".to_string();
    second.semantic_digest = "a".repeat(64);
    owner.submit(100, request()).unwrap();
    owner.reserve(100, "request.1", 1, reservation()).unwrap();
    owner.submit(100, second).unwrap();
    drop(owner);

    let mut wal = OpenOptions::new().append(true).open(&journal).unwrap();
    wal.write_all(b"reserve|request.2|1|reservation.1|100|128|4|9000\n")
        .unwrap();
    wal.sync_all().unwrap();
    drop(wal);
    assert!(matches!(
        DurableInferenceControl::open(&journal, 32),
        Err(Error::CorruptJournal("reservation identity reused"))
    ));
    fs::remove_file(&journal).unwrap();
}

#[test]
fn large_request_table_updates_one_record_and_replays_exactly() {
    let journal = path("scoped-event-staging");
    let mut owner = DurableInferenceControl::open(&journal, 256).unwrap();

    // The original implementation cloned every retained request before
    // appending one event. Exercise many independent records plus the complete
    // legacy single-use transition through the same fsynced WAL.
    for index in 0..64 {
        let mut value = request();
        value.request_id = format!("request.{index}");
        value.semantic_digest = format!("{:064x}", index + 1);
        owner.submit(100, value).unwrap();
    }
    let unrelated = owner.get("request.63").unwrap().clone();

    let mut reserved = reservation();
    reserved.reservation_id = "reservation.0".to_owned();
    assert_eq!(
        owner
            .reserve(100, "request.0", 1, reserved.clone())
            .unwrap()
            .revision,
        2
    );
    assert_eq!(
        owner.assign("request.0", 2, assignment()).unwrap().revision,
        3
    );
    let dispatched = owner
        .claim_dispatch(100, "request.0", 3, "reservation.0", &assignment())
        .unwrap();
    assert_eq!(dispatched.state, RequestState::Dispatching);
    assert_eq!(dispatched.revision, 4);
    assert_eq!(*owner.get("request.63").unwrap(), unrelated);

    // The GLOBAL reservation ownership map must still reject a second
    // request, even though the staged transition holds only one record.
    let previous_len = fs::metadata(&journal).unwrap().len();
    assert_eq!(
        owner.reserve(100, "request.1", 1, reserved),
        Err(Error::Conflict)
    );
    assert_eq!(fs::metadata(&journal).unwrap().len(), previous_len);
    assert_eq!(owner.get("request.1").unwrap().revision, 1);

    drop(owner);
    let reopened = DurableInferenceControl::open(&journal, 256).unwrap();
    assert_eq!(
        reopened.get("request.0").unwrap().state,
        RequestState::Dispatching
    );
    assert_eq!(reopened.get("request.0").unwrap().revision, 4);
    assert_eq!(*reopened.get("request.63").unwrap(), unrelated);
    assert_eq!(
        reopened.get("request.1").unwrap().state,
        RequestState::Pending
    );
    drop(reopened);
    fs::remove_file(&journal).unwrap();
}

#[test]
fn malformed_legacy_submit_and_short_reservation_wal_fail_closed_on_replay() {
    let forged_submit = path("invalid-legacy-submit");
    fs::write(
        &forged_submit,
        format!(
            "submit|bad!request|principal.1|{}|{}|128|10000|{}\n",
            "1".repeat(64),
            "2".repeat(64),
            "3".repeat(64)
        ),
    )
    .unwrap();
    assert!(matches!(
        DurableInferenceControl::open(&forged_submit, 32),
        Err(Error::CorruptJournal("invalid legacy event fields"))
    ));
    fs::remove_file(&forged_submit).unwrap();

    let short = path("forged-short-reservation");
    let mut owner = DurableInferenceControl::open(&short, 32).unwrap();
    owner.submit(100, request()).unwrap();
    drop(owner);
    let mut wal = OpenOptions::new().append(true).open(&short).unwrap();
    wal.write_all(b"reserve|request.1|1|reservation.1|100|1|4|9000\n")
        .unwrap();
    wal.sync_all().unwrap();
    drop(wal);
    assert!(matches!(
        DurableInferenceControl::open(&short, 32),
        Err(Error::UsageExceeded)
    ));
    fs::remove_file(&short).unwrap();
}

#[test]
fn settlement_refuses_over_reserved_units_before_wal_append() {
    for terminal_observed in [false, true] {
        let path = path(if terminal_observed {
            "over-unit-terminal"
        } else {
            "over-unit-indeterminate"
        });
        let mut owner = DurableInferenceControl::open(&path, 32).unwrap();
        owner.submit(100, request()).unwrap();
        owner.reserve(100, "request.1", 1, reservation()).unwrap();
        owner.assign("request.1", 2, assignment()).unwrap();
        owner
            .claim_dispatch(100, "request.1", 3, "reservation.1", &assignment())
            .unwrap();
        let mut observed = TerminalObservation {
            request_id: "request.1".to_string(),
            reservation_id: "reservation.1".to_string(),
            worker_id: "worker.1".to_string(),
            worker_generation: 2,
            model_digest: "1".repeat(64),
            payload_digest: "2".repeat(64),
            terminal_observed,
            terminal_status: terminal_observed.then_some(RequestState::Completed),
            output_digest: terminal_observed.then(|| "5".repeat(64)),
            consumed_tokens: 1,
            usage_units: 101,
        };
        let bytes_before = fs::metadata(&path).unwrap().len();
        assert_eq!(
            owner.settle("request.1", 4, "6".repeat(64), observed.clone()),
            Err(Error::UsageExceeded)
        );
        assert_eq!(fs::metadata(&path).unwrap().len(), bytes_before);
        assert_eq!(owner.get("request.1").unwrap().revision, 4);
        assert_eq!(
            owner.get("request.1").unwrap().state,
            RequestState::Dispatching
        );
        // The exact reserved upper bound is still allowed and survives reopen.
        observed.usage_units = 100;
        owner
            .settle("request.1", 4, "7".repeat(64), observed)
            .unwrap();
        assert_eq!(owner.get("request.1").unwrap().usage_units, 100);
        assert_eq!(
            owner.get("request.1").unwrap().state,
            if terminal_observed {
                RequestState::Completed
            } else {
                RequestState::Indeterminate
            }
        );
        drop(owner);
        let recovered = DurableInferenceControl::open(&path, 32).unwrap();
        assert_eq!(recovered.get("request.1").unwrap().usage_units, 100);
        drop(recovered);
        fs::remove_file(path).unwrap();
    }
}

#[test]
fn forged_legacy_terminal_wal_cannot_relabel_or_overcharge_on_recovery() {
    for (case, observed_request, tokens, units, terminal, status, output) in [
        (
            "wrong-request",
            "request.2",
            1,
            1,
            "1",
            "completed",
            "5".repeat(64),
        ),
        (
            "over-quota",
            "request.1",
            129,
            1,
            "1",
            "completed",
            "5".repeat(64),
        ),
        (
            "over-billed-units",
            "request.1",
            1,
            101,
            "1",
            "completed",
            "5".repeat(64),
        ),
        (
            "over-billed-unknown",
            "request.1",
            1,
            101,
            "0",
            "none",
            "none".to_string(),
        ),
        (
            "invalid-terminal",
            "request.1",
            1,
            1,
            "0",
            "completed",
            "none".to_string(),
        ),
        (
            "missing-output",
            "request.1",
            1,
            1,
            "1",
            "completed",
            "none".to_string(),
        ),
    ] {
        let journal = path(case);
        let mut owner = DurableInferenceControl::open(&journal, 32).unwrap();
        owner.submit(100, request()).unwrap();
        owner.reserve(100, "request.1", 1, reservation()).unwrap();
        owner.assign("request.1", 2, assignment()).unwrap();
        drop(owner);

        let line = format!(
            "settle|request.1|3|{}|reservation.1|worker.1|2|{}|{}|{terminal}|{status}|{output}|{tokens}|{units}|{observed_request}\n",
            "6".repeat(64),
            "1".repeat(64),
            "2".repeat(64)
        );
        let mut wal = OpenOptions::new().append(true).open(&journal).unwrap();
        wal.write_all(line.as_bytes()).unwrap();
        wal.sync_all().unwrap();
        drop(wal);
        assert!(
            DurableInferenceControl::open(&journal, 32).is_err(),
            "forged historical terminal must be rejected: {case}"
        );
        fs::remove_file(&journal).unwrap();
    }
}

#[test]
fn poisoned_owner_never_acknowledges_idempotent_legacy_receipts() {
    let journal = path("poisoned-idempotent-legacy");
    let mut owner = DurableInferenceControl::open(&journal, 32).unwrap();
    owner.submit(100, request()).unwrap();
    // These toggles ONLY simulate separate post-fsync-failure points in a unit
    // test. Product code must never clear a poisoned owner without reopening.
    owner.poisoned = true;
    assert_eq!(owner.submit(100, request()), Err(Error::WriterUnavailable));
    assert_eq!(
        owner.reserve(100, "request.1", 1, reservation()),
        Err(Error::WriterUnavailable)
    );
    owner.poisoned = false;
    owner.reserve(100, "request.1", 1, reservation()).unwrap();
    owner.poisoned = true;
    assert_eq!(
        owner.reserve(100, "request.1", 2, reservation()),
        Err(Error::WriterUnavailable)
    );
    owner.poisoned = false;
    owner.assign("request.1", 2, assignment()).unwrap();
    owner.poisoned = true;
    assert_eq!(
        owner.assign("request.1", 3, assignment()),
        Err(Error::WriterUnavailable)
    );
    assert_eq!(
        owner.claim_dispatch(100, "request.1", 3, "reservation.1", &assignment()),
        Err(Error::WriterUnavailable)
    );
    owner.poisoned = false;
    owner.cancel("request.1", 3).unwrap();
    owner.poisoned = true;
    assert_eq!(owner.cancel("request.1", 4), Err(Error::WriterUnavailable));
    owner.poisoned = false;
    let observed = TerminalObservation {
        request_id: "request.1".to_owned(),
        reservation_id: "reservation.1".to_owned(),
        worker_id: "worker.1".to_owned(),
        worker_generation: 2,
        model_digest: "1".repeat(64),
        payload_digest: "2".repeat(64),
        terminal_observed: true,
        terminal_status: Some(RequestState::Completed),
        output_digest: Some("5".repeat(64)),
        consumed_tokens: 10,
        usage_units: 5,
    };
    owner
        .settle("request.1", 4, "6".repeat(64), observed.clone())
        .unwrap();
    owner.poisoned = true;
    assert_eq!(
        owner.settle("request.1", 5, "6".repeat(64), observed),
        Err(Error::WriterUnavailable)
    );
    drop(owner);
    // The real repair boundary is a fresh lock-acquiring journal replay, not a
    // resurrected in-memory receipt from the poisoned instance.
    let recovered = DurableInferenceControl::open(&journal, 32).unwrap();
    assert_eq!(
        recovered.get("request.1").unwrap().state,
        RequestState::Completed
    );
    drop(recovered);
    fs::remove_file(journal).unwrap();
}

#[test]
fn terminal_output_and_exact_idempotent_retry_survive_owner_reopen() {
    let journal = path("terminal-output-exact-idempotence");
    let mut owner = DurableInferenceControl::open(&journal, 32).unwrap();
    owner.submit(100, request()).unwrap();
    owner.reserve(100, "request.1", 1, reservation()).unwrap();
    owner.assign("request.1", 2, assignment()).unwrap();
    owner
        .claim_dispatch(100, "request.1", 3, "reservation.1", &assignment())
        .unwrap();
    let original = TerminalObservation {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        worker_id: "worker.1".to_string(),
        worker_generation: 2,
        model_digest: "1".repeat(64),
        payload_digest: "2".repeat(64),
        terminal_observed: true,
        terminal_status: Some(RequestState::Completed),
        output_digest: Some("5".repeat(64)),
        consumed_tokens: 10,
        usage_units: 5,
    };
    let committed = owner
        .settle("request.1", 4, "6".repeat(64), original.clone())
        .unwrap();
    assert_eq!(committed.state, RequestState::Completed);
    let written = fs::metadata(&journal).unwrap().len();
    assert!(owner
        .settle("request.1", committed.revision, "6".repeat(64), original.clone())
        .unwrap()
        .idempotent);

    let mut forged = original.clone();
    forged.output_digest = Some("7".repeat(64));
    assert_eq!(
        owner.settle("request.1", committed.revision, "6".repeat(64), forged),
        Err(Error::Conflict)
    );
    let mut forged = original.clone();
    forged.consumed_tokens += 1;
    assert_eq!(
        owner.settle("request.1", committed.revision, "6".repeat(64), forged),
        Err(Error::Conflict)
    );
    let mut forged = original.clone();
    forged.usage_units += 1;
    assert_eq!(
        owner.settle("request.1", committed.revision, "6".repeat(64), forged),
        Err(Error::Conflict)
    );
    assert_eq!(written, fs::metadata(&journal).unwrap().len());
    assert_eq!(
        owner
            .get("request.1")
            .unwrap()
            .terminal_output_digest
            .as_deref(),
        Some("5".repeat(64).as_str())
    );

    drop(owner);
    let mut reopened = DurableInferenceControl::open(&journal, 32).unwrap();
    assert_eq!(
        reopened
            .get("request.1")
            .unwrap()
            .terminal_output_digest
            .as_deref(),
        Some("5".repeat(64).as_str())
    );
    assert!(reopened
        .settle("request.1", committed.revision, "6".repeat(64), original.clone())
        .unwrap()
        .idempotent);
    let mut forged = original;
    forged.output_digest = Some("8".repeat(64));
    assert_eq!(
        reopened.settle("request.1", committed.revision, "6".repeat(64), forged),
        Err(Error::Conflict)
    );
    assert_eq!(written, fs::metadata(&journal).unwrap().len());
    drop(reopened);
    fs::remove_file(journal).unwrap();
}
