//! Measured topology candidates enter the existing signed artifact owner.
//! A budget decision alone cannot select or activate a population.

use codex_hepta_learning_artifacts::ArtifactPublicationReceiptV1;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_neuron::MemoryPopulationCostV2;
use codex_hepta_plasticity::MemoryStructureDecisionV1;
use codex_hepta_plasticity::TopologyOperationV2;
use codex_hepta_plasticity::TopologyProposalRequestV2;
use codex_hepta_plasticity::TopologyProposalV2;
use codex_hepta_plasticity::propose_memory_structure_v1;
use codex_hepta_types::Digest32;

use super::LoadedMemoryCellBundleV1;
use super::MemoryCellReleaseHostV1;

/// A published candidate still requires the existing independent signed
/// selection. `None` means the gate preserved the current owner and version.
pub struct MemoryStructurePublicationV9 {
    pub proposal: TopologyProposalV2,
    pub publication: Option<ArtifactPublicationReceiptV1>,
}

/// Bind a measured split/merge to exact population bytes and publish through
/// the real owner transaction. NoChange cannot publish even supplied bytes.
pub fn stage_memory_structure_v9(
    host: &MemoryCellReleaseHostV1,
    snapshot: &MemoryCellOwnerSnapshotV1,
    decision: &MemoryStructureDecisionV1,
    request: TopologyProposalRequestV2,
    candidate: Option<LearningArtifactPublishRequestV1>,
) -> Result<MemoryStructurePublicationV9, String> {
    let selected = host.load_current()?;
    selected.validate_owner_snapshot(snapshot)?;
    let selected_digest = selected.bundle_digest().to_string().parse::<Digest32>()
        .map_err(|error| error.to_string())?;
    if request.selected_artifact_digest != selected_digest
        || request.baseline_generation.get() != selected.generation().get()
    {
        return Err("memory structure proposal is not based on the selected owner version".to_string());
    }
    let proposal = propose_memory_structure_v1(request, decision).map_err(|error| error.to_string())?;
    let Some(proposed_digest) = decision.proposed_digest() else {
        host.revalidate(&selected)?;
        return Ok(MemoryStructurePublicationV9 { proposal, publication: None });
    };
    let candidate = candidate.ok_or_else(|| "positive structure decision needs exact candidate bytes".to_string())?;
    if Digest32::of_bytes(&candidate.payload) != proposed_digest
        || candidate.admission.validated_manifest.manifest.bytes_digest != proposed_digest
        || candidate.admission.validated_manifest.manifest.generation != proposal.candidate_generation
    {
        return Err("memory structure candidate differs from measured digest or generation".to_string());
    }
    let decoded = LoadedMemoryCellBundleV1::decode(&candidate.payload, proposed_digest)?;
    decoded.validate_owner_snapshot(snapshot)?;
    let change = proposal.candidates.iter().flat_map(|item| &item.changes).next()
        .ok_or_else(|| "positive structure proposal omitted its operation".to_string())?;
    for (before, after) in [(selected.semantic(), decoded.semantic()), (selected.procedure(), decoded.procedure())] {
        let valid = match change.operation {
            TopologyOperationV2::Split => after.shard_count() > before.shard_count(),
            TopologyOperationV2::Merge => after.shard_count() < before.shard_count(),
            TopologyOperationV2::Add | TopologyOperationV2::Remove | TopologyOperationV2::Replace
            | TopologyOperationV2::Rewire | TopologyOperationV2::Retire => false,
        };
        if !valid {
            return Err("proposed split/merge does not change both typed population cardinalities".to_string());
        }
    }
    host.revalidate(&selected)?;
    let publication = host.publish(candidate, snapshot)?;
    Ok(MemoryStructurePublicationV9 { proposal, publication: Some(publication) })
}

/// Reclaim decoded parameters of the selected generation. Its next authorized
/// read performs the existing bounded wake; source facts and release stay live.
pub fn sleep_selected_memory_v9(
    host: &MemoryCellReleaseHostV1,
    expected_bundle: Digest32,
) -> Result<[MemoryPopulationCostV2; 2], String> {
    let selected = host.load_current()?;
    if selected.bundle_digest().to_string() != expected_bundle.to_string() {
        return Err("sleep request refers to a superseded memory version".to_string());
    }
    let cells = [selected.semantic(), selected.procedure()];
    for cell in cells { cell.sleep().map_err(|error| error.to_string())?; }
    host.revalidate(&selected)?;
    Ok([cells[0].cost().map_err(|error| error.to_string())?, cells[1].cost().map_err(|error| error.to_string())?])
}

#[cfg(test)]
#[path = "memory_structure_runtime_v9_tests.rs"]
mod tests;
