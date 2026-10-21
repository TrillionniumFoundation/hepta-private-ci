//! Bounded, auditable Meta-Network proposal over typed MemoryCells.
//!
//! This is a pure candidate planner, not a second retrieval, model, storage,
//! selector or execution spine. The evidence ledger and forget frontier are
//! external owners; the supplied witness is a binding, NOT authentication.

use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractGenerationV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf::PPM;
use crate::memory_cell::MAX_MEMORY_CELL_ACTIVE_CELLS;
use crate::memory_cell::MemoryCellManifestV1;
use crate::wire::canonical_contract_digest_v1;

pub const META_NETWORK_SCHEMA_VERSION_V1: u32 = 1;
pub const MAX_META_NETWORK_BIDS_V1: usize = MAX_MEMORY_CELL_ACTIVE_CELLS;
pub const MAX_META_NETWORK_LINKS_V1: usize = 256;
pub const MAX_META_NETWORK_COST_UNITS_V1: u32 = 1_000_000;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MetaNetworkPostureV1 {
    ShadowOnly,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MetaNetworkDispositionV1 {
    Abstained,
    AdvisorySelection,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MetaNetworkRelationV1 {
    Associate,
    Conflict,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MetaNetworkPolicyV1 {
    pub schema_version: u32,
    pub maximum_active_cells: u16,
    pub maximum_associations: u16,
    pub maximum_cost_units: u32,
    pub maximum_ood_ppm: u32,
    pub minimum_net_gain_units: u32,
}

impl MetaNetworkPolicyV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema_version != META_NETWORK_SCHEMA_VERSION_V1 {
            return Err(HnmfContractError::Invalid("meta policy schema"));
        }
        if self.maximum_active_cells == 0
            || usize::from(self.maximum_active_cells) > MAX_META_NETWORK_BIDS_V1
            || usize::from(self.maximum_associations) > MAX_META_NETWORK_LINKS_V1
            || self.maximum_cost_units == 0
            || self.maximum_cost_units > MAX_META_NETWORK_COST_UNITS_V1
            || self.maximum_ood_ppm > PPM
            || self.minimum_net_gain_units == 0
        {
            return Err(HnmfContractError::Invalid("meta policy bounds"));
        }
        Ok(())
    }
}

/// Exact ledger state supplied by the *existing* evidence owner. Matching this
/// value cannot prove its provenance; the caller must authenticate that owner.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MetaNetworkLedgerWitnessV1 {
    pub ledger_root_digest: ContractDigestV1,
    pub source_frontier_digest: ContractDigestV1,
    pub forget_frontier_digest: ContractDigestV1,
    pub admission_receipt_digest: ContractDigestV1,
}

/// A Cell's bounded request to be considered. Benefits, costs and OOD are
/// estimates, not observed model performance or proof of source correctness.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MetaNetworkCellBidV1 {
    pub manifest: MemoryCellManifestV1,
    pub manifest_digest: ContractDigestV1,
    pub evidence_receipt_digest: ContractDigestV1,
    pub estimated_gain_units: u32,
    pub estimated_cost_units: u32,
    pub risk_units: u32,
    pub ood_ppm: u32,
    pub abstain: bool,
}

/// An evidence-linked association or exclusion. The source evidence is not
/// copied into the graph, and association never overrides a conflict.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MetaNetworkLinkV1 {
    pub first_cell_id: ContractIdV1,
    pub second_cell_id: ContractIdV1,
    pub relation: MetaNetworkRelationV1,
    pub evidence_receipt_digest: ContractDigestV1,
    pub strength_ppm: u32,
}

/// One immutable proposed route, tied to a shared frozen Encoder generation,
/// source/forget watermarks and complete, bounded candidates.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MetaNetworkPlanV1 {
    pub schema_version: u32,
    pub request_id: ContractIdV1,
    pub input_digest: ContractDigestV1,
    pub shared_base_digest: ContractDigestV1,
    pub encoder_digest: ContractDigestV1,
    pub ledger_root_digest: ContractDigestV1,
    pub source_frontier_digest: ContractDigestV1,
    pub forget_frontier_digest: ContractDigestV1,
    pub admission_receipt_digest: ContractDigestV1,
    pub graph_generation: ContractGenerationV1,
    pub model_generation: ContractGenerationV1,
    pub policy: MetaNetworkPolicyV1,
    pub bids: Vec<MetaNetworkCellBidV1>,
    pub links: Vec<MetaNetworkLinkV1>,
}

