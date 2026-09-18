use super::*;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn path(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!("hepta-native-{label}-{nonce}.journal"))
}

fn request(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.to_string(),
        principal_id: "agent-1".to_string(),
        worker_generation: 4,
        model: "actual-model".to_string(),
        payload_digest: "a".repeat(64),
    }
}

fn dispatch() -> NativeDispatch {
    NativeDispatch {
        thread_id: "thread-1".to_string(),
        model_provider: "provider".to_string(),
        context_digest: "b".repeat(64),
    }
}

fn output(status: NativeRunStatus, tokens: Option<u64>) -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        model: "actual-model".to_string(),
        model_provider: "provider".to_string(),
        terminal_observed: status != NativeRunStatus::Indeterminate,
        status,
        output: "observed text".to_string(),
        observed_output_tokens: tokens,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::Unverified,
    }
}

fn start(control: &mut DurableInferenceControl, id: &str) {
    control.reserve_native(request(id), 1).unwrap();
    control.dispatch_native(id, dispatch()).unwrap();
    control.native_started(id, "turn-1".to_string()).unwrap();
}

#[test]
fn concurrent_handles_share_budget_without_holding_the_lock_during_execution() {
    let path = path("concurrent-handles");
    // Both handles open before either request is admitted. Historically the
    // second open failed because the first handle retained the exclusive lock
    // for its full lifetime.
    let mut first = DurableInferenceControl::open(&path, 8).unwrap();
    let mut second = DurableInferenceControl::open(&path, 8).unwrap();

    let r1 = first.reserve_native(request("r1"), 2).unwrap();
    let r2 = second.reserve_native(request("r2"), 2).unwrap();
    assert_eq!(r1.state, NativeReservationState::Reserved);
    assert_eq!(r2.state, NativeReservationState::Reserved);

    // Each mutation refreshes under the short writer fence, so both handles
    // can progress against the same durable budget without stale overwrite.
    first.dispatch_native("r1", dispatch()).unwrap();
    let mut d2 = dispatch();
    d2.thread_id = "thread-2".to_string();
    second.dispatch_native("r2", d2).unwrap();

    drop(first);
    drop(second);
    let reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(
        reopened.native_record("r1").unwrap().state,
        NativeReservationState::Dispatching
    );
    assert_eq!(
        reopened.native_record("r2").unwrap().state,
        NativeReservationState::Dispatching
    );
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn stale_handle_reopens_current_inode_after_peer_compaction() {
    let path = path("peer-compaction");
    let mut first = DurableInferenceControl::open(&path, 8).unwrap();
    let mut second = DurableInferenceControl::open(&path, 8).unwrap();

    first.reserve_native(request("r1"), 2).unwrap();
    second.reserve_native(request("r2"), 2).unwrap();
    let archive = second.compact_with_archive().unwrap();

    // `first` was opened before the atomic journal replacement. Its next
    // mutation must reopen the current pathname while holding the sidecar fence
    // instead of appending to the retired inode.
    first.dispatch_native("r1", dispatch()).unwrap();
    drop(first);
    drop(second);

    let reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(
        reopened.native_record("r1").unwrap().state,
        NativeReservationState::Dispatching
    );
    assert_eq!(
        reopened.native_record("r2").unwrap().state,
        NativeReservationState::Reserved
    );
    drop(reopened);

    std::fs::remove_file(&path).unwrap();
    std::fs::remove_file(&archive).unwrap();
    let lock = path.with_file_name(format!(
        "{}.writer.lock",
        path.file_name().unwrap().to_string_lossy()
    ));
    let _ = std::fs::remove_file(lock);
}

#[test]
fn compaction_archives_full_history_and_preserves_indeterminate_fences() {
    let path = path("compact");
    let mut control = DurableInferenceControl::open(&path, 16).unwrap();

    start(&mut control, "r1");
    let released = control
        .settle_native("r1", output(NativeRunStatus::Completed, Some(9)))
        .unwrap();

    start(&mut control, "r2");
    let indeterminate = control
        .settle_native("r2", output(NativeRunStatus::Indeterminate, None))
        .unwrap();

    let bytes_before = std::fs::read(&path).unwrap();
    let archive = control.compact_with_archive().unwrap();
    assert!(archive.is_file());
    assert_eq!(std::fs::read(&archive).unwrap(), bytes_before);
    // Small histories can grow by the fixed checkpoint/header overhead.
    // Require canonical bounded state here; growth tests separately require
    // byte reduction for histories large enough to amortize that overhead.
    let checkpoint = std::fs::read_to_string(&path).unwrap();
    assert_eq!(checkpoint.lines().count(), 3);
    assert_eq!(
        checkpoint
            .lines()
            .filter(|line| line.starts_with(CHECKPOINT_PREFIX))
            .count(),
        2
    );
    assert!(
        !checkpoint
            .lines()
            .any(|line| line.starts_with(JOURNAL_PREFIX))
    );

    drop(control);
    let mut reopened = DurableInferenceControl::open(&path, 16).unwrap();
    assert_eq!(reopened.native_record("r1"), Some(&released));
    assert_eq!(reopened.native_record("r2"), Some(&indeterminate));
    // The unknown external outcome still owns the journal's single slot after
    // compaction; rotation cannot make it replayable or pretend it terminated.
    assert_eq!(
        reopened.reserve_native(request("r3"), 1),
        Err(Error::CapacityExceeded)
    );
    drop(reopened);

    // Active checkpoints are not self-sufficient audit history: the header
    // binds the predecessor archive, and loss of that archive fails closed.
    std::fs::remove_file(&archive).unwrap();
    assert!(DurableInferenceControl::open(&path, 16).is_err());

    std::fs::remove_file(&path).unwrap();
    let lock = path.with_file_name(format!(
        "{}.writer.lock",
        path.file_name().unwrap().to_string_lossy()
    ));
    let _ = std::fs::remove_file(lock);
}

#[test]
fn duplicate_reopen_preserves_exact_binding_and_reserves_only_once() {
    let path = path("duplicate");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let reserved = control.reserve_native(request("r1"), 1).unwrap();
    assert_eq!(control.reserve_native(request("r1"), 1).unwrap(), reserved);
    let mut changed = request("r1");
    changed.worker_generation += 1;
    assert_eq!(control.reserve_native(changed, 1), Err(Error::Conflict));
    assert_eq!(
        control.reserve_native(request("r1"), 2),
        Err(Error::Conflict)
    );
    assert_eq!(
        control.reserve_native(request("r2"), 1),
        Err(Error::CapacityExceeded)
    );
    control.dispatch_native("r1", dispatch()).unwrap();
    let expected = control.native_record("r1").unwrap().clone();
    drop(control);
    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(reopened.reserve_native(request("r1"), 1).unwrap(), expected);
    assert_eq!(
        reopened.dispatch_native("r1", dispatch()),
        Err(Error::InvalidTransition)
    );
    assert_eq!(
        reopened.reserve_native(request("r2"), 1),
        Err(Error::CapacityExceeded)
    );
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn unknown_execution_holds_slot_and_late_terminal_settles_real_usage() {
    let path = path("unknown");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    let unknown = control
        .settle_native("r1", output(NativeRunStatus::Indeterminate, None))
        .unwrap();
    assert_eq!(unknown.state, NativeReservationState::Indeterminate);
    assert_eq!(unknown.observation.unwrap().observed_output_tokens, None);
    assert_eq!(
        control.reserve_native(request("r2"), 1),
        Err(Error::CapacityExceeded)
    );
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    // No synthetic u32 cap is allowed to erase an actually observed overrun.
    let terminal = output(NativeRunStatus::Completed, Some(u64::from(u32::MAX) + 1));
    let settled = control.settle_native("r1", terminal.clone()).unwrap();
    assert_eq!(settled.state, NativeReservationState::Released);
    assert_eq!(control.settle_native("r1", terminal).unwrap(), settled);
    control.reserve_native(request("r2"), 1).unwrap();
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&settled));
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn cancellation_intent_and_terminal_failure_do_not_invent_zero_usage() {
    let path = path("cancel");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    let cancelling = control.cancel_native("r1").unwrap();
    assert_eq!(control.cancel_native("r1").unwrap(), cancelling);
    assert_eq!(
        control.reserve_native(request("r2"), 1),
        Err(Error::CapacityExceeded)
    );
    let terminal = output(NativeRunStatus::Interrupted, None);
    let interrupted = control.settle_native("r1", terminal.clone()).unwrap();
    assert_eq!(interrupted.state, NativeReservationState::Released);
    assert!(interrupted.cancel_requested);
    assert_eq!(interrupted.observation, Some(terminal));
    start(&mut control, "r2");
    let failed = control
        .settle_native("r2", output(NativeRunStatus::Failed, None))
        .unwrap();
    assert_eq!(failed.observation.unwrap().observed_output_tokens, None);
    assert_eq!(failed.state, NativeReservationState::Released);
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn missing_terminal_usage_can_be_completed_without_changing_the_outcome() {
    let path = path("late-usage");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    control
        .settle_native("r1", output(NativeRunStatus::Completed, None))
        .unwrap();
    let settled = control
        .settle_native("r1", output(NativeRunStatus::Completed, Some(27)))
        .unwrap();
    assert_eq!(
        control.settle_native("r1", output(NativeRunStatus::Completed, Some(26))),
        Err(Error::Conflict)
    );
    assert_eq!(
        control.settle_native("r1", output(NativeRunStatus::Failed, Some(27))),
        Err(Error::Conflict)
    );
    let mut mismatched = output(NativeRunStatus::Completed, Some(27));
    mismatched.turn_id = "another-turn".to_string();
    assert_eq!(
        control.settle_native("r1", mismatched),
        Err(Error::AssignmentMismatch)
    );
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&settled));
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn pre_dispatch_stop_releases_without_claiming_provider_terminal() {
    let path = path("before");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    let stopped = control
        .stop_native_before_dispatch("r1", "cancelled".to_string())
        .unwrap();
    assert_eq!(stopped.state, NativeReservationState::Released);
    assert_eq!(stopped.observation, None);
    assert_eq!(
        control.dispatch_native("r1", dispatch()),
        Err(Error::InvalidTransition)
    );
    start(&mut control, "r2");
    assert_eq!(
        control.stop_native_before_dispatch("r2", "cancelled".to_string()),
        Err(Error::InvalidTransition)
    );
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&stopped));
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn journal_byte_budget_rejects_before_append_and_replay_checks_actual_bytes() {
    use std::io::Write;
    let path = path("byte-budget");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    let mut observed = output(NativeRunStatus::Completed, Some(0));
    observed.output = "x".repeat(1024 * 1024);
    for tokens in 0..128 {
        observed.observed_output_tokens = Some(tokens);
        let before = control.native_record("r1").unwrap().clone();
        let bytes_before = std::fs::metadata(&path).unwrap().len();
        match control.settle_native("r1", observed.clone()) {
            Ok(_) => continue,
            Err(error) => {
                assert_eq!(error, Error::CapacityExceeded);
                assert_eq!(control.native_record("r1"), Some(&before));
                assert_eq!(std::fs::metadata(&path).unwrap().len(), bytes_before);
                assert!(bytes_before > super::super::MAX_JOURNAL_BYTES / 2);
                break;
            }
        }
    }
    let expected = control.native_record("r1").unwrap().clone();
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&expected));
    drop(control);
    // A syntactically valid extra observation still exceeds the total budget.
    let event = Event::Observe {
        request_id: "r1".to_string(),
        output: observed,
    };
    let json = serde_json::to_string(&event).unwrap();
    let mut file = std::fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap();
    writeln!(file, "{JOURNAL_PREFIX}{json}").unwrap();
    drop(file);
    let oversized_bytes = std::fs::metadata(&path).unwrap().len();
    assert!(matches!(
        DurableInferenceControl::open(&path, 8),
        Err(Error::CapacityExceeded)
    ));
    assert_eq!(std::fs::metadata(&path).unwrap().len(), oversized_bytes);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn oversized_and_incomplete_lines_are_rejected_without_truncation() {
    let path = path("line-budget");
    let mut oversized = vec![b'x'; super::super::MAX_JOURNAL_LINE_BYTES + 1];
    oversized.push(b'\n');
    std::fs::write(&path, &oversized).unwrap();
    assert!(matches!(
        DurableInferenceControl::open(&path, 8),
        Err(Error::CapacityExceeded)
    ));
    assert_eq!(
        std::fs::metadata(&path).unwrap().len(),
        oversized.len() as u64
    );
    std::fs::remove_file(&path).unwrap();
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    drop(control);
    let file = std::fs::OpenOptions::new().write(true).open(&path).unwrap();
    let truncated_length = file.metadata().unwrap().len() - 1;
    file.set_len(truncated_length).unwrap();
    drop(file);
    assert!(matches!(
        DurableInferenceControl::open(&path, 8),
        Err(Error::CorruptJournal("incomplete line"))
    ));
    assert_eq!(std::fs::metadata(&path).unwrap().len(), truncated_length);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn late_completed_releases_slot_without_erasing_authority_loss() {
    let path = path("authority-loss");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    control.cancel_native("r1").unwrap();
    let mut interrupted_observation = output(NativeRunStatus::Indeterminate, Some(42));
    interrupted_observation.owner_authority = NativeOwnerAuthority::Lost {
        reason: "owner generation fenced".to_string(),
    };
    control
        .settle_native("r1", interrupted_observation.clone())
        .unwrap();
    let mut terminal = interrupted_observation;
    terminal.status = NativeRunStatus::Completed;
    terminal.terminal_observed = true;
    let settled = control.settle_native("r1", terminal.clone()).unwrap();
    assert_eq!(settled.state, NativeReservationState::Released);
    assert!(settled.cancel_requested);
    assert_eq!(settled.observation, Some(terminal.clone()));
    assert!(!terminal.succeeded());
    control.reserve_native(request("r2"), 1).unwrap();
    let mut dishonest_upgrade = terminal;
    dishonest_upgrade.owner_authority = NativeOwnerAuthority::ObservedReady;
    assert_eq!(
        control.settle_native("r1", dishonest_upgrade),
        Err(Error::Conflict)
    );
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&settled));
    assert!(
        !control
            .native_record("r1")
            .unwrap()
            .observation
            .as_ref()
            .unwrap()
            .succeeded()
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn legacy_journal_completion_without_authority_cannot_be_replayed_as_success() {
    let path = path("legacy-authority");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    let mut old_output = output(NativeRunStatus::Completed, Some(19));
    old_output.owner_authority = NativeOwnerAuthority::ObservedReady;
    let event = Event::Observe {
        request_id: "r1".to_string(),
        output: old_output,
    };
    let mut json = serde_json::to_value(event).unwrap();
    json["Observe"]["output"]
        .as_object_mut()
        .unwrap()
        .remove("owner_authority");
    // Write an actual pre-upgrade observation record with the field absent.
    control
        .append(&format!(
            "{JOURNAL_PREFIX}{}\n",
            serde_json::to_string(&json).unwrap()
        ))
        .unwrap();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let mut replayed = control
        .native_record("r1")
        .unwrap()
        .observation
        .clone()
        .unwrap();
    assert_eq!(replayed.owner_authority, NativeOwnerAuthority::Unverified);
    assert_eq!(replayed.status, NativeRunStatus::Completed);
    assert_eq!(replayed.observed_output_tokens, Some(19));
    assert!(!replayed.succeeded());
    // Later token evidence must not retroactively authorize the old attempt.
    replayed.observed_output_tokens = Some(20);
    control.settle_native("r1", replayed.clone()).unwrap();
    replayed.owner_authority = NativeOwnerAuthority::ObservedReady;
    assert_eq!(control.settle_native("r1", replayed), Err(Error::Conflict));
    drop(control);
    std::fs::remove_file(path).unwrap();
}
