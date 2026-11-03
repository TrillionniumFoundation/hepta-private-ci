use super::*;
use pretty_assertions::assert_eq;

fn dispatched() -> Result<(AgentRunCoordinator, RunRecovery), AgentRunError> {
    let mut runs = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.lifecycle-observer".to_owned(),
        supervisor_generation: 2,
        agentd_generation: 3,
        configuration_digest: "1".repeat(64),
        ports_digest: "2".repeat(64),
        max_active_runs: 2,
    })?;
    let snapshot = RunSnapshot {
        run_id: "run.lifecycle-observer".to_owned(),
        request_digest: "3".repeat(64),
        objective_digest: "4".repeat(64),
        body_digest: "5".repeat(64),
        artifact_set_digest: "6".repeat(64),
        authority_epoch: 7,
        generation: 3,
        fence_digest: "9".repeat(64),
        deadline_ms: 10_000,
    };
    let admitted = runs.start_run(100, snapshot.clone())?;
    let attached = runs.attach_context(200, admitted.revision, ContextAttachment {
        run_id: snapshot.run_id.clone(),
        request_digest: snapshot.request_digest.clone(),
        objective_digest: snapshot.objective_digest.clone(),
        body_digest: snapshot.body_digest.clone(),
        artifact_set_digest: snapshot.artifact_set_digest.clone(),
        authority_epoch: snapshot.authority_epoch,
        generation: snapshot.generation,
        fence_digest: snapshot.fence_digest.clone(),
        deadline_ms: snapshot.deadline_ms,
        context_digest: "7".repeat(64),
        compilation_receipt_digest: "8".repeat(64),
    })?;
    runs.mark_dispatched(300, &snapshot.run_id, attached.revision)?;
    let recovery = runs.recovery_record(&snapshot.run_id)?;
    Ok((runs, recovery))
}

#[test]
fn original_observation_rejects_future_checkpoint_without_changing_the_owner() -> Result<(), AgentRunError> {
    let (mut runs, original) = dispatched()?;
    let run_id = &original.snapshot.run_id;
    runs.observe_terminal(run_id, original.revision, RunPhase::Indeterminate, false)?;
    let before = runs.recovery_record(run_id)?;
    let receipt = runs.run(run_id).ok_or(AgentRunError::RunNotFound)?;
    for revision in [before.revision + 1, u64::MAX] {
        let mut future = original.clone();
        future.revision = revision;
        assert_eq!(runs.restore_original_observation(future, None, None), Err(AgentRunError::StaleRevision));
        assert_eq!(runs.recovery_record(run_id)?, before);
        assert_eq!(runs.run(run_id), Some(receipt.clone()));
    }
    let observed = runs.restore_original_observation(original.clone(), None, None)?;
    assert_eq!((observed.revision, observed.phase, observed.cancel_reason),
        (before.revision, RunPhase::Indeterminate, None));
    assert_eq!(runs.restore_original_observation(before.clone(), None, None)?.revision, before.revision);
    assert_eq!(runs.recovery_record(run_id)?, before);
    Ok(())
}

#[test]
fn original_observation_preserves_later_cancellation_and_rejects_conflicting_reason() -> Result<(), AgentRunError> {
    let (mut runs, original) = dispatched()?;
    let run_id = &original.snapshot.run_id;
    let (_, cancelled) = runs.cancel_run(400, run_id, original.revision, "original_operator_stop")?;
    let cancellation = runs.recovery_record(run_id)?;
    for phase in [RunPhase::Cancelling, RunPhase::Indeterminate] {
        if phase == RunPhase::Indeterminate {
            runs.observe_terminal(run_id, cancelled.revision, phase, false)?;
        }
        let before = runs.recovery_record(run_id)?;
        let receipt = runs.run(run_id).ok_or(AgentRunError::RunNotFound)?;
        let mut same_revision_without_reason = before.clone();
        same_revision_without_reason.cancel_reason = None;
        let mut earlier_conflicting_reason = original.clone();
        earlier_conflicting_reason.cancel_reason = Some("different_stop".to_owned());
        for conflicting in [same_revision_without_reason, earlier_conflicting_reason] {
            assert_eq!(runs.restore_original_observation(conflicting, None, None), Err(AgentRunError::Conflict));
            assert_eq!(runs.recovery_record(run_id)?, before);
            assert_eq!(runs.run(run_id), Some(receipt.clone()));
        }
        // The older, genuinely pre-cancellation anchor remains observable.
        // Its missing reason cannot clear the original owner's newer fact.
        let observed = runs.restore_original_observation(original.clone(), None, None)?;
        assert_eq!((observed.revision, observed.phase, observed.cancel_reason.as_deref()),
            (before.revision, phase, Some("original_operator_stop")));
        let after_cancel = runs.restore_original_observation(cancellation.clone(), None, None)?;
        assert_eq!(after_cancel.cancel_reason.as_deref(), Some("original_operator_stop"));
        assert_eq!(runs.recovery_record(run_id)?, before);
    }
    Ok(())
}
