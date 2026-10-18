//! Current owner observation, with no Fleet store or lifecycle writer.
use anyhow::ensure;
use codex_hepta_contracts::AgentId;
use codex_hepta_supervisor::SupervisordAgentStatus;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::SupervisordControlFence;
use codex_hepta_supervisor::SupervisordHealth;

use codex_hepta_matrixd::chat::native_wire::NativeChatBinding;

pub(super) async fn check(
    client: &SupervisordClient,
    binding: &NativeChatBinding,
) -> anyhow::Result<SupervisordAgentStatus> {
    let expected: SupervisordControlFence = serde_json::from_value(binding.control_fence.clone())?;
    expected
        .validate()
        .map_err(|_| anyhow::anyhow!("invalid original control fence"))?;
    let agent_id = AgentId::parse(binding.agent_id.clone())?;
    ensure!(expected.agent_id == agent_id, "foreign owner fence");
    let before = client.health().await?;
    let agent = client.snapshot(agent_id).await?;
    let after = client.health().await?;
    validate(&before, &agent, &after, binding, &expected)?;
    Ok(agent)
}

pub(super) fn validate(
    before: &SupervisordHealth,
    agent: &SupervisordAgentStatus,
    after: &SupervisordHealth,
    binding: &NativeChatBinding,
    expected: &SupervisordControlFence,
) -> anyhow::Result<()> {
    ensure!(
        before.ready
            && after.ready
            && before.process_id == after.process_id
            && before.supervisor_epoch == after.supervisor_epoch,
        "owner changed during chat observation"
    );
    ensure!(
        after.process_id == binding.supervisor_process_id
            && after.supervisor_epoch == expected.supervisor_epoch,
        "stale owner instance"
    );
    ensure!(
        agent.control_fence == *expected
            && agent.agent_id == expected.agent_id
            && agent.lifecycle_generation == expected.lifecycle_generation
            && agent.lifecycle == expected.lifecycle,
        "stale Agent fence"
    );
    ensure!(
        agent.active
            && agent.healthy
            && agent.lifecycle == codex_hepta_fleet::AgentLifecycle::Running
            && agent.process_id == Some(u64::from(binding.agent_process_id)),
        "Agent is not the displayed healthy process"
    );
    ensure!(
        agent.current_release.is_some()
            && !agent.release_change_pending
            && agent.current_release == expected.current_release
            && agent.previous_release == expected.previous_release
            && agent.spawn_generation == expected.spawn_generation
            && agent.runtime_generation == expected.runtime_generation
            && agent.spawn_generation.is_some(),
        "Agent release or generation changed"
    );
    Ok(())
}

#[cfg(test)]
#[path = "chat_root_current_tests.rs"]
mod tests;
