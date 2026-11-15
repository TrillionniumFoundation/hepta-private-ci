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
fn owner_drop_releases_lock_with_duplicate_descriptor() {
    let path = path("inherited-writer-lock");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 32).expect("owner");
    control.submit(/*now_ms*/ 100, request()).expect("submit");
    let expected = control.get("request.1").cloned();
    // A concurrent fork can retain this same open file description until exec.
    let inherited = control.file.try_clone().expect("duplicate descriptor");
    assert!(matches!(
        DurableInferenceControl::open(&path, /*capacity*/ 32),
        Err(Error::WriterUnavailable)
    ));
    drop(control);

    let reopened =
        DurableInferenceControl::open(&path, /*capacity*/ 32).expect("owner releases its lock");
    assert_eq!(reopened.get("request.1"), expected.as_ref());
    drop(inherited);
    // Closing an old descriptor must not release the new owner's lock.
    assert!(matches!(
        DurableInferenceControl::open(&path, /*capacity*/ 32),
        Err(Error::WriterUnavailable)
    ));
    drop(reopened);
    let final_owner = DurableInferenceControl::open(&path, /*capacity*/ 32).expect("next owner");
    assert_eq!(final_owner.get("request.1"), expected.as_ref());
    drop(final_owner);
    fs::remove_file(path).expect("cleanup");
}

#[cfg(feature = "qualification-owned-file-read")]
#[test]
fn qualification_observes_physical_same_length_changes_and_retains_the_lock_and_cursor() {
    let path = path("physical-observation");
    // This negative-control fixture needs in-place write access. Production
    // append-only descriptors intentionally cannot perform that mutation on Windows.
    let mut options = OpenOptions::new();
    options.create_new(true).read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options.open(&path).expect("read/write fixture");
    let mut control =
        DurableInferenceControl::replay_file(file, &path, /*capacity*/ 32).expect("owner");
    control.submit(/*now_ms*/ 100, request()).expect("submit");
    let cached = control.get("request.1").cloned();
    let original = control
        .qualification_file_bytes(/*max_bytes*/ 1024 * 1024)
        .expect("bytes");
    assert!(matches!(
        DurableInferenceControl::open(&path, /*capacity*/ 32),
        Err(Error::WriterUnavailable)
    ));
    let mut changed = original.clone();
    changed[0] ^= 1;
    // Mutate the same locked descriptor without reopening or changing its length.
    // Cached state or file length cannot stand in for the byte observation.
    control.file.rewind().expect("rewind fixture");
    control
        .file
        .write_all(&changed)
        .expect("replace fixture bytes");
    control
        .file
        .seek(std::io::SeekFrom::Start(3))
        .expect("cursor");
    assert_eq!(
        control
            .qualification_file_bytes(/*max_bytes*/ 1024 * 1024)
            .expect("changed bytes"),
        changed
    );
    assert_eq!(control.file.stream_position().expect("restored cursor"), 3);
    assert_ne!(changed, original);
    assert_eq!(control.get("request.1"), cached.as_ref());
    assert!(matches!(
        DurableInferenceControl::open(&path, /*capacity*/ 32),
        Err(Error::WriterUnavailable)
    ));
    drop(control);
    fs::remove_file(path).expect("cleanup");
}

#[cfg(feature = "qualification-owned-file-read")]
#[test]
fn qualification_bound_failure_preserves_the_cursor_and_fences_further_writes() {
    let path = path("bounded-observation");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 32).expect("owner");
    control.submit(/*now_ms*/ 100, request()).expect("submit");
    let bytes = control
        .qualification_file_bytes(/*max_bytes*/ 1024 * 1024)
        .expect("bytes");
    control
        .file
        .seek(std::io::SeekFrom::Start(3))
        .expect("cursor");
    assert_eq!(
        control.qualification_file_bytes(/*max_bytes*/ 1),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(control.file.stream_position().expect("restored cursor"), 3);
    assert!(control.poisoned);
    assert_eq!(
        control
            .qualification_file_bytes(/*max_bytes*/ 1024 * 1024)
            .expect("physical bytes"),
        bytes
    );
    assert!(control.poisoned);
    assert_eq!(
        control.cancel("request.1", /*expected_revision*/ 1),
        Err(Error::WriterUnavailable)
    );
    drop(control);
    fs::remove_file(path).expect("cleanup");
}
