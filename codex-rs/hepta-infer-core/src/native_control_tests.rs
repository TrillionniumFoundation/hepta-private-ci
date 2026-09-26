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
        owner_context_digest: Some("c".repeat(64)),
        codex_payload_digest: Some("e".repeat(64)),
        codex_request_digest: Some("c".repeat(64)),
        app_server_version: Some("1.2.3".to_string()),
        protocol_id: Some("codex.app-server.v2".to_string()),
        codex_source_admission_digest: Some("f".repeat(64)),
        codex_home_digest: Some("1".repeat(64)),
        codex_connection_id: Some(7),
        codex_session_id: Some("session-1".to_string()),
        codex_deadline_ms: Some(10_000),
        codex_authority_epoch: Some(9),
        codex_revocation_revision: Some(3),
        codex_revocation_head_sha256: Some("3".repeat(64)),
        codex_authority_witness_sha256: Some("2".repeat(64)),
    }
}

fn output(status: NativeRunStatus, tokens: Option<u64>) -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        model: "actual-model".to_string(),
        model_provider: "provider".to_string(),
        terminal_observed: status != NativeRunStatus::Indeterminate,
        boundary_status: match status {
            NativeRunStatus::Completed => NativeBoundaryStatus::Succeeded,
            NativeRunStatus::Failed => NativeBoundaryStatus::Failed,
            NativeRunStatus::Interrupted => NativeBoundaryStatus::Interrupted,
            NativeRunStatus::Indeterminate => NativeBoundaryStatus::Indeterminate,
        },
        status,
        output: "observed text".to_string(),
        observed_output_tokens: tokens,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::Unverified,
        codex_terminal_correlation_digest: (status != NativeRunStatus::Indeterminate)
            .then(|| "d".repeat(64)),
    }
}

fn start_with_limit(control: &mut DurableInferenceControl, id: &str, maximum_in_flight: usize) {
    control
        .reserve_native(request(id), maximum_in_flight)
        .unwrap();
    control.dispatch_native(id, dispatch()).unwrap();
    control.native_started(id, "turn-1".to_string()).unwrap();
}

fn start(control: &mut DurableInferenceControl, id: &str) {
    start_with_limit(control, id, 1);
}