impl MetaNetworkPlanV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema_version != META_NETWORK_SCHEMA_VERSION_V1 {
            return Err(HnmfContractError::Invalid("meta plan schema"));
        }
        self.policy.validate()?;
        if self.bids.len() > MAX_META_NETWORK_BIDS_V1
            || self.links.len() > MAX_META_NETWORK_LINKS_V1
        {
            return Err(HnmfContractError::Invalid("meta graph bounds"));
        }

        let mut cells = BTreeSet::new();
        for bid in &self.bids {
            bid.manifest.validate()?;
            let manifest = &bid.manifest;
            if !cells.insert(manifest.cell_id.clone()) {
                return Err(HnmfContractError::Conflict("duplicate meta cell"));
            }
            if manifest.shared_base_digest != self.shared_base_digest
                || manifest.encoder_digest != self.encoder_digest
                || manifest.graph_generation != self.graph_generation
                || manifest.model_generation != self.model_generation
            {
                return Err(HnmfContractError::Conflict("meta encoder generation"));
            }
            if manifest.source_frontier_digest != self.source_frontier_digest
                || manifest.forget_frontier_digest != self.forget_frontier_digest
            {
                return Err(HnmfContractError::Conflict("meta stale frontier"));
            }
            if self.policy.maximum_active_cells > manifest.max_active_cells {
                return Err(HnmfContractError::Conflict("meta active cell cap"));
            }
            let actual_digest = canonical_contract_digest_v1(manifest)
                .map_err(|_| HnmfContractError::Invalid("meta manifest digest"))?;
            if bid.manifest_digest.digest() != actual_digest {
                return Err(HnmfContractError::Conflict("meta manifest digest"));
            }
            if bid.ood_ppm > PPM {
                return Err(HnmfContractError::Invalid("meta bid ood"));
            }
            if bid.abstain && (bid.estimated_gain_units != 0 || bid.estimated_cost_units != 0) {
                return Err(HnmfContractError::Conflict("meta abstain budget"));
            }
        }

        let mut pairs = BTreeSet::new();
        for link in &self.links {
            if link.first_cell_id >= link.second_cell_id {
                return Err(HnmfContractError::Conflict("meta noncanonical link"));
            }
            if !cells.contains(&link.first_cell_id) || !cells.contains(&link.second_cell_id) {
                return Err(HnmfContractError::Missing("meta link endpoint"));
            }
            if link.strength_ppm == 0 || link.strength_ppm > PPM {
                return Err(HnmfContractError::Invalid("meta link strength"));
            }
            if !pairs.insert((&link.first_cell_id, &link.second_cell_id)) {
                return Err(HnmfContractError::Conflict("duplicate meta link"));
            }
        }
        Ok(())
    }

    /// Permutation-independent plan digest: complete bids and links are sorted
    /// before using the repository's canonical cognitive-wire digest.
    pub fn canonical_plan_digest(&self) -> Result<ContractDigestV1, HnmfContractError> {
        self.validate()?;
        let mut canonical = self.clone();
        canonical
            .bids
            .sort_by(|a, b| a.manifest.cell_id.cmp(&b.manifest.cell_id));
        canonical.links.sort_by(|a, b| {
            a.first_cell_id
                .cmp(&b.first_cell_id)
                .then_with(|| a.second_cell_id.cmp(&b.second_cell_id))
        });
        let digest = canonical_contract_digest_v1(&canonical)
            .map_err(|_| HnmfContractError::Invalid("meta canonical plan"))?;
        ContractDigestV1::from_digest(digest)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MetaNetworkRouteReceiptV1 {
    pub schema_version: u32,
    pub request_id: ContractIdV1,
    pub plan_digest: ContractDigestV1,
    pub ledger_root_digest: ContractDigestV1,
    pub source_frontier_digest: ContractDigestV1,
    pub forget_frontier_digest: ContractDigestV1,
    pub graph_generation: ContractGenerationV1,
    pub model_generation: ContractGenerationV1,
    pub disposition: MetaNetworkDispositionV1,
    pub selected_cell_ids: Vec<ContractIdV1>,
    pub omitted_cell_ids: Vec<ContractIdV1>,
    pub conflict_suppressed_cell_ids: Vec<ContractIdV1>,
    pub composed_links: Vec<MetaNetworkLinkV1>,
    pub estimated_spend_units: u32,
    pub posture: MetaNetworkPostureV1,
}

impl MetaNetworkRouteReceiptV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema_version != META_NETWORK_SCHEMA_VERSION_V1
            || self.selected_cell_ids.len() > MAX_META_NETWORK_BIDS_V1
            || self.omitted_cell_ids.len() > MAX_META_NETWORK_BIDS_V1
            || self.conflict_suppressed_cell_ids.len() > MAX_META_NETWORK_BIDS_V1
            || self.composed_links.len() > MAX_META_NETWORK_LINKS_V1
        {
            return Err(HnmfContractError::Invalid("meta receipt bounds"));
        }
        if self.selected_cell_ids.is_empty()
            != (self.disposition == MetaNetworkDispositionV1::Abstained)
        {
            return Err(HnmfContractError::Conflict("meta receipt disposition"));
        }
        let selected = self.selected_cell_ids.iter().collect::<BTreeSet<_>>();
        let omitted = self.omitted_cell_ids.iter().collect::<BTreeSet<_>>();
        if selected.len() != self.selected_cell_ids.len()
            || omitted.len() != self.omitted_cell_ids.len()
            || selected.iter().any(|cell| omitted.contains(cell))
            || self
                .conflict_suppressed_cell_ids
                .iter()
                .any(|cell| !omitted.contains(cell))
        {
            return Err(HnmfContractError::Conflict("meta receipt cells"));
        }
        for link in &self.composed_links {
            if link.relation != MetaNetworkRelationV1::Associate
                || !selected.contains(&link.first_cell_id)
                || !selected.contains(&link.second_cell_id)
            {
                return Err(HnmfContractError::Conflict("meta composed link"));
            }
        }
        Ok(())
    }

    /// Recompute against an externally authenticated current frontier. A bare
    /// syntactically valid receipt must never be treated as a selector grant.
    pub fn validate_against(
        &self,
        plan: &MetaNetworkPlanV1,
        witness: &MetaNetworkLedgerWitnessV1,
    ) -> Result<(), HnmfContractError> {
        self.validate()?;
        if *self != propose_meta_network_route_v1(plan, witness)? {
            return Err(HnmfContractError::Conflict("meta receipt recomputation"));
        }
        Ok(())
    }
}

