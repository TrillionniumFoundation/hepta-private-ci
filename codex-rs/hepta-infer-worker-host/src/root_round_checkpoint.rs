//! Retain one complete original numerical observation for the sealed Round.
//! Live eligibility is checked again by the same held Agentd reader at use.
use super::*;
use codex_hepta_agentd::PreparedParameterCheckpointV1;
use codex_hepta_agentd::decode_prepared_parameter_checkpoint_response_v3;
use codex_hepta_neuron::NeuronGenerationMaterialV2;

pub(super) async fn collect(
    client: &AgentdClient,
    before: &codex_hepta_supervisor::SupervisordAgentStatus,
    agent: &AgentId,
    round: &AgentdSelfIterationRoundV1,
    goal: &NeuronGenerationMaterialV2,
    goal_source: &InstalledCpuSourceV1,
    public: &Path,
) -> Result<(PreparedParameterCheckpointV1, InstalledCpuSourceV1)> {
    let spawn = before
        .spawn_generation
        .context("actual checkpoint spawn absent")?;
    let name = format!("checkpoint-response-{spawn}.bin");
    let path = public.join(&name);
    let bytes = if path.try_exists()? {
        codex_hepta_agent_components::learning_ledger::read_root_review_input(
            &path,
            codex_hepta_agentd::MAX_CONTROL_FRAME_BYTES,
        )
        .map_err(|error| anyhow::anyhow!("{error}"))?
    } else {
        let (generation, _, bytes) = client
            .prepare_parameter_checkpoint_source_v1(
                round.clone(),
                goal_source.path.clone(),
                goal_source.digest.parse()?,
            )
            .await?;
        current::validate_runtime_generation(before, generation)?;
        bytes
    };
    // The original decoder checks the complete frame, peer, whole Round and
    // complete Goal material. Retry never reconstructs or replaces its bytes.
    let (generation, checkpoint) =
        decode_prepared_parameter_checkpoint_response_v3(&bytes, agent, spawn, round, goal)?;
    current::validate_runtime_generation(before, generation)?;
    ensure!(
        checkpoint.baseline_material_digest == goal_source.digest.parse()?,
        "whole frozen checkpoint Goal Source changed"
    );
    let source = original_facts::publish(
        public,
        &name,
        &bytes,
        usize::try_from(codex_hepta_agentd::MAX_CONTROL_FRAME_BYTES)?,
    )?;
    Ok((checkpoint, source))
}
