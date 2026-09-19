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
        operation_id: Some(format!("operation-{id}")),
        quota_reservation_digest: Some("c".repeat(64)),
        resource_snapshot_digest: Some("d".repeat(64)),
        worker_assignment_digest: Some("f".repeat(64)),
    }
}

fn dispatch() -> NativeDispatch {
    NativeDispatch {
        thread_id: "thread-1".to_string(),
        model_provider: "provider".to_string(),
        context_digest: "b".repeat(64),
        authority_binding_digest: Some("e".repeat(64)),
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
        final_use_authority: NativeFinalUseAuthority::Unverified,
        output_sha256: None,
        output_retained: true,
    }
}

fn start(control: &mut DurableInferenceControl, id: &str) {
    control.reserve_native(request(id), 1).unwrap();
    control.dispatch_native(id, dispatch()).unwrap();
    control.native_started(id, "turn-1".to_string()).unwrap();
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
    let legacy = json["Observe"]["output"].as_object_mut().unwrap();
    legacy.remove("owner_authority");
    legacy.remove("final_use_authority");
    legacy.remove("output_sha256");
    legacy.remove("output_retained");
    // Write an actual pre-upgrade observation record with the fields absent.
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

#[test]
fn receipt_only_settlement_persists_digest_without_model_text() {
    let path = path("receipt-only");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    let mut observed = output(NativeRunStatus::Completed, Some(9));
    observed.owner_authority = NativeOwnerAuthority::ObservedReady;
    observed.final_use_authority = NativeFinalUseAuthority::Verified {
        authority_epoch: 7,
        grant_id: "grant-1".to_string(),
    };
    let live_text = observed.output.clone();
    let settled = control.settle_native_receipt_only("r1", observed).unwrap();
    let persisted = settled.observation.as_ref().unwrap();
    assert_eq!(persisted.output, "");
    assert!(!persisted.output_retained);
    let expected_digest = Digest32::of_bytes(live_text.as_bytes()).to_string();
    assert_eq!(
        persisted.output_sha256.as_deref(),
        Some(expected_digest.as_str())
    );
    assert!(persisted.succeeded());
    drop(control);

    let bytes = std::fs::read(&path).unwrap();
    assert!(
        !bytes
            .windows(live_text.len())
            .any(|window| window == live_text.as_bytes())
    );
    let reopened = DurableInferenceControl::open(&path, 8).unwrap();
    let replayed = reopened
        .native_record("r1")
        .unwrap()
        .observation
        .as_ref()
        .unwrap();
    assert_eq!(replayed.output, "");
    assert!(!replayed.output_retained);
    assert!(replayed.succeeded());
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn terminal_unverified_final_use_cannot_be_retroactively_authorized() {
    let path = path("final-use-upgrade");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    let terminal = output(NativeRunStatus::Completed, Some(3));
    control.settle_native("r1", terminal.clone()).unwrap();
    let mut upgraded = terminal;
    upgraded.final_use_authority = NativeFinalUseAuthority::Verified {
        authority_epoch: 1,
        grant_id: "grant-1".to_string(),
    };
    assert_eq!(control.settle_native("r1", upgraded), Err(Error::Conflict));
    drop(control);
    std::fs::remove_file(path).unwrap();
}