/// Deterministic, candidate-only sparse route. No fact, model, Cell state,
/// source ledger, tool, scheduler or topology is mutated by this function.
pub fn propose_meta_network_route_v1(
    plan: &MetaNetworkPlanV1,
    witness: &MetaNetworkLedgerWitnessV1,
) -> Result<MetaNetworkRouteReceiptV1, HnmfContractError> {
    plan.validate()?;
    if plan.ledger_root_digest != witness.ledger_root_digest
        || plan.source_frontier_digest != witness.source_frontier_digest
        || plan.forget_frontier_digest != witness.forget_frontier_digest
        || plan.admission_receipt_digest != witness.admission_receipt_digest
    {
        return Err(HnmfContractError::Conflict("meta current ledger frontier"));
    }

    let mut ranked = plan
        .bids
        .iter()
        .map(|bid| {
            let net = i64::from(bid.estimated_gain_units)
                - i64::from(bid.estimated_cost_units)
                - i64::from(bid.risk_units);
            (bid, net)
        })
        .collect::<Vec<_>>();
    ranked.sort_by(|a, b| {
        b.1.cmp(&a.1)
            .then_with(|| a.0.manifest.cell_id.cmp(&b.0.manifest.cell_id))
    });
    let mut selected = BTreeSet::new();
    let mut suppressed = BTreeSet::new();
    let mut spend = 0_u32;
    for (bid, net) in ranked {
        if selected.len() >= usize::from(plan.policy.maximum_active_cells) {
            break;
        }
        if bid.abstain
            || bid.ood_ppm > plan.policy.maximum_ood_ppm
            || net < i64::from(plan.policy.minimum_net_gain_units)
            || bid.estimated_cost_units > plan.policy.maximum_cost_units - spend
        {
            continue;
        }
        let conflict = plan.links.iter().any(|link| {
            link.relation == MetaNetworkRelationV1::Conflict
                && ((link.first_cell_id == bid.manifest.cell_id
                    && selected.contains(&link.second_cell_id))
                    || (link.second_cell_id == bid.manifest.cell_id
                        && selected.contains(&link.first_cell_id)))
        });
        if conflict {
            suppressed.insert(bid.manifest.cell_id.clone());
            continue;
        }
        spend += bid.estimated_cost_units;
        selected.insert(bid.manifest.cell_id.clone());
    }

    let all_cells = plan
        .bids
        .iter()
        .map(|bid| bid.manifest.cell_id.clone())
        .collect::<BTreeSet<_>>();
    let omitted = all_cells.difference(&selected).cloned().collect::<Vec<_>>();
    let mut links = plan
        .links
        .iter()
        .filter(|link| {
            link.relation == MetaNetworkRelationV1::Associate
                && selected.contains(&link.first_cell_id)
                && selected.contains(&link.second_cell_id)
        })
        .cloned()
        .collect::<Vec<_>>();
    links.sort_by(|a, b| {
        b.strength_ppm
            .cmp(&a.strength_ppm)
            .then_with(|| a.first_cell_id.cmp(&b.first_cell_id))
            .then_with(|| a.second_cell_id.cmp(&b.second_cell_id))
    });
    links.truncate(usize::from(plan.policy.maximum_associations));
    links.sort_by(|a, b| {
        a.first_cell_id
            .cmp(&b.first_cell_id)
            .then_with(|| a.second_cell_id.cmp(&b.second_cell_id))
    });

    let receipt = MetaNetworkRouteReceiptV1 {
        schema_version: META_NETWORK_SCHEMA_VERSION_V1,
        request_id: plan.request_id.clone(),
        plan_digest: plan.canonical_plan_digest()?,
        ledger_root_digest: plan.ledger_root_digest,
        source_frontier_digest: plan.source_frontier_digest,
        forget_frontier_digest: plan.forget_frontier_digest,
        graph_generation: plan.graph_generation,
        model_generation: plan.model_generation,
        disposition: if selected.is_empty() {
            MetaNetworkDispositionV1::Abstained
        } else {
            MetaNetworkDispositionV1::AdvisorySelection
        },
        selected_cell_ids: selected.into_iter().collect(),
        omitted_cell_ids: omitted,
        conflict_suppressed_cell_ids: suppressed.into_iter().collect(),
        composed_links: links,
        estimated_spend_units: spend,
        posture: MetaNetworkPostureV1::ShadowOnly,
    };
    receipt.validate()?;
    Ok(receipt)
}

