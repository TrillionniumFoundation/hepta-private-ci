use super::*;

fn digest(byte: char) -> String {
    byte.to_string().repeat(64)
}

fn composition(generation: u64) -> RuntimeComposition {
    RuntimeComposition {
        agent_id: "agent.1".to_string(),
        supervisor_generation: generation,
        agentd_generation: generation,
        configuration_digest: digest('1'),
        ports_digest: digest('2'),
        cancellation_ack_timeout_ms: 1_000,
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
        AgentRunCoordinator::compose_runtime(composition(3)).expect("compose runtime");
    let admitted = coordinator.start_run(100, snapshot()).expect("admit run");
    assert_eq!(
        admitted,
        RunReceipt {
            run_id: "run.1".to_string(),
            revision: 1,
            phase: RunPhase::Admitted,
            context_digest: None,
            terminal_observed: false,
            idempotent: false,
            cancel_reason: None,
            cancellation_ack_deadline_ms: None,
        }
    );

    let mut mixed = attachment();
    mixed.body_digest = digest('9');
    assert_eq!(
        coordinator.attach_context(101, 1, mixed),
        Err(AgentRunError::MixedSnapshot)
    );

    let mut stale_authority = attachment();
    stale_authority.authority_epoch += 1;
    assert_eq!(
        coordinator.attach_context(101, 1, stale_authority),
        Err(AgentRunError::MixedSnapshot)
    );

    let mut stale_deadline = attachment();
    stale_deadline.deadline_ms += 1;
    assert_eq!(
        coordinator.attach_context(101, 1, stale_deadline),
        Err(AgentRunError::MixedSnapshot)
    );

    let attached = coordinator
        .attach_context(101, 1, attachment())
        .expect("attach context");
    assert_eq!(
        attached,
        RunReceipt {
            run_id: "run.1".to_string(),
            revision: 2,
            phase: RunPhase::ContextAttached,
            context_digest: Some(digest('7')),
            terminal_observed: false,
            idempotent: false,
            cancel_reason: None,
            cancellation_ack_deadline_ms: None,
        }
    );
}

#[test]
fn deadline_is_enforced_after_admission_and_expires_dispatched_runs_conservatively() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition(3)).expect("compose runtime");
    coordinator.start_run(100, snapshot()).expect("admit run");
    assert_eq!(
        coordinator.attach_context(10_000, 1, attachment()),
        Err(AgentRunError::DeadlineExceeded)
    );

    let expired = coordinator
        .expire_deadlines(10_000)
        .expect("expire pre-dispatch deadline");
    assert_eq!(expired.len(), 1);
    assert_eq!(expired[0].phase, RunPhase::Cancelled);
    assert_eq!(expired[0].cancel_reason.as_deref(), Some("deadline_exceeded"));

    let mut second = snapshot();
    second.run_id = "run.2".to_string();
    second.deadline_ms = 20_000;
    let mut second_attachment = attachment();
    second_attachment.run_id = second.run_id.clone();
    second_attachment.deadline_ms = second.deadline_ms;
    coordinator.start_run(100, second).expect("admit second");
    coordinator
        .attach_context(101, 1, second_attachment)
        .expect("attach second");
    coordinator
        .mark_dispatched(102, "run.2", 2)
        .expect("dispatch second");
    let expired = coordinator
        .expire_deadlines(20_000)
        .expect("expire dispatched deadline");
    assert_eq!(expired.len(), 1);
    assert_eq!(expired[0].phase, RunPhase::Cancelling);
    assert_eq!(expired[0].cancel_reason.as_deref(), Some("deadline_exceeded"));
    assert_eq!(expired[0].cancellation_ack_deadline_ms, Some(21_000));

    let uncertain = coordinator
        .expire_deadlines(21_000)
        .expect("expire cancellation acknowledgement");
    assert_eq!(uncertain.len(), 1);
    assert_eq!(uncertain[0].phase, RunPhase::Indeterminate);
    assert_eq!(uncertain[0].cancellation_ack_deadline_ms, None);
}

