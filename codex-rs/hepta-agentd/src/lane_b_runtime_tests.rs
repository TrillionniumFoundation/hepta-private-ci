use super::*;

fn digest(byte: char) -> String {
    byte.to_string().repeat(64)
}

fn composition() -> RuntimeComposition {
    RuntimeComposition {
        agent_id: "agent.1".to_string(),
        supervisor_generation: 2,
        agentd_generation: 3,
        configuration_digest: digest('1'),
        ports_digest: digest('2'),
        cancellation_ack_timeout_ms: 5_000,
    }
}

fn snapshot() -> RunSnapshot {
    RunSnapshot {
        run_id: "run.1".to_string(),
        request_digest: digest('3'),
        objective_digest: digest('4'),
        body_digest: digest('5'),
        artifact_set_digest: digest('6'),
        authority_epoch: 7,
        deadline_ms: 10_000,
    }
}

fn attachment() -> ContextAttachment {
    ContextAttachment {
        run_id: "run.1".to_string(),
        request_digest: digest('3'),
        objective_digest: digest('4'),
        body_digest: digest('5'),
        artifact_set_digest: digest('6'),
        authority_epoch: 7,
        deadline_ms: 10_000,
        context_digest: digest('7'),
        compilation_receipt_digest: digest('8'),
    }
}

#[test]
fn freezes_the_complete_run_tuple_before_context_attachment() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    let admitted = coordinator.start_run(100, snapshot()).expect("admit run");
    assert_eq!(admitted.phase, RunPhase::Admitted);
    assert_eq!(admitted.cancellation_reason, None);

    let mut mixed = attachment();
    mixed.authority_epoch = 8;
    assert_eq!(
        coordinator.attach_context(100, 1, mixed),
        Err(AgentRunError::MixedSnapshot)
    );

    let mut mixed_deadline = attachment();
    mixed_deadline.deadline_ms += 1;
    assert_eq!(
        coordinator.attach_context(100, 1, mixed_deadline),
        Err(AgentRunError::MixedSnapshot)
    );

    let attached = coordinator
        .attach_context(100, 1, attachment())
        .expect("attach context");
    assert_eq!(attached.phase, RunPhase::ContextAttached);
    assert_eq!(attached.revision, 2);
}

#[test]
fn cancellation_preserves_dispatch_boundary_and_reason_idempotency() {
    let mut before = AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    before.start_run(100, snapshot()).expect("admit run");
    let early = before
        .cancel_run(100, "run.1", 1, "operator_cancel")
        .expect("cancel");
    assert_eq!(early.0, CancellationDisposition::CancelledBeforeDispatch);
    assert_eq!(early.1.phase, RunPhase::Cancelled);
    assert_eq!(
        early.1.cancellation_reason.as_deref(),
        Some("operator_cancel")
    );
    let repeated = before
        .cancel_run(100, "run.1", 1, "operator_cancel")
        .expect("idempotent retry");
    assert_eq!(repeated.0, CancellationDisposition::AlreadyTerminal);
    assert!(repeated.1.idempotent);

    let mut after = AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    after.start_run(100, snapshot()).expect("admit run");
    after
        .attach_context(100, 1, attachment())
        .expect("attach context");
    after.mark_dispatched(100, "run.1", 2).expect("dispatch");
    let late = after
        .cancel_run(100, "run.1", 3, "operator_cancel")
        .expect("cancel");
    assert_eq!(late.0, CancellationDisposition::CancellingAfterDispatch);
    assert_eq!(late.1.phase, RunPhase::Cancelling);
    assert_eq!(late.1.cancellation_ack_deadline_ms, Some(5_100));
    let terminal = after
        .observe_terminal("run.1", 4, RunPhase::Indeterminate, false)
        .expect("observe unknown terminality");
    assert_eq!(terminal.phase, RunPhase::Indeterminate);
    assert!(!terminal.terminal_observed);
}

