use super::*;
use crate::AgentRunCoordinator;
use crate::ContextAttachment;
use crate::RunPhase;

fn composition() -> RuntimeComposition {
    RuntimeComposition {
        agent_id: "agent.epoch".to_string(),
        supervisor_generation: 41,
        agentd_generation: 41,
        configuration_digest: "1".repeat(64),
        ports_digest: "2".repeat(64),
        max_active_runs: 8,
    }
}

fn snapshot() -> RunSnapshot {
    RunSnapshot {
        run_id: "run.epoch".to_string(),
        request_digest: "3".repeat(64),
        objective_digest: "4".repeat(64),
        body_digest: "5".repeat(64),
        artifact_set_digest: "6".repeat(64),
        authority_epoch: 9,
        generation: 42,
        fence_digest: objective_run_fence_digest("agent.epoch", 41, 42).to_string(),
        deadline_ms: 5_000,
    }
}

fn context(snapshot: &RunSnapshot) -> ContextAttachment {
    ContextAttachment {
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
    }
}

fn coordinator() -> AgentRunCoordinator {
    let mut owner = AgentRunCoordinator::compose_runtime(composition()).unwrap();
    owner
        .bind_run_epoch(AgentdRunEpochV1::running("agent.epoch", 41, 42).unwrap())
        .unwrap();
    owner
}

#[test]
fn running_epoch_does_not_alias_spawn_or_drain() {
    let epoch = AgentdRunEpochV1::running("agent.epoch", 41, 42).unwrap();
    assert_eq!(
        epoch.fence_digest(),
        objective_run_fence_digest("agent.epoch", 41, 42)
    );
    for current in [0, 40, 41, 43] {
        assert_eq!(
            AgentdRunEpochV1::running("agent.epoch", 41, current),
            Err(AgentRunError::InvalidGeneration)
        );
    }
    assert_eq!(
        AgentdRunEpochV1::running("agent.epoch", u64::MAX, 1),
        Err(AgentRunError::InvalidGeneration)
    );
}

#[test]
fn coordinator_enforces_generation_and_fence_without_wire_checks() {
    for (generation, fence) in [
        (41, objective_run_fence_digest("agent.epoch", 41, 41)),
        (42, objective_run_fence_digest("agent.other", 41, 42)),
    ] {
        let mut owner = coordinator();
        let mut value = snapshot();
        value.generation = generation;
        value.fence_digest = fence.to_string();
        assert_eq!(
            owner.start_run(1_000, value),
            Err(AgentRunError::MixedSnapshot)
        );
        assert_eq!(owner.active_run_count(), 0);
    }
}

#[test]
fn atomic_context_admission_rejects_without_leaking_run_capacity() {
    let mut owner = coordinator();
    let value = snapshot();
    let mut attachment = context(&value);
    attachment.body_digest = "9".repeat(64);
    assert_eq!(
        owner.admit_intelligence_context(1_000, value, attachment),
        Err(AgentRunError::MixedSnapshot)
    );
    assert_eq!(owner.run("run.epoch"), None);
    assert_eq!(owner.active_run_count(), 0);
}

#[test]
fn exact_replay_preserves_identity_and_does_not_redispatch() {
    let mut owner = coordinator();
    let value = snapshot();
    let attachment = context(&value);
    let first = owner
        .admit_intelligence_context(1_000, value.clone(), attachment.clone())
        .unwrap();
    assert_eq!(first.phase, RunPhase::ContextAttached);
    let dispatched = owner
        .mark_dispatched(1_001, &first.run_id, first.revision)
        .unwrap();
    let replay = owner
        .admit_intelligence_context(6_000, value, attachment)
        .unwrap();
    assert_eq!(replay.phase, RunPhase::Dispatched);
    assert_eq!(replay.revision, dispatched.revision);
    assert!(replay.idempotent);
}

#[test]
fn semantic_drift_conflicts_instead_of_refreshing_the_deadline() {
    let mut owner = coordinator();
    let value = snapshot();
    owner
        .admit_intelligence_context(1_000, value.clone(), context(&value))
        .unwrap();
    let mut changed = value;
    changed.deadline_ms += 1;
    assert_eq!(
        owner.admit_intelligence_context(1_100, changed.clone(), context(&changed)),
        Err(AgentRunError::Conflict)
    );
}

#[test]
fn another_process_cannot_rebind_the_owner_epoch() {
    let mut owner = coordinator();
    let other = AgentdRunEpochV1::running("agent.epoch", 43, 44).unwrap();
    assert_eq!(
        owner.bind_run_epoch(other),
        Err(AgentRunError::MixedSnapshot)
    );
}
