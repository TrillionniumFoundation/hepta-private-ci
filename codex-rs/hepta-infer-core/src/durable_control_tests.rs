use super::*;
use std::io::SeekFrom;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

// Inspect the original locked file without reopening its pathname. Restore the
// real cursor even after a read failure, and propagate restoration failures.
pub(super) fn held_journal_bytes(mut file: &File) -> std::io::Result<Vec<u8>> {
    let position = file.stream_position()?;
    let read = (|| {
        file.rewind()?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        Ok(bytes)
    })();
    file.seek(SeekFrom::Start(position))?;
    read
}

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
    let mut control = DurableInferenceControl::replay_file(
        file, &path, /*capacity*/ 32, /*writer_lock*/ None,
    )
    .expect("owner");
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

#[derive(Debug, Default)]
struct RecordedWalMetrics(std::sync::Mutex<Vec<PhaseMetricEventV1>>);

impl PhaseMetricSinkV1 for RecordedWalMetrics {
    fn record(
        &self,
        event: PhaseMetricEventV1,
    ) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        self.0.lock().unwrap().push(event);
        Ok(())
    }

    fn healthy(&self) -> bool {
        true
    }

    fn flush(&self) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        Ok(())
    }
}

#[test]
fn native_and_legacy_wal_fsync_emit_non_authorizing_phase_metrics() {
    let path = path("wal-metrics");
    let sink = std::sync::Arc::new(RecordedWalMetrics::default());
    let mut owner = DurableInferenceControl::open(&path, 32)
        .unwrap()
        .with_metrics_sink(sink.clone());
    assert!(owner.production_metrics_ready());
    owner.submit(100, request()).expect("legacy fsync");
    owner
        .reserve_native(
            native::NativeRequest {
                request_id: "native.1".to_string(),
                principal_id: "principal.1".to_string(),
                worker_generation: 2,
                model: "model".to_string(),
                payload_digest: "a".repeat(64),
            },
            1,
        )
        .expect("native fsync");
    assert!(owner.flush_production_metrics());
    {
        let events = sink.0.lock().unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].phase, PhaseMetricKindV1::Wal);
        assert!(events[0].succeeded);
        assert!(!events[0].scope_digest.is_zero());
        assert!(!events[0].operation_digest.is_zero());
    }
    drop(owner);
    let reopened = DurableInferenceControl::open(&path, 32).unwrap();
    assert_eq!(reopened.get("request.1").unwrap().revision, 1);
    assert!(reopened.native_record("native.1").is_some());
    assert!(!reopened.production_metrics_ready());
    drop(reopened);
    fs::remove_file(path).unwrap();
}

#[derive(Debug)]
struct RejectWalMetrics;

impl PhaseMetricSinkV1 for RejectWalMetrics {
    fn record(
        &self,
        _event: PhaseMetricEventV1,
    ) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        Err(codex_hepta_types::PhaseMetricSinkErrorV1::Unavailable)
    }

    fn healthy(&self) -> bool {
        false
    }

    fn flush(&self) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        Err(codex_hepta_types::PhaseMetricSinkErrorV1::Unavailable)
    }
}

#[test]
fn evidence_outage_is_not_an_authorization_failure_or_wal_retry() {
    let path = path("wal-telemetry-failed");
    let mut owner = DurableInferenceControl::open(&path, 32)
        .unwrap()
        .with_metrics_sink(std::sync::Arc::new(RejectWalMetrics));
    assert!(!owner.production_metrics_ready());
    assert_eq!(owner.submit(100, request()).unwrap().revision, 1);
    assert!(!owner.production_metrics_ready());
    assert!(!owner.flush_production_metrics());
    // The WAL is still held under an exclusive writer lock. Reopening it
    // with fs::read is forbidden by Windows share-mode semantics.
    let committed_length = owner.file.metadata().unwrap().len();
    assert_eq!(owner.submit(100, request()).unwrap().revision, 1);
    assert_eq!(
        owner.file.metadata().unwrap().len(),
        committed_length,
        "idempotent submit must not append another WAL event"
    );
    drop(owner);
    let reopened = DurableInferenceControl::open(&path, 32).unwrap();
    assert_eq!(reopened.get("request.1").unwrap().revision, 1);
    drop(reopened);
    fs::remove_file(path).unwrap();
}

// Direct library callers cannot bypass the higher-level worker's unsupported
// platform denial by opening the production WAL independently.
#[cfg(not(unix))]
#[test]
fn production_control_refuses_unsupported_platform() {
    let path = path("non-unix-production");
    assert!(matches!(
        DurableInferenceControl::open_production(&path, 32),
        Err(Error::InvalidIdentity(_))
    ));
    assert!(!path.exists());
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

#[path = "durable_incremental_tests.rs"]
mod incremental;

#[test]
fn held_journal_observation_preserves_physical_bytes_cursor_and_lock() {
    let path = path("held-journal-observation");
    let mut file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&path)
        .expect("physical journal fixture");
    file.try_lock().expect("exclusive journal lock");
    let original = b"original journal evidence\n".to_vec();
    file.write_all(&original).expect("write original bytes");
    let contender = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("independent contender handle");
    assert!(matches!(
        contender.try_lock(),
        Err(std::fs::TryLockError::WouldBlock)
    ));

    file.seek(SeekFrom::Start(3)).expect("initial cursor");
    assert_eq!(held_journal_bytes(&file).expect("original bytes"), original);
    assert_eq!(file.stream_position().expect("restored cursor"), 3);
    let mut changed = original;
    changed[0] ^= 1;
    file.rewind().expect("rewind physical fixture");
    file.write_all(&changed)
        .expect("same-length physical mutation");
    file.seek(SeekFrom::Start(3)).expect("changed cursor");
    assert_eq!(held_journal_bytes(&file).expect("changed bytes"), changed);
    assert_eq!(file.stream_position().expect("restored cursor"), 3);
    assert!(matches!(
        contender.try_lock(),
        Err(std::fs::TryLockError::WouldBlock)
    ));
    drop(file);

    let mut write_only = OpenOptions::new()
        .write(true)
        .open(&path)
        .expect("actual unreadable descriptor");
    write_only.try_lock().expect("exclusive write-only lock");
    write_only.seek(SeekFrom::Start(3)).expect("failure cursor");
    assert!(held_journal_bytes(&write_only).is_err());
    assert_eq!(write_only.stream_position().expect("restored cursor"), 3);
    assert!(matches!(
        contender.try_lock(),
        Err(std::fs::TryLockError::WouldBlock)
    ));
    drop(write_only);
    contender.try_lock().expect("owner drop releases lock");
    drop(contender);
    fs::remove_file(path).expect("cleanup");
}