/// One next-snapshot candidate references the original replay, immutable
/// artifact, independent evaluation and topology evidence. It is NOT an apply
/// operation, approval, selector result or permission to retain deleted facts.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MetaNetworkNextSnapshotCandidateV1 {
    pub schema_version: u32,
    pub candidate_id: ContractIdV1,
    pub route_receipt_digest: ContractDigestV1,
    pub ledger_root_digest: ContractDigestV1,
    pub source_frontier_digest: ContractDigestV1,
    pub forget_frontier_digest: ContractDigestV1,
    pub replay_receipt_digest: ContractDigestV1,
    pub artifact_digest: ContractDigestV1,
    pub independent_evaluation_digest: ContractDigestV1,
    pub topology_proposal_digest: ContractDigestV1,
    pub predecessor_graph_generation: ContractGenerationV1,
    pub next_graph_generation: ContractGenerationV1,
    pub predecessor_model_generation: ContractGenerationV1,
    pub next_model_generation: ContractGenerationV1,
    pub posture: MetaNetworkPostureV1,
}

impl MetaNetworkNextSnapshotCandidateV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema_version != META_NETWORK_SCHEMA_VERSION_V1 {
            return Err(HnmfContractError::Invalid("meta next snapshot schema"));
        }
        if self.predecessor_graph_generation.next()? != self.next_graph_generation
            || (self.next_model_generation != self.predecessor_model_generation
                && self.predecessor_model_generation.next()? != self.next_model_generation)
        {
            return Err(HnmfContractError::Conflict("meta next snapshot generation"));
        }
        Ok(())
    }

    pub fn validate_against_route(
        &self,
        route: &MetaNetworkRouteReceiptV1,
    ) -> Result<(), HnmfContractError> {
        self.validate()?;
        route.validate()?;
        if route.disposition != MetaNetworkDispositionV1::AdvisorySelection
            || self.route_receipt_digest.digest()
                != canonical_contract_digest_v1(route)
                    .map_err(|_| HnmfContractError::Invalid("meta route digest"))?
            || self.ledger_root_digest != route.ledger_root_digest
            || self.source_frontier_digest != route.source_frontier_digest
            || self.forget_frontier_digest != route.forget_frontier_digest
            || self.predecessor_graph_generation != route.graph_generation
            || self.predecessor_model_generation != route.model_generation
        {
            return Err(HnmfContractError::Conflict("meta next snapshot route"));
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "meta_network_tests.rs"]
mod tests;
