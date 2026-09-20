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

fn assert_receipt(
    receipt: &RunReceipt,
    revision: u64,
    phase: RunPhase,
    cancel_reason: Option<&str>,
) {
    assert_eq!(receipt.run_id, "run.1");
    assert_eq!(receipt.revision, revision);
    assert_eq!(receipt.phase, phase);
    assert_eq!(receipt.authority_epoch, 7);
    assert_eq!(receipt.deadline_ms, 10_000);
    assert_eq!(receipt.cancel_reason.as_deref(), cancel_reason);
}

#[test]
fn freezes_the_complete_run_tuple_before_context_attachment() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    let admitted = coordinator.start_run(100, snapshot()).expect("admit run");
    assert_receipt(&admitted, 1, RunPhase::Admitted, None);

    let mut mixed = attachment();
    mixed.body_digest = digest('9');
    assert_eq!(
        coordinator.attach_context(200, 1, mixed),
        Err(AgentRunError::MixedSnapshot)
    );

    let mut wrong_authority = attachment();
    wrong_authority.authority_epoch = 8;
    assert_eq!(
        coordinator.attach_context(200, 1, wrong_authority),
        Err(AgentRunError::MixedSnapshot)
    );

    let mut wrong_deadline = attachment();
    wrong_deadline.deadline_ms += 1;
    assert_eq!(
        coordinator.attach_context(200, 1, wrong_deadline),
        Err(AgentRunError::MixedSnapshot)
    );

    let attached = coordinator
        .attach_context(200, 1, attachment())
        .expect("attach context");
    assert_receipt(&attached, 2, RunPhase::ContextAttached, None);
    assert_eq!(attached.context_digest, Some(digest('7')));
}

#[test]
fn cancellation_preserves_the_dispatch_boundary_and_reason() {
    let mut before = AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    before.start_run(100, snapshot()).expect("admit run");
    let early = before
        .cancel_run(200, "run.1", 1, "operator_request")
        .expect("cancel");
    assert_eq!(early.0, CancellationDisposition::CancelledBeforeDispatch);
    assert_receipt(&early.1, 2, RunPhase::Cancelled, Some("operator_request"));
    assert!(early.1.terminal_observed);

    let mut after = AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    after.start_run(100, snapshot()).expect("admit run");
    after
        .attach_context(200, 1, attachment())
        .expect("attach context");
    after.mark_dispatched(300, "run.1", 2).expect("dispatch");
    let late = after
        .cancel_run(400, "run.1", 3, "operator_request")
        .expect("cancel");
    assert_eq!(late.0, CancellationDisposition::CancellingAfterDispatch);
    assert_receipt(&late.1, 4, RunPhase::Cancelling, Some("operator_request"));

    let repeated = after
        .cancel_run(450, "run.1", 4, "operator_request")
        .expect("idempotent cancel");
    assert!(repeated.1.idempotent);
    assert_eq!(
        after.cancel_run(450, "run.1", 4, "different_reason"),
        Err(AgentRunError::Conflict)
    );

    let terminal = after
        .observe_terminal("run.1", 4, RunPhase::Indeterminate, false)
        .expect("observe unknown terminality");
    assert_receipt(
        &terminal,
        5,
        RunPhase::Indeterminate,
        Some("operator_request"),
    );
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
    coordinator.close_admissions();
    let repeated = coordinator.start_run(100, original).expect("repeat");
    assert!(repeated.idempotent);

    let mut changed = snapshot();
    changed.objective_digest = digest('9');
    assert_eq!(
        coordinator.start_run(100, changed),
        Err(AgentRunError::Conflict)
    );

    let mut new = snapshot();
    new.run_id = "run.2".to_string();
    assert_eq!(
        coordinator.start_run(100, new),
        Err(AgentRunError::AdmissionClosed)
    );
}

#[test]
fn lifecycle_deadline_is_enforced_after_admission() {
    let mut pre = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    let mut pre_snapshot = snapshot();
    pre_snapshot.deadline_ms = 200;
    pre.start_run(100, pre_snapshot).expect("start");
    assert_eq!(
        pre.attach_context(
            200,
            1,
            ContextAttachment {
                deadline_ms: 200,
                ..attachment()
            }
        ),
        Err(AgentRunError::DeadlineElapsed)
    );
    assert_eq!(pre.expire_deadlines(200).expect("expire"), 1);
    let expired = pre.run("run.1").expect("retained");
    assert_eq!(expired.phase, RunPhase::Cancelled);
    assert_eq!(expired.cancel_reason.as_deref(), Some("deadline_elapsed"));

    let mut post = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    let mut post_snapshot = snapshot();
    post_snapshot.deadline_ms = 300;
    post.start_run(100, post_snapshot).expect("start");
    post.attach_context(
        150,
        1,
        ContextAttachment {
            deadline_ms: 300,
            ..attachment()
        },
    )
    .expect("attach");
    post.mark_dispatched(200, "run.1", 2).expect("dispatch");
    assert_eq!(post.expire_deadlines(300).expect("expire"), 1);
    let expired = post.run("run.1").expect("retained");
    assert_eq!(expired.phase, RunPhase::Cancelling);
    assert_eq!(expired.cancel_reason.as_deref(), Some("deadline_elapsed"));
    assert!(!expired.terminal_observed);
}

