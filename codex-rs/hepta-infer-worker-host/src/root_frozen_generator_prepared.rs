//! Observe the original compiler's held fresh pair before an isolated G effect.
//! Root never opens or repairs a generation store to manufacture preparation.
use anyhow::Context;
use anyhow::Result;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_supervisor::SupervisordAgentStatus;
use codex_hepta_types::StableId;

use crate::CpuNeuronParameterRootMaterialsV2;

pub(super) async fn pair(
    client: &AgentdClient,
    current: &SupervisordAgentStatus,
    materials: &CpuNeuronParameterRootMaterialsV2,
    selected: &StableId,
) -> Result<()> {
    let candidate = materials
        .with_plan(|plan| {
            plan.candidates
                .iter()
                .find(|entry| entry.candidate_id == selected)
                .map(|entry| entry.generation.clone())
        })
        .context("original selected generation absent")?;
    for expected in [candidate, materials.rollback().clone()] {
        let (generation, packet) = client
            .prepared_generation_v2(
                expected.runtime.generation.get(),
                expected.runtime.semantic_digest()?,
                expected.body.semantic_digest()?,
            )
            .await?;
        super::current::validate_runtime_generation(current, generation)?;
        packet
            .context("original fresh physical generation is unavailable")?
            .validate_against(&expected)?;
    }
    Ok(())
}