#[test]
fn operation_identity_is_idempotent_only_for_equal_semantics() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    let original = snapshot();
    coordinator
        .start_run(100, original.clone())
        .expect("admit run");
    let repeated = coordinator
        .start_run(20_000, original)
        .expect("historical repeat stays idempotent after deadline");
    assert!(repeated.idempotent);

    let mut changed = snapshot();
    changed.objective_digest = digest('9');
    assert_eq!(
        coordinator.start_run(100, changed),
        Err(AgentRunError::Conflict)
    );
}

#[test]
fn deadline_is_enforced_after_admission_and_by_background_sweep() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");
    assert_eq!(
        coordinator.attach_context(10_000, 1, attachment()),
        Err(AgentRunError::DeadlineExceeded)
    );
    let changed = coordinator.enforce_deadlines(10_000).expect("sweep");
    assert_eq!(changed.len(), 1);
    assert_eq!(changed[0].phase, RunPhase::Cancelled);
    assert_eq!(
        changed[0].cancellation_reason.as_deref(),
        Some("deadline_exceeded")
    );
}

#[test]
fn cancellation_ack_deadline_converts_lost_ack_to_indeterminate() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");
    coordinator
        .attach_context(100, 1, attachment())
        .expect("attach");
    coordinator
        .mark_dispatched(100, "run.1", 2)
        .expect("dispatch");
    let (_, cancelling) = coordinator
        .cancel_run(200, "run.1", 3, "operator_cancel")
        .expect("cancel");
    assert_eq!(cancelling.phase, RunPhase::Cancelling);
    assert_eq!(cancelling.cancellation_ack_deadline_ms, Some(5_200));

    assert!(
        coordinator
            .enforce_deadlines(5_199)
            .expect("before ack deadline")
            .is_empty()
    );
    let changed = coordinator
        .enforce_deadlines(5_200)
        .expect("ack deadline elapsed");
    assert_eq!(changed.len(), 1);
    assert_eq!(changed[0].phase, RunPhase::Indeterminate);
    assert_eq!(changed[0].cancellation_ack_deadline_ms, None);
    assert!(!changed[0].terminal_observed);
}

#[test]
fn dispatched_deadline_and_drain_require_external_terminality() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");
    coordinator
        .attach_context(100, 1, attachment())
        .expect("attach");
    coordinator
        .mark_dispatched(100, "run.1", 2)
        .expect("dispatch");

    let changed = coordinator.enforce_deadlines(10_000).expect("deadline");
    assert_eq!(changed[0].phase, RunPhase::Cancelling);
    assert_eq!(coordinator.pending_external_run_count(), 1);
    assert!(
        coordinator
            .begin_drain("agentd_shutdown")
            .expect("drain")
            .is_empty()
    );

    let unknown = coordinator
        .mark_unobserved_external_indeterminate()
        .expect("persist uncertainty");
    assert_eq!(unknown.len(), 1);
    assert_eq!(unknown[0].phase, RunPhase::Indeterminate);
    assert_eq!(coordinator.pending_external_run_count(), 1);
}

#[test]
fn recovery_never_redispatches_an_uncertain_external_run() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");
    coordinator
        .attach_context(100, 1, attachment())
        .expect("attach");
    coordinator
        .mark_dispatched(100, "run.1", 2)
        .expect("dispatch");

    let encoded = serde_json::to_vec(&coordinator.recovery_state()).expect("encode");
    let recovery: RunRecoveryState = serde_json::from_slice(&encoded).expect("decode");
    let restored =
        AgentRunCoordinator::restore_runtime(composition(), recovery, 200).expect("restore");
    let receipt = restored.run("run.1").expect("retained run");
    assert_eq!(receipt.phase, RunPhase::Indeterminate);
    assert_eq!(receipt.revision, 4);
    assert_eq!(restored.pending_external_run_count(), 1);
}