#[test]
fn drain_closes_admission_and_preserves_dispatch_uncertainty() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");
    coordinator
        .attach_context(200, 1, attachment())
        .expect("attach");
    coordinator
        .mark_dispatched(300, "run.1", 2)
        .expect("dispatch");

    assert_eq!(
        coordinator
            .begin_drain(400, "agentd_draining")
            .expect("begin drain"),
        1
    );
    assert!(!coordinator.admissions_open());
    let draining = coordinator.run("run.1").expect("run");
    assert_eq!(draining.phase, RunPhase::Cancelling);
    assert_eq!(draining.cancel_reason.as_deref(), Some("agentd_draining"));

    assert_eq!(
        coordinator
            .mark_unresolved_indeterminate("shutdown_drain_timeout")
            .expect("mark unknown"),
        1
    );
    let unknown = coordinator.run("run.1").expect("run");
    assert_eq!(unknown.phase, RunPhase::Indeterminate);
    assert_eq!(coordinator.unresolved_run_count(), 1);
}

#[test]
fn recovery_rehydrates_only_an_indeterminate_non_redispatchable_run() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.close_admissions();
    let recovery = RunRecovery {
        snapshot: snapshot(),
        revision: 9,
        context_digest: digest('7'),
        compilation_receipt_digest: digest('8'),
        cancel_reason: Some("process_restart".to_string()),
    };
    let recovered = coordinator
        .recover_indeterminate(recovery.clone())
        .expect("recover");
    assert_receipt(
        &recovered,
        9,
        RunPhase::Indeterminate,
        Some("process_restart"),
    );
    let repeated = coordinator
        .recover_indeterminate(recovery)
        .expect("repeat recovery");
    assert!(repeated.idempotent);
    assert_eq!(
        coordinator.mark_dispatched(200, "run.1", 9),
        Err(AgentRunError::InvalidTransition)
    );

    let observed = coordinator
        .observe_terminal("run.1", 9, RunPhase::Succeeded, true)
        .expect("terminal reconciliation");
    assert_receipt(&observed, 10, RunPhase::Succeeded, Some("process_restart"));
    assert!(observed.terminal_observed);
}

#[test]
fn terminal_observation_is_idempotent_and_only_closed_runs_can_be_removed() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    coordinator.start_run(100, snapshot()).expect("admit run");
    coordinator
        .attach_context(200, 1, attachment())
        .expect("attach context");
    coordinator
        .mark_dispatched(300, "run.1", 2)
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

#[test]
fn indeterminate_outcomes_reconcile_without_redispatch_or_leaked_capacity() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    for _ in 0..MAX_RETAINED_RUNS + 1 {
        coordinator
            .start_run(/*now_ms*/ 100, snapshot())
            .expect("admit");
        coordinator
            .attach_context(
                /*now_ms*/ 200,
                /*expected_revision*/ 1,
                attachment(),
            )
            .expect("attach");
        coordinator
            .mark_dispatched(/*now_ms*/ 300, "run.1", /*expected_revision*/ 2)
            .expect("dispatch");
        let unknown = coordinator
            .observe_terminal(
                "run.1",
                /*expected_revision*/ 3,
                RunPhase::Indeterminate,
                /*terminal_observed*/ false,
            )
            .expect("unknown outcome");
        assert_eq!(
            coordinator.cancel_run(400, "run.1", unknown.revision, "operator_request"),
            Err(AgentRunError::TerminalObservationRequired)
        );
        assert_eq!(
            coordinator.remove_closed_run("run.1", unknown.revision),
            Err(AgentRunError::InvalidTransition)
        );
        let observed = coordinator
            .observe_terminal(
                "run.1",
                unknown.revision,
                RunPhase::Succeeded,
                /*terminal_observed*/ true,
            )
            .expect("owner-observed reconciliation");
        assert!(observed.terminal_observed);
        coordinator
            .remove_closed_run("run.1", observed.revision)
            .expect("release capacity");
    }
    assert_eq!(coordinator.run("run.1"), None);
}
