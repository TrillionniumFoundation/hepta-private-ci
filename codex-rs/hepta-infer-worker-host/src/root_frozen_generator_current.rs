//! Authenticate the current original Agent before and after factual reading.
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_supervisor::RootAdmittedFleetPeerV1;
use codex_hepta_supervisor::SupervisordAgentStatus;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::SupervisordHealth;

pub(super) async fn read(
    supervisor: &SupervisordClient,
    agent_id: &AgentId,
    peer: &RootAdmittedFleetPeerV1,
) -> Result<SupervisordAgentStatus> {
    let before = supervisor.health().await?;
    let agent = supervisor.snapshot(agent_id.clone()).await?;
    let after = supervisor.health().await?;
    validate(
        &before,
        &agent,
        &after,
        agent_id,
        peer.subject(),
        peer.pid(),
    )?;
    Ok(agent)
}

fn validate(
    before: &SupervisordHealth,
    agent: &SupervisordAgentStatus,
    after: &SupervisordHealth,
    agent_id: &AgentId,
    subject: &str,
    pid: u32,
) -> Result<()> {
    agent
        .control_fence
        .validate()
        .map_err(|_| anyhow::anyhow!("invalid original Agent fence"))?;
    ensure!(
        before.ready
            && after.ready
            && before.process_id == after.process_id
            && before.supervisor_epoch == after.supervisor_epoch
            && agent.agent_id == *agent_id
            && agent.agent_id.as_str() == subject
            && agent.control_fence.supervisor_epoch == after.supervisor_epoch
            && agent.control_fence.agent_id == agent.agent_id
            && agent.control_fence.lifecycle == agent.lifecycle
            && agent.control_fence.lifecycle_generation == agent.lifecycle_generation
            && agent.active
            && agent.healthy
            && agent.lifecycle == AgentLifecycle::Running
            && agent.process_id == Some(u64::from(pid))
            && agent.current_release.is_some()
            && !agent.release_change_pending
            && agent.control_fence.current_release == agent.current_release
            && agent.control_fence.previous_release == agent.previous_release
            && agent.control_fence.release_change_pending == agent.release_change_pending
            && agent.control_fence.spawn_generation == agent.spawn_generation
            && agent.control_fence.runtime_generation == agent.runtime_generation
            && agent.spawn_generation.is_some(),
        "current original healthy Agent, supervisor or release changed"
    );
    Ok(())
}

#[cfg(test)]
#[path = "root_frozen_generator_current_tests.rs"]
mod tests;

pub(super) fn unchanged(
    before: &SupervisordAgentStatus,
    after: &SupervisordAgentStatus,
) -> Result<()> {
    ensure!(
        before.control_fence == after.control_fence && before.process_id == after.process_id,
        "original Agent changed during independent observation"
    );
    Ok(())
}

pub(super) fn validate_runtime_generation(
    current: &SupervisordAgentStatus,
    generation: u64,
) -> Result<()> {
    ensure!(
        current.runtime_generation == Some(generation),
        "original reader runtime generation changed"
    );
    Ok(())
}
