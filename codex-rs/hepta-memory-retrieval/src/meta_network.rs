//! Authority-free multi-Cell shadow recall: one immutable cue and snapshot,
//! typed Cell ticks, then evidence-bound Meta-Network routing. This adapter
//! owns no Encoder driver, writer, selector, weight update or topology apply.

use std::collections::BTreeSet;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::HnmfContractError;
use codex_hepta_cognitive_types::memory_cell::MemoryCellManifestV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellTickInputV1;
use codex_hepta_cognitive_types::memory_meta_network::MAX_MEMORY_META_CANDIDATES_V1;
use codex_hepta_cognitive_types::memory_meta_network::MemoryMetaNetworkPolicyV1;
use codex_hepta_cognitive_types::memory_meta_network::MemoryMetaRoutingCandidateV1;
use codex_hepta_cognitive_types::memory_meta_network::MemoryMetaShadowRouteV1;
use codex_hepta_cognitive_types::memory_meta_network::route_memory_cells_v1;

use crate::EngramDynamicsPolicyV1;
use crate::EngramSnapshotV1;
use crate::GeneratedCandidateInputV1;
use crate::MemoryCellRuntimeErrorV1;
use crate::MemoryCellShadowTickV1;
use crate::MemoryCueV1;
use crate::RetrievalPolicyV1;
use crate::run_memory_cell_tick;

/// One already-evidenced Cell projection evaluated against the shared immutable
/// retrieval cue/snapshot. The support and assessment are external references.
pub struct MemoryMetaCellTickSpecV1 {
    pub manifest: MemoryCellManifestV1,
    pub tick_input: MemoryCellTickInputV1,
    pub generated_input: GeneratedCandidateInputV1,
    pub evidence_ledger_digest: ContractDigestV1,
    pub encoder_feature_digest: ContractDigestV1,
    pub support_digest: Option<ContractDigestV1>,
    pub independent_assessment_digest: ContractDigestV1,
    pub relevance_ppm: u32,
    pub resource_cost_units: u32,
    pub association_group_digest: Option<ContractDigestV1>,
    pub contradiction_group_digest: Option<ContractDigestV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryMetaShadowBatchV1 {
    pub cell_ticks: Vec<MemoryCellShadowTickV1>,
    pub routing: MemoryMetaShadowRouteV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MemoryMetaBatchErrorV1 {
    Contract(HnmfContractError),
    Tick {
        cell_id: ContractIdV1,
        source: MemoryCellRuntimeErrorV1,
    },
}

impl std::fmt::Display for MemoryMetaBatchErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for MemoryMetaBatchErrorV1 {}

pub fn run_memory_meta_batch_shadow_v1(
    policy: &MemoryMetaNetworkPolicyV1,
    cue: &MemoryCueV1,
    retrieval_policy: &RetrievalPolicyV1,
    engram_snapshot: &EngramSnapshotV1,
    dynamics_policy: &EngramDynamicsPolicyV1,
    cells: &[MemoryMetaCellTickSpecV1],
) -> Result<MemoryMetaShadowBatchV1, MemoryMetaBatchErrorV1> {
    policy.validate().map_err(MemoryMetaBatchErrorV1::Contract)?;
    if cells.len() > MAX_MEMORY_META_CANDIDATES_V1 {
        return Err(MemoryMetaBatchErrorV1::Contract(
            HnmfContractError::Invalid("memory meta candidate count"),
        ));
    }
    if policy.snapshot_digest.digest() != engram_snapshot.snapshot_digest {
        return Err(MemoryMetaBatchErrorV1::Contract(
            HnmfContractError::Conflict("memory meta shared snapshot"),
        ));
    }
    let mut identities = BTreeSet::new();
    for cell in cells {
        if !identities.insert(cell.manifest.cell_id.clone()) {
            return Err(MemoryMetaBatchErrorV1::Contract(
                HnmfContractError::DuplicateIdentity("memory meta cell"),
            ));
        }
        // Preflight expensive shadow ticks without trusting any Cell-local
        // projection to redefine the shared Encoder or evidence frontiers.
        if cell.manifest.shared_base_digest != policy.shared_base_digest
            || cell.manifest.encoder_digest != policy.encoder_digest
            || cell.encoder_feature_digest != policy.encoder_feature_digest
            || cell.evidence_ledger_digest != policy.evidence_ledger_digest
            || cell.manifest.source_frontier_digest != policy.source_frontier_digest
            || cell.manifest.forget_frontier_digest != policy.forget_frontier_digest
            || cell.manifest.graph_generation != policy.graph_generation
            || cell.manifest.model_generation != policy.model_generation
            || cell.tick_input.snapshot_digest != policy.snapshot_digest
        {
            return Err(MemoryMetaBatchErrorV1::Contract(
                HnmfContractError::Conflict("memory meta evidence or generation drift"),
            ));
        }
    }

    let mut cell_ticks = Vec::with_capacity(cells.len());
    let mut candidates = Vec::with_capacity(cells.len());
    for cell in cells {
        let tick = run_memory_cell_tick(
            &cell.manifest,
            &cell.tick_input,
            cue,
            retrieval_policy,
            &cell.generated_input,
            engram_snapshot,
            dynamics_policy,
        )
        .map_err(|source| MemoryMetaBatchErrorV1::Tick {
            cell_id: cell.manifest.cell_id.clone(),
            source,
        })?;
        candidates.push(MemoryMetaRoutingCandidateV1 {
            manifest: cell.manifest.clone(),
            tick_input: cell.tick_input.clone(),
            tick_receipt: tick.receipt.clone(),
            evidence_ledger_digest: cell.evidence_ledger_digest,
            encoder_feature_digest: cell.encoder_feature_digest,
            support_digest: cell.support_digest,
            independent_assessment_digest: cell.independent_assessment_digest,
            relevance_ppm: cell.relevance_ppm,
            resource_cost_units: cell.resource_cost_units,
            association_group_digest: cell.association_group_digest,
            contradiction_group_digest: cell.contradiction_group_digest,
        });
        cell_ticks.push(tick);
    }
    let routing =
        route_memory_cells_v1(policy, &candidates).map_err(MemoryMetaBatchErrorV1::Contract)?;
    Ok(MemoryMetaShadowBatchV1 {
        cell_ticks,
        routing,
    })
}