#[test]
fn completed_owner_ready_without_codex_witness_is_not_success() {
    let mut observed = output(NativeRunStatus::Completed, Some(1));
    observed.owner_authority = NativeOwnerAuthority::ObservedReady;
    observed.codex_terminal_correlation_digest = None;
    assert!(!observed.succeeded());

    observed.codex_terminal_correlation_digest = Some("d".repeat(64));
    assert!(observed.succeeded());
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
fn post_dispatch_pre_turn_stop_is_durable_and_releases_without_provider_terminal() {
    let path = path("finalize-stop");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort("r1", dispatch())
        .unwrap();
    let stopped = control
        .stop_native_before_turn_start(token, "cognitive final-use revalidation failed".to_string())
        .unwrap();
    assert_eq!(stopped.state, NativeReservationState::Released);
    assert_eq!(stopped.turn_id, None);
    assert_eq!(stopped.observation, None);
    assert!(stopped.dispatch.is_some());

    control.reserve_native(request("r2"), 1).unwrap();
    let (_, too_late_token) = control
        .dispatch_native_with_pre_effect_abort("r2", dispatch())
        .unwrap();
    control.native_started("r2", "turn-1".to_string()).unwrap();
    assert_eq!(
        control.stop_native_before_turn_start(too_late_token, "too late".to_string()),
        Err(Error::InvalidTransition)
    );

    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&stopped));
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn one_shot_pre_effect_abort_releases_only_the_live_write_ahead() {
    let path = path("pre-effect-abort");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort("r1", dispatch())
        .unwrap();
    let stopped = control
        .abort_native_before_effect(token, "final-use denied before send".to_string())
        .unwrap();
    assert_eq!(stopped.state, NativeReservationState::Released);
    assert_eq!(
        stopped.pre_dispatch_stop.as_deref(),
        Some("final-use denied before send")
    );
    assert_eq!(stopped.observation, None);
    control.reserve_native(request("r2"), 1).unwrap();

    drop(control);
    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(reopened.native_record("r1"), Some(&stopped));
    assert_eq!(
        reopened.stop_native_before_dispatch("r1", "already stopped".to_string()),
        Err(Error::InvalidTransition)
    );
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn lost_pre_effect_abort_token_becomes_reconcile_only_on_reopen() {
    let path = path("pre-effect-recovery");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort("r1", dispatch())
        .unwrap();
    drop(token);
    drop(control);

    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(
        reopened.native_record("r1").unwrap().state,
        NativeReservationState::Dispatching
    );
    assert_eq!(
        reopened.stop_native_before_dispatch("r1", "recovered".to_string()),
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
fn explicit_dispatch_rejection_releases_without_claiming_provider_terminal() {
    let path = path("dispatch-rejected");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    control.dispatch_native("r1", dispatch()).unwrap();
    let rejection = NativeDispatchRejection {
        status: NativeDispatchRejectionStatus::Overloaded,
        reason: "Server overloaded; retry later.".to_string(),
        response_digest: "e".repeat(64),
        retry_safe_before_admission: true,
    };
    let rejected = control
        .reject_native_before_start("r1", rejection.clone())
        .unwrap();
    assert_eq!(rejected.state, NativeReservationState::Released);
    assert_eq!(rejected.dispatch_rejection, Some(rejection));
    assert_eq!(rejected.observation, None);
    assert_eq!(rejected.turn_id, None);
    control.reserve_native(request("r2"), 1).unwrap();
    drop(control);

    let control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(control.native_record("r1"), Some(&rejected));
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn generic_dispatch_rejection_holds_slot_when_pre_admission_is_not_proven() {
    let path = path("dispatch-rejected-unknown");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    control.dispatch_native("r1", dispatch()).unwrap();
    let rejection = NativeDispatchRejection {
        status: NativeDispatchRejectionStatus::Rejected,
        reason: "application error after dispatch".to_string(),
        response_digest: "f".repeat(64),
        retry_safe_before_admission: false,
    };
    let rejected = control
        .reject_native_before_start("r1", rejection.clone())
        .unwrap();
    assert_eq!(rejected.state, NativeReservationState::Indeterminate);
    assert_eq!(rejected.dispatch_rejection, Some(rejection));
    assert_eq!(rejected.observation, None);
    assert_eq!(
        control.reserve_native(request("r2"), 1),
        Err(Error::CapacityExceeded)
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn codex_bound_terminal_requires_adapter_correlation_witness() {
    let path = path("terminal-witness");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start(&mut control, "r1");
    let mut dishonest = output(NativeRunStatus::Completed, Some(1));
    dishonest.codex_terminal_correlation_digest = None;
    assert_eq!(
        control.settle_native("r1", dishonest),
        Err(Error::TerminalObservationMissing)
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn journal_compaction_reclaims_refinements_and_preserves_exact_replay() {
    let path = path("compaction-replay");
    let mut control = DurableInferenceControl::open(&path, 16).unwrap();
    start(&mut control, "r1");
    let mut observed = output(NativeRunStatus::Completed, Some(0));
    observed.output = "x".repeat(256 * 1024);
    for tokens in 0..12 {
        observed.observed_output_tokens = Some(tokens);
        control.settle_native("r1", observed.clone()).unwrap();
    }
    let expected = control.native_record("r1").unwrap().clone();
    let before = control.journal_capacity_status();
    let receipt = control.compact_journal().unwrap();
    let after = control.journal_capacity_status();
    assert_eq!(receipt.before_bytes, before.journal_bytes);
    assert_eq!(receipt.after_bytes, after.journal_bytes);
    assert!(receipt.after_bytes < receipt.before_bytes);
    assert_eq!(receipt.native_records, 1);
    assert_eq!(receipt.reserved_headroom_bytes, 0);
    assert_eq!(after.reserved_headroom_bytes, 0);
    // The replacement inode is locked before rename and remains the owner's
    // locked writer after compaction; path replacement never opens a double-writer gap.
    assert!(matches!(
        DurableInferenceControl::open(&path, 16),
        Err(Error::WriterUnavailable)
    ));
    drop(control);

    let mut reopened = DurableInferenceControl::open(&path, 16).unwrap();
    assert_eq!(reopened.native_record("r1"), Some(&expected));
    let bytes_before_duplicate = reopened.journal_capacity_status().journal_bytes;
    assert_eq!(reopened.settle_native("r1", observed).unwrap(), expected);
    assert_eq!(
        reopened.journal_capacity_status().journal_bytes,
        bytes_before_duplicate
    );
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn checkpoint_roundtrips_every_reachable_native_state_shape() {
    fn compact_reopen_exact(path: PathBuf, mut control: DurableInferenceControl) {
        let expected = control.native.records.clone();
        let expected_active = control.native.active_reservations;
        let expected_headroom = control.journal_capacity_status().reserved_headroom_bytes;
        control.compact_journal().unwrap();
        assert_eq!(
            control.journal_capacity_status().reserved_headroom_bytes,
            expected_headroom
        );
        drop(control);
        let reopened = DurableInferenceControl::open(&path, 64).unwrap();
        assert_eq!(reopened.native.records, expected);
        assert_eq!(reopened.native.active_reservations, expected_active);
        assert_eq!(
            reopened.journal_capacity_status().reserved_headroom_bytes,
            expected_headroom
        );
        drop(reopened);
        std::fs::remove_file(path).unwrap();
    }

    // Seven active identities are the maximum worst-case-output set that fits
    // this journal budget. Cover every active state shape in one checkpoint.
    let active_path = path("checkpoint-active-shapes");
    let mut active = DurableInferenceControl::open(&active_path, 64).unwrap();
    active.reserve_native(request("reserved"), 16).unwrap();

    active.reserve_native(request("dispatching"), 16).unwrap();
    active.dispatch_native("dispatching", dispatch()).unwrap();

    start_with_limit(&mut active, "running", 16);

    active
        .reserve_native(request("cancel-dispatching"), 16)
        .unwrap();
    active
        .dispatch_native("cancel-dispatching", dispatch())
        .unwrap();
    active.cancel_native("cancel-dispatching").unwrap();

    start_with_limit(&mut active, "cancel-running", 16);
    active.cancel_native("cancel-running").unwrap();

    start_with_limit(&mut active, "indeterminate-observation", 16);
    active
        .settle_native(
            "indeterminate-observation",
            output(NativeRunStatus::Indeterminate, None),
        )
        .unwrap();

    active
        .reserve_native(request("unsafe-rejection"), 16)
        .unwrap();
    active
        .dispatch_native("unsafe-rejection", dispatch())
        .unwrap();
    active
        .reject_native_before_start(
            "unsafe-rejection",
            NativeDispatchRejection {
                status: NativeDispatchRejectionStatus::Rejected,
                reason: "provider acceptance is unknown".to_string(),
                response_digest: "7".repeat(64),
                retry_safe_before_admission: false,
            },
        )
        .unwrap();
    assert_eq!(active.native.active_reservations, 7);
    compact_reopen_exact(active_path, active);

    // Released variants do not consume future-terminal headroom. Include an
    // observed-then-cancelled active record plus every release construction.
    let released_path = path("checkpoint-released-shapes");
    let mut released = DurableInferenceControl::open(&released_path, 64).unwrap();

    start_with_limit(&mut released, "observed-then-cancelled", 16);
    released
        .settle_native(
            "observed-then-cancelled",
            output(NativeRunStatus::Indeterminate, None),
        )
        .unwrap();
    released.cancel_native("observed-then-cancelled").unwrap();

    released
        .reserve_native(request("pre-dispatch-stop"), 16)
        .unwrap();
    released
        .stop_native_before_dispatch("pre-dispatch-stop", "cancelled locally".to_string())
        .unwrap();

    released
        .reserve_native(request("pre-effect-abort"), 16)
        .unwrap();
    let (_, token) = released
        .dispatch_native_with_pre_effect_abort("pre-effect-abort", dispatch())
        .unwrap();
    released
        .abort_native_before_effect(token, "final-use denied".to_string())
        .unwrap();

    released
        .reserve_native(request("safe-rejection"), 16)
        .unwrap();
    released
        .dispatch_native("safe-rejection", dispatch())
        .unwrap();
    released
        .reject_native_before_start(
            "safe-rejection",
            NativeDispatchRejection {
                status: NativeDispatchRejectionStatus::Overloaded,
                reason: "rejected before admission".to_string(),
                response_digest: "8".repeat(64),
                retry_safe_before_admission: true,
            },
        )
        .unwrap();

    start_with_limit(&mut released, "completed", 16);
    released
        .settle_native("completed", output(NativeRunStatus::Completed, Some(2)))
        .unwrap();

    start_with_limit(&mut released, "cancelled-terminal", 16);
    released.cancel_native("cancelled-terminal").unwrap();
    released
        .settle_native(
            "cancelled-terminal",
            output(NativeRunStatus::Interrupted, None),
        )
        .unwrap();

    released
        .reserve_native(request("unsafe-reconciled"), 16)
        .unwrap();
    released
        .dispatch_native("unsafe-reconciled", dispatch())
        .unwrap();
    released
        .reject_native_before_start(
            "unsafe-reconciled",
            NativeDispatchRejection {
                status: NativeDispatchRejectionStatus::Rejected,
                reason: "outcome initially unknown".to_string(),
                response_digest: "9".repeat(64),
                retry_safe_before_admission: false,
            },
        )
        .unwrap();
    released
        .settle_native(
            "unsafe-reconciled",
            output(NativeRunStatus::Completed, Some(3)),
        )
        .unwrap();

    start_with_limit(&mut released, "late-usage", 16);
    released
        .settle_native("late-usage", output(NativeRunStatus::Completed, None))
        .unwrap();
    released
        .settle_native("late-usage", output(NativeRunStatus::Completed, Some(4)))
        .unwrap();

    assert_eq!(released.native.active_reservations, 1);
    compact_reopen_exact(released_path, released);
}

#[test]
fn reserved_terminal_headroom_rejects_new_work_but_closes_accepted_run() {
    let path = path("terminal-headroom");
    let mut control = DurableInferenceControl::open(&path, 32).unwrap();
    let large_output = "\0".repeat(850_000);

    // Ten released records leave a compacted current-state image between one
    // and two worst-case terminal frames from the hard journal ceiling.
    for index in 0..10 {
        let id = format!("history-{index}");
        control.reserve_native(request(&id), 2).unwrap();
        control.dispatch_native(&id, dispatch()).unwrap();
        control.native_started(&id, "turn-1".to_string()).unwrap();
        let mut terminal = output(NativeRunStatus::Completed, Some(index));
        terminal.output = large_output.clone();
        control.settle_native(&id, terminal).unwrap();
    }
    let compacted = control.compact_journal().unwrap();
    assert_eq!(compacted.reserved_headroom_bytes, 0);
    let before_live = control.journal_capacity_status();
    assert!(before_live.admissible_bytes > TERMINAL_HEADROOM_BYTES);
    assert!(before_live.admissible_bytes < 2 * TERMINAL_HEADROOM_BYTES);

    control.reserve_native(request("live"), 2).unwrap();
    let live_reserved = control.journal_capacity_status();
    assert_eq!(
        live_reserved.reserved_headroom_bytes,
        TERMINAL_HEADROOM_BYTES
    );
    assert_eq!(
        control.reserve_native(request("blocked"), 2),
        Err(Error::CapacityExceeded)
    );
    assert!(control.native_record("blocked").is_none());

    control.dispatch_native("live", dispatch()).unwrap();
    control
        .native_started("live", "turn-1".to_string())
        .unwrap();
    let mut terminal = output(NativeRunStatus::Completed, Some(7));
    terminal.output = "\0".repeat(1024 * 1024);
    let settled = control.settle_native("live", terminal.clone()).unwrap();
    assert_eq!(settled.state, NativeReservationState::Released);
    assert_eq!(control.journal_capacity_status().reserved_headroom_bytes, 0);
    assert_eq!(control.settle_native("live", terminal).unwrap(), settled);
    drop(control);

    let reopened = DurableInferenceControl::open(&path, 32).unwrap();
    assert_eq!(reopened.native_record("live"), Some(&settled));
    assert!(reopened.native_record("blocked").is_none());
    assert_eq!(
        reopened.journal_capacity_status().reserved_headroom_bytes,
        0
    );
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn unsafe_dispatch_rejection_reconciles_to_terminal_after_reopen() {
    let path = path("unsafe-rejection-reconcile");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    control.dispatch_native("r1", dispatch()).unwrap();
    let indeterminate = control
        .reject_native_before_start(
            "r1",
            NativeDispatchRejection {
                status: NativeDispatchRejectionStatus::Rejected,
                reason: "provider may have accepted before returning the error".to_string(),
                response_digest: "9".repeat(64),
                retry_safe_before_admission: false,
            },
        )
        .unwrap();
    assert_eq!(indeterminate.state, NativeReservationState::Indeterminate);
    assert_eq!(
        control.reserve_native(request("r2"), 1),
        Err(Error::CapacityExceeded)
    );
    drop(control);

    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    let terminal = output(NativeRunStatus::Completed, Some(13));
    let settled = reopened.settle_native("r1", terminal.clone()).unwrap();
    assert_eq!(settled.state, NativeReservationState::Released);
    assert_eq!(reopened.settle_native("r1", terminal).unwrap(), settled);
    reopened.reserve_native(request("r2"), 1).unwrap();
    drop(reopened);

    let reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(reopened.native_record("r1"), Some(&settled));
    assert_eq!(
        reopened.native_record("r2").unwrap().state,
        NativeReservationState::Reserved
    );
    drop(reopened);
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
    terminal.boundary_status = NativeBoundaryStatus::Quarantined;
    terminal.terminal_observed = true;
    terminal.codex_terminal_correlation_digest = Some("d".repeat(64));
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

#[test]
fn historical_codex_dispatch_without_frontier_reopens_but_cannot_upgrade_to_success() {
    let path = path("historical-codex-frontier");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    let mut historical = dispatch();
    historical.codex_authority_epoch = None;
    historical.codex_revocation_revision = None;
    historical.codex_revocation_head_sha256 = None;
    control.dispatch_native("r1", historical).unwrap();
    control.native_started("r1", "turn-1".to_string()).unwrap();
    drop(control);

    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let reopened = control.native_record("r1").unwrap();
    assert_eq!(
        reopened
            .dispatch
            .as_ref()
            .unwrap()
            .codex_revocation_revision,
        None
    );

    let mut observed = output(NativeRunStatus::Completed, Some(7));
    observed.owner_authority = NativeOwnerAuthority::ObservedReady;
    let settled = control.settle_native("r1", observed).unwrap();
    let terminal = settled.observation.unwrap();
    assert_eq!(terminal.status, NativeRunStatus::Completed);
    assert!(terminal.terminal_observed);
    assert_eq!(terminal.boundary_status, NativeBoundaryStatus::Quarantined);
    assert!(!terminal.succeeded());
    assert!(
        terminal
            .stop_reason
            .as_deref()
            .is_some_and(|reason| reason.contains("lacks claim-time authority frontier"))
    );

    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[path = "native_incremental_tests.rs"]
mod incremental;

#[path = "native_growth_tests.rs"]
mod growth;

#[path = "native_maintenance_tests.rs"]
mod maintenance;

#[path = "native_usage_tests.rs"]
mod usage;

#[path = "native_prepared_input_tests.rs"]
mod prepared_input;