#[test]
fn v1_cancelling_recovery_migrates_to_indeterminate() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");
    coordinator
        .attach_context(100, 1, attachment())
        .expect("attach");
    coordinator.mark_dispatched(100, "run.1", 2).expect("dispatch");
    coordinator
        .cancel_run(200, "run.1", 3, "legacy_cancel")
        .expect("cancel");

    let mut legacy = coordinator.recovery_state();
    legacy.schema_version = 1;
    legacy.composition.cancellation_ack_timeout_ms = 0;
    legacy.records[0].cancellation_ack_deadline_ms = None;

    let restored =
        AgentRunCoordinator::restore_runtime(composition(), legacy, 300).expect("migrate v1");
    let receipt = restored.run("run.1").expect("retained");
    assert_eq!(receipt.phase, RunPhase::Indeterminate);
    assert_eq!(receipt.cancellation_ack_deadline_ms, None);
    assert!(!receipt.terminal_observed);
}

#[test]
fn recovery_cancels_expired_pre_dispatch_work() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");

    let restored =
        AgentRunCoordinator::restore_runtime(composition(), coordinator.recovery_state(), 10_000)
            .expect("restore");
    let receipt = restored.run("run.1").expect("retained");
    assert_eq!(receipt.phase, RunPhase::Cancelled);
    assert_eq!(
        receipt.cancellation_reason.as_deref(),
        Some("deadline_exceeded_during_restart")
    );
}

#[test]
fn newer_generation_cancels_pre_dispatch_recovery_instead_of_reusing_authority() {
    let old = composition();
    let mut coordinator = AgentRunCoordinator::compose_runtime(old).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");

    let mut next = composition();
    next.supervisor_generation += 1;
    next.agentd_generation += 1;
    let restored = AgentRunCoordinator::restore_runtime(next, coordinator.recovery_state(), 200)
        .expect("restore newer generation");
    let receipt = restored.run("run.1").expect("retained");
    assert_eq!(receipt.phase, RunPhase::Cancelled);
    assert_eq!(
        receipt.cancellation_reason.as_deref(),
        Some("generation_changed_during_restart")
    );
}

#[test]
fn closed_retention_is_compacted_before_capacity_rejects_new_work() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    for index in 0..MAX_RETAINED_RUNS {
        let mut closed = snapshot();
        closed.run_id = format!("run.closed.{index:04}");
        let admitted = coordinator.start_run(100, closed.clone()).expect("admit");
        let (_, cancelled) = coordinator
            .cancel_run(
                100,
                &closed.run_id,
                admitted.revision,
                "retention_fixture",
            )
            .expect("close");
        assert_eq!(cancelled.phase, RunPhase::Cancelled);
    }
    assert_eq!(coordinator.runs.len(), MAX_RETAINED_RUNS);

    let mut next = snapshot();
    next.run_id = "run.zzzz.next".to_string();
    coordinator.start_run(100, next.clone()).expect("compact and admit");
    assert_eq!(coordinator.runs.len(), MAX_RETAINED_RUNS);
    assert!(coordinator.run("run.closed.0000").is_none());
    assert_eq!(coordinator.run(&next.run_id).expect("new run").phase, RunPhase::Admitted);
}

#[test]
fn terminal_observation_is_idempotent_and_only_closed_runs_can_be_removed() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    coordinator.start_run(100, snapshot()).expect("admit run");
    coordinator
        .attach_context(100, 1, attachment())
        .expect("attach context");
    coordinator
        .mark_dispatched(100, "run.1", 2)
        .expect("dispatch");
    let completed = coordinator
        .observe_terminal("run.1", 3, RunPhase::Succeeded, true)
        .expect("complete");
    let repeated = coordinator
        .observe_terminal("run.1", 3, RunPhase::Succeeded, true)
        .expect("repeat terminal observation");
    assert!(repeated.idempotent);
    assert_eq!(repeated.revision, completed.revision);
    let removed = coordinator
        .remove_closed_run("run.1", completed.revision)
        .expect("remove closed run");
    assert_eq!(removed.phase, RunPhase::Succeeded);
    assert_eq!(coordinator.run("run.1"), None);
}