#[test]
fn cancellation_preserves_dispatch_boundary_reason_and_idempotency() {
    let mut before =
        AgentRunCoordinator::compose_runtime(composition(3)).expect("compose runtime");
    before.start_run(100, snapshot()).expect("admit run");
    let early = before
        .cancel_run(103, "run.1", 1, "operator_requested")
        .expect("cancel");
    assert_eq!(early.0, CancellationDisposition::CancelledBeforeDispatch);
    assert_eq!(early.1.phase, RunPhase::Cancelled);
    assert_eq!(early.1.cancel_reason.as_deref(), Some("operator_requested"));
    let repeated = before
        .cancel_run(104, "run.1", 1, "operator_requested")
        .expect("repeat cancel");
    assert_eq!(repeated.0, CancellationDisposition::AlreadyTerminal);
    assert!(repeated.1.idempotent);

    let mut after =
        AgentRunCoordinator::compose_runtime(composition(3)).expect("compose runtime");
    after.start_run(100, snapshot()).expect("admit run");
    after
        .attach_context(101, 1, attachment())
        .expect("attach context");
    after.mark_dispatched(102, "run.1", 2).expect("dispatch");
    let late = after
        .cancel_run(103, "run.1", 3, "operator_requested")
        .expect("cancel");
    assert_eq!(late.0, CancellationDisposition::CancellingAfterDispatch);
    assert_eq!(late.1.phase, RunPhase::Cancelling);
    assert_eq!(late.1.cancel_reason.as_deref(), Some("operator_requested"));
    assert_eq!(late.1.cancellation_ack_deadline_ms, Some(1_103));
    let repeated_late = after
        .cancel_run(u64::MAX, "run.1", 3, "operator_requested")
        .expect("repeat dispatched cancel");
    assert_eq!(repeated_late.0, CancellationDisposition::CancellingAfterDispatch);
    assert!(repeated_late.1.idempotent);
    assert_eq!(repeated_late.1.cancellation_ack_deadline_ms, Some(1_103));

    let terminal = after
        .observe_terminal("run.1", 4, RunPhase::Indeterminate, false)
        .expect("observe unknown terminality");
    assert_eq!(terminal.phase, RunPhase::Indeterminate);
    assert!(!terminal.terminal_observed);
    assert_eq!(terminal.cancellation_ack_deadline_ms, None);
}

#[test]
fn draining_rejects_new_admission_but_allows_idempotent_existing_retry() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition(3)).expect("compose runtime");
    let original = snapshot();
    coordinator
        .start_run(100, original.clone())
        .expect("admit run");
    coordinator.begin_drain();
    assert!(coordinator.is_draining());
    assert!(
        coordinator
            .start_run(10_001, original)
            .expect("retry after original deadline")
            .idempotent
    );

    let mut new_run = snapshot();
    new_run.run_id = "run.2".to_string();
    assert_eq!(
        coordinator.start_run(100, new_run),
        Err(AgentRunError::Draining)
    );
}

#[test]
fn operation_identity_is_idempotent_only_for_equal_semantics() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition(3)).expect("compose runtime");
    let original = snapshot();
    coordinator
        .start_run(100, original.clone())
        .expect("admit run");
    let repeated = coordinator.start_run(100, original).expect("repeat");
    assert!(repeated.idempotent);

    let mut changed = snapshot();
    changed.objective_digest = digest('9');
    assert_eq!(
        coordinator.start_run(100, changed),
        Err(AgentRunError::Conflict)
    );
}

#[test]
fn terminal_observation_is_idempotent_and_only_closed_runs_can_be_removed() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition(3)).expect("compose runtime");
    coordinator.start_run(100, snapshot()).expect("admit run");
    coordinator
        .attach_context(101, 1, attachment())
        .expect("attach context");
    coordinator.mark_dispatched(102, "run.1", 2).expect("dispatch");
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

#[test]
fn identical_context_bytes_do_not_hide_a_changed_run_snapshot() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition(3)).expect("compose");
    coordinator
        .start_run(/* now_ms */ 100, snapshot())
        .expect("admit");
    let original = coordinator
        .attach_context(/* now_ms */ 101, /* expected_revision */ 1, attachment())
        .expect("attach");
    let mut mixed = attachment();
    mixed.objective_digest = digest('9');
    assert_eq!(
        coordinator.attach_context(/* now_ms */ 101, /* expected_revision */ 1, mixed),
        Err(AgentRunError::MixedSnapshot)
    );
    let current = coordinator.run("run.1").expect("retained run");
    assert_eq!(current.revision, original.revision);
    assert_eq!(current.phase, original.phase);
}

