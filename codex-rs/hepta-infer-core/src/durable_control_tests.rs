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

fn native_request(id: &str) -> native::NativeRequest {
    native::NativeRequest {
        request_id: id.to_string(),
        principal_id: "native-principal".to_string(),
        worker_generation: 1,
        model: "native-model".to_string(),
        payload_digest: "a".repeat(64),
    }
}

#[test]
fn failed_legacy_append_preserves_all_records() {
    let location = path("failed-legacy-append");
    let mut owner = DurableInferenceControl::open(&location, 8).expect("owner");
    owner.submit(100, request()).expect("target");
    let mut unrelated = request();
    unrelated.request_id = "unrelated".to_string();
    owner.submit(100, unrelated).expect("unrelated");
    owner
        .reserve_native(native_request("native"), 1)
        .expect("native record");
    let legacy_before = owner.records.clone();
    let native_before = owner.native.records.clone();
    let journal_bytes_before = owner.journal_bytes;
    drop(owner);
    let bytes_before = fs::read(&location).expect("committed bytes");
    let mut owner = DurableInferenceControl::open(&location, 8).expect("reopen");
    let held_writer = std::mem::replace(
        &mut owner.file,
        File::open(&location).expect("read-only append handle"),
    );
    assert!(matches!(owner.cancel("request.1", 1), Err(Error::Io(_))));
    assert!(owner.poisoned);
    assert_eq!(owner.records, legacy_before);
    assert_eq!(owner.native.records, native_before);
    assert_eq!(owner.journal_bytes, journal_bytes_before);
    assert_eq!(owner.cancel("unrelated", 1), Err(Error::WriterUnavailable));
    assert!(matches!(
        DurableInferenceControl::open(&location, 8),
        Err(Error::WriterUnavailable)
    ));
    drop(owner);
    drop(held_writer);
    assert_eq!(fs::read(&location).expect("unchanged bytes"), bytes_before);
    let recovered = DurableInferenceControl::open(&location, 8).expect("recover");
    assert_eq!(recovered.records, legacy_before);
    assert_eq!(recovered.native.records, native_before);
    drop(recovered);
    fs::remove_file(location).expect("cleanup");
}

#[test]
fn legacy_mutation_keeps_unrelated_record_storage() {
    let location = path("legacy-no-unrelated-clone");
    let mut owner = DurableInferenceControl::open(&location, 8).expect("owner");
    owner.submit(100, request()).expect("target");
    let mut unrelated = request();
    unrelated.request_id = "unrelated".to_string();
    owner.submit(100, unrelated).expect("unrelated");
    let before = owner.get("unrelated").expect("unrelated").clone();
    let payload_buffer = owner
        .get("unrelated")
        .expect("unrelated")
        .request
        .payload_digest
        .as_ptr();
    owner.cancel("request.1", 1).expect("cancel target");
    let after = owner.get("unrelated").expect("unrelated");
    assert_eq!(after, &before);
    assert_eq!(
        after.request.payload_digest.as_ptr(),
        payload_buffer,
        "a mutation must not replace an unrelated live payload allocation"
    );
    drop(owner);
    let recovered = DurableInferenceControl::open(&location, 8).expect("reopen");
    assert_eq!(recovered.get("unrelated"), Some(&before));
    drop(recovered);
    fs::remove_file(location).expect("cleanup");
}

fn mixed_journal_frames(
    legacy_id: &str,
    native_id: &str,
) -> (Vec<u8>, Vec<u8>, RequestRecord, native::NativeRunRecord) {
    let location = path("mixed-namespace-source");
    let mut legacy = DurableInferenceControl::open(&location, 8).expect("legacy owner");
    let mut requested = request();
    requested.request_id = legacy_id.to_string();
    legacy.submit(100, requested).expect("legacy submit");
    legacy.cancel(legacy_id, 1).expect("valid legacy tail");
    let legacy_record = legacy.get(legacy_id).expect("legacy record").clone();
    drop(legacy);
    let legacy_bytes = fs::read(&location).expect("legacy frames");
    fs::remove_file(&location).expect("remove legacy fixture");

    let mut native = DurableInferenceControl::open(&location, 8).expect("native owner");
    native
        .reserve_native(native_request(native_id), 1)
        .expect("native reserve");
    let native_record = native
        .stop_native_before_dispatch(native_id, "before effect".to_string())
        .expect("valid native tail");
    drop(native);
    let native_bytes = fs::read(&location).expect("native frames");
    fs::remove_file(location).expect("remove native fixture");
    (legacy_bytes, native_bytes, legacy_record, native_record)
}

#[test]
fn mixed_namespace_replay_rejects_collisions_in_both_orders() {
    let (legacy, native, _, _) = mixed_journal_frames("collision", "collision");
    for frames in [
        [legacy.as_slice(), native.as_slice()],
        [native.as_slice(), legacy.as_slice()],
    ] {
        let location = path("mixed-collision");
        // Let the production constructor establish the private journal mode.
        drop(DurableInferenceControl::open(&location, 8).expect("private fixture"));
        let bytes = frames.concat();
        fs::write(&location, &bytes).expect("write colliding histories");
        assert!(matches!(
            DurableInferenceControl::open(&location, 8),
            Err(Error::CapacityExceeded)
        ));
        assert_eq!(fs::read(&location).expect("unchanged journal"), bytes);
        fs::remove_file(location).expect("cleanup");
    }
}

#[test]
fn mixed_namespace_replay_preserves_noncolliding_records_in_both_orders() {
    let (legacy, native, legacy_record, native_record) = mixed_journal_frames("legacy", "native");
    for frames in [
        [legacy.as_slice(), native.as_slice()],
        [native.as_slice(), legacy.as_slice()],
    ] {
        let location = path("mixed-valid");
        drop(DurableInferenceControl::open(&location, 8).expect("private fixture"));
        let bytes = frames.concat();
        fs::write(&location, &bytes).expect("write valid histories");
        let recovered = DurableInferenceControl::open(&location, 8).expect("mixed replay");
        assert_eq!(recovered.records.len(), 1);
        assert_eq!(recovered.native.records.len(), 1);
        assert_eq!(recovered.get("legacy"), Some(&legacy_record));
        assert_eq!(recovered.native_record("native"), Some(&native_record));
        drop(recovered);
        assert_eq!(fs::read(&location).expect("unchanged journal"), bytes);
        fs::remove_file(location).expect("cleanup");
    }
}
