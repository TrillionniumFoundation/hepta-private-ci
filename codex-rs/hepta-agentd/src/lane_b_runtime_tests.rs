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
        hard_constraint_digest: digest('7'),
        preference_state_digest: digest('8'),
        model_tuple_digest: digest('9'),
        prompt_registry_digest: digest('a'),
        body_digest: digest('5'),
        artifact_set_digest: digest('6'),
        authority_epoch: 7,
        generation: 3,
        fence_digest: digest('b'),
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

#[test]
fn identical_context_bytes_do_not_hide_a_changed_run_snapshot() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator
        .start_run(/*now_ms*/ 100, snapshot())
        .expect("admit");
    let original = coordinator
        .attach_context(/*expected_revision*/ 1, attachment())
        .expect("attach");
    let mut mixed = attachment();
    mixed.objective_digest = digest('9');
    assert_eq!(
        coordinator.attach_context(/*expected_revision*/ 1, mixed),
        Err(AgentRunError::MixedSnapshot)
    );
    let current = coordinator.run("run.1").expect("retained run");
    assert_eq!(current.revision, original.revision);
    assert_eq!(current.phase, original.phase);
}

#[test]
fn indeterminate_outcomes_reconcile_without_redispatch_or_leaked_capacity() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    for _ in 0..MAX_RETAINED_RUNS + 1 {
        coordinator
            .start_run(/*now_ms*/ 100, snapshot())
            .expect("admit");
        coordinator
            .attach_context(/*expected_revision*/ 1, attachment())
            .expect("attach");
        coordinator
            .mark_dispatched("run.1", /*expected_revision*/ 2)
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
            coordinator.cancel_run("run.1", unknown.revision),
            Err(AgentRunError::TerminalObservationRequired)
        );
        assert_eq!(
            coordinator.remove_closed_run("run.1", unknown.revision),
            Err(AgentRunError::InvalidTransition)
        );
        assert_eq!(
            coordinator.observe_terminal(
                "run.1",
                /*expected_revision*/ 3,
                RunPhase::Succeeded,
                /*terminal_observed*/ true
            ),
            Err(AgentRunError::StaleRevision)
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


#[test]
fn published_objective_run_start_is_consumed_without_new_durable_ownership() {
    use codex_hepta_objective::RunStartSnapshotV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    let run_start = RunStartSnapshotV1 {
        run_id: StableId::new("run.2").expect("run id"),
        objective_digest: Digest32::of_bytes(b"objective"),
        hard_constraint_digest: Digest32::of_bytes(b"hard"),
        preference_state_digest: Digest32::of_bytes(b"preference"),
        model_tuple_digest: Digest32::of_bytes(b"model"),
        prompt_registry_digest: Digest32::of_bytes(b"prompt"),
        artifact_set_digest: Digest32::of_bytes(b"artifact"),
        authority_epoch: 7,
        generation: 3,
        fence_digest: Digest32::of_bytes(b"fence"),
    };
    let receipt = coordinator
        .start_objective_run(
            100,
            &run_start,
            ObjectiveRunStartRuntimeBindings {
                request_digest: digest('c'),
                body_digest: digest('d'),
                deadline_ms: 10_000,
            },
        )
        .expect("admit published objective run");
    assert_eq!(receipt.run_id, "run.2");
    assert_eq!(receipt.phase, RunPhase::Admitted);

    let mut wrong_generation = run_start;
    wrong_generation.generation = 4;
    assert_eq!(
        coordinator.start_objective_run(
            100,
            &wrong_generation,
            ObjectiveRunStartRuntimeBindings {
                request_digest: digest('c'),
                body_digest: digest('d'),
                deadline_ms: 10_000,
            },
        ),
        Err(AgentRunError::InvalidGeneration)
    );
}