#[test]
fn indeterminate_outcomes_reconcile_without_redispatch_or_leaked_capacity() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition(3)).expect("compose");
    for _ in 0..MAX_RETAINED_RUNS + 1 {
        coordinator
            .start_run(/* now_ms */ 100, snapshot())
            .expect("admit");
        coordinator
            .attach_context(/* now_ms */ 101, /* expected_revision */ 1, attachment())
            .expect("attach");
        coordinator
            .mark_dispatched(/* now_ms */ 102, "run.1", /* expected_revision */ 2)
            .expect("dispatch");
        let unknown = coordinator
            .observe_terminal(
                "run.1",
                /* expected_revision */ 3,
                RunPhase::Indeterminate,
                /* terminal_observed */ false,
            )
            .expect("unknown outcome");
        assert_eq!(
            coordinator.cancel_run(103, "run.1", unknown.revision, "operator_requested"),
            Err(AgentRunError::TerminalObservationRequired)
        );
        assert_eq!(
            coordinator.remove_closed_run("run.1", unknown.revision),
            Err(AgentRunError::InvalidTransition)
        );
        assert_eq!(
            coordinator.observe_terminal(
                "run.1",
                /* expected_revision */ 3,
                RunPhase::Succeeded,
                /* terminal_observed */ true
            ),
            Err(AgentRunError::StaleRevision)
        );
        let observed = coordinator
            .observe_terminal(
                "run.1",
                unknown.revision,
                RunPhase::Succeeded,
                /* terminal_observed */ true,
            )
            .expect("owner-observed reconciliation");
        assert!(observed.terminal_observed);
        coordinator
            .remove_closed_run("run.1", observed.revision)
            .expect("release capacity");
    }
    assert_eq!(coordinator.run("run.1"), None);
}

#[test]
fn restart_never_redispatches_uncertain_work() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition(3)).expect("compose");

    coordinator.start_run(100, snapshot()).expect("admit run");
    coordinator
        .attach_context(101, 1, attachment())
        .expect("attach context");
    coordinator.mark_dispatched(102, "run.1", 2).expect("dispatch");

    let mut second = snapshot();
    second.run_id = "run.2".to_string();
    let mut second_attachment = attachment();
    second_attachment.run_id = "run.2".to_string();
    coordinator.start_run(100, second).expect("admit second");
    coordinator
        .attach_context(101, 1, second_attachment)
        .expect("attach second");

    let changed = coordinator
        .reconcile_after_restart(composition(4))
        .expect("restart reconcile");
    assert_eq!(changed.len(), 2);
    assert_eq!(coordinator.run("run.1").expect("run 1").phase, RunPhase::Indeterminate);
    assert_eq!(coordinator.run("run.2").expect("run 2").phase, RunPhase::Cancelled);
    assert_eq!(coordinator.composition().agentd_generation, 4);
}

#[test]
fn shutdown_preserves_dispatch_uncertainty_and_closes_safe_work() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition(3)).expect("compose");

    coordinator.start_run(100, snapshot()).expect("admit run");
    coordinator
        .attach_context(101, 1, attachment())
        .expect("attach context");
    coordinator.mark_dispatched(102, "run.1", 2).expect("dispatch");

    let mut second = snapshot();
    second.run_id = "run.2".to_string();
    coordinator.start_run(100, second).expect("admit second");

    coordinator.begin_drain();
    coordinator
        .mark_unfinished_for_shutdown()
        .expect("shutdown reconcile");

    let run1 = coordinator.run("run.1").expect("run1");
    let run2 = coordinator.run("run.2").expect("run2");
    assert_eq!(run1.phase, RunPhase::Indeterminate);
    assert_eq!(
        run1.cancel_reason.as_deref(),
        Some("agentd_shutdown_after_dispatch")
    );
    assert_eq!(run2.phase, RunPhase::Cancelled);
    assert_eq!(
        run2.cancel_reason.as_deref(),
        Some("agentd_shutdown_before_dispatch")
    );
}


#[test]
fn recovered_state_rejects_impossible_phase_fields() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition(3)).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit run");

    coordinator
        .runs
        .get_mut("run.1")
        .expect("run record")
        .phase = RunPhase::Dispatched;
    assert_eq!(
        coordinator.validate_recovered_state(),
        Err(AgentRunError::InvalidTransition)
    );
}
