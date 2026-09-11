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
        context_digest: digest('7'),
        compilation_receipt_digest: digest('8'),
    }
}

#[test]
fn freezes_the_run_tuple_before_context_attachment() {
    let mut coordinator =
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
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
        }
    );

    let mut mixed = attachment();
    mixed.body_digest = digest('9');
    assert_eq!(
        coordinator.attach_context(1, mixed),
        Err(AgentRunError::MixedSnapshot)
    );

    let attached = coordinator
        .attach_context(1, attachment())
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
        }
    );
}

#[test]
fn cancellation_preserves_the_dispatch_boundary() {
    let mut before = AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    before.start_run(100, snapshot()).expect("admit run");
    let early = before.cancel_run("run.1", 1).expect("cancel");
    assert_eq!(
        early,
        (
            CancellationDisposition::CancelledBeforeDispatch,
            RunReceipt {
                run_id: "run.1".to_string(),
                revision: 2,
                phase: RunPhase::Cancelled,
                context_digest: None,
                terminal_observed: true,
                idempotent: false,
            },
        )
    );

    let mut after = AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    after.start_run(100, snapshot()).expect("admit run");
    after
        .attach_context(1, attachment())
        .expect("attach context");
    after.mark_dispatched("run.1", 2).expect("dispatch");
    let late = after.cancel_run("run.1", 3).expect("cancel");
    assert_eq!(late.0, CancellationDisposition::CancellingAfterDispatch);
    assert_eq!(late.1.phase, RunPhase::Cancelling);
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
        AgentRunCoordinator::compose_runtime(composition()).expect("compose runtime");
    coordinator.start_run(100, snapshot()).expect("admit run");
    coordinator
        .attach_context(1, attachment())
        .expect("attach context");
    coordinator.mark_dispatched("run.1", 2).expect("dispatch");
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
