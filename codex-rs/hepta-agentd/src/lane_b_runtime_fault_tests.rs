use super::*;

use pretty_assertions::assert_eq;

fn snapshot() -> RunSnapshot {
    RunSnapshot {
        run_id: "run.recovery".to_string(),
        request_digest: "3".repeat(64),
        objective_digest: "4".repeat(64),
        body_digest: "5".repeat(64),
        artifact_set_digest: "6".repeat(64),
        authority_epoch: 7,
        generation: 3,
        fence_digest: "9".repeat(64),
        deadline_ms: u64::MAX,
    }
}

fn coordinator() -> AgentRunCoordinator {
    AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.recovery".to_string(),
        supervisor_generation: 2,
        agentd_generation: 3,
        configuration_digest: "1".repeat(64),
        ports_digest: "2".repeat(64),
        max_active_runs: 1,
    })
    .expect("compose runtime")
}

fn recovery(revision: u64) -> RunRecovery {
    RunRecovery {
        snapshot: snapshot(),
        revision,
        context_digest: "7".repeat(64),
        compilation_receipt_digest: "8".repeat(64),
        cancel_reason: Some("process_restart".to_string()),
    }
}

#[test]
fn exhausted_recovered_revision_keeps_unresolved_reservation() {
    for phase in [RunPhase::Cancelled, RunPhase::Succeeded, RunPhase::Failed] {
        let mut coordinator = coordinator();
        let before = coordinator
            .recover_indeterminate(recovery(u64::MAX))
            .expect("recover unresolved run");

        assert_eq!(
            coordinator.observe_terminal(
                &before.run_id,
                before.revision,
                phase,
                /*terminal_observed*/ true,
            ),
            Err(AgentRunError::ArithmeticOverflow)
        );
        assert_eq!(coordinator.run(&before.run_id), Some(before.clone()));
        assert_eq!(coordinator.active_run_count(), 1);
        assert_eq!(coordinator.unresolved_run_count(), 1);
        assert_eq!(
            coordinator.remove_closed_run(&before.run_id, before.revision),
            Err(AgentRunError::InvalidTransition)
        );
        assert_eq!(
            coordinator.mark_dispatched(/*now_ms*/ 100, &before.run_id, before.revision,),
            Err(AgentRunError::InvalidTransition)
        );

        let mut replacement = snapshot();
        replacement.run_id = "run.replacement".to_string();
        assert_eq!(
            coordinator.start_run(/*now_ms*/ 100, replacement),
            Err(AgentRunError::CapacityExceeded)
        );
    }
}

#[test]
fn acknowledgement_deadline_overflow_preserves_dispatched_record() {
    let mut coordinator = coordinator();
    let snapshot = snapshot();
    let admitted = coordinator
        .start_run(/*now_ms*/ 100, snapshot.clone())
        .expect("admit run");
    let attached = coordinator
        .attach_context(
            /*now_ms*/ 200,
            admitted.revision,
            ContextAttachment {
                run_id: snapshot.run_id,
                request_digest: snapshot.request_digest,
                objective_digest: snapshot.objective_digest,
                body_digest: snapshot.body_digest,
                artifact_set_digest: snapshot.artifact_set_digest,
                authority_epoch: snapshot.authority_epoch,
                generation: snapshot.generation,
                fence_digest: snapshot.fence_digest,
                deadline_ms: snapshot.deadline_ms,
                context_digest: "7".repeat(64),
                compilation_receipt_digest: "8".repeat(64),
            },
        )
        .expect("attach context");
    let before = coordinator
        .mark_dispatched(/*now_ms*/ 300, &attached.run_id, attached.revision)
        .expect("dispatch run");

    assert_eq!(
        coordinator.cancel_run(
            u64::MAX - 1_000,
            &before.run_id,
            before.revision,
            "operator_request",
        ),
        Err(AgentRunError::ArithmeticOverflow)
    );
    assert_eq!(coordinator.run(&before.run_id), Some(before.clone()));

    assert_eq!(
        coordinator.expire_deadlines(u64::MAX),
        Err(AgentRunError::ArithmeticOverflow)
    );
    assert_eq!(coordinator.run(&before.run_id), Some(before.clone()));

    assert_eq!(
        coordinator.begin_drain(u64::MAX - 1_000, "shutdown"),
        Err(AgentRunError::ArithmeticOverflow)
    );
    assert_eq!(coordinator.run(&before.run_id), Some(before));
    assert!(!coordinator.admissions_open());
    assert_eq!(coordinator.active_run_count(), 1);
    assert_eq!(coordinator.unresolved_run_count(), 1);
}

#[test]
fn last_representable_terminal_transition_still_reconciles() {
    let mut coordinator = coordinator();
    let recovered = coordinator
        .recover_indeterminate(recovery(u64::MAX - 1))
        .expect("recover unresolved run");
    let terminal = coordinator
        .observe_terminal(
            &recovered.run_id,
            recovered.revision,
            RunPhase::Succeeded,
            /*terminal_observed*/ true,
        )
        .expect("observe terminal at final revision");

    assert_eq!(terminal.revision, u64::MAX);
    assert_eq!(terminal.phase, RunPhase::Succeeded);
    assert!(terminal.terminal_observed);
    assert_eq!(coordinator.active_run_count(), 0);
    assert_eq!(coordinator.unresolved_run_count(), 0);

    let mut expected_replay = terminal.clone();
    expected_replay.idempotent = true;
    assert_eq!(
        coordinator.observe_terminal(
            &recovered.run_id,
            recovered.revision,
            RunPhase::Succeeded,
            /*terminal_observed*/ true,
        ),
        Ok(expected_replay)
    );
    assert_eq!(
        coordinator.remove_closed_run(&terminal.run_id, terminal.revision),
        Ok(terminal)
    );
}
