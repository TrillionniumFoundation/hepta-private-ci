//! Deterministic, authority-free sparse routing over typed Memory Cells.
//!
//! Facts and deletion truth belong to the external evidence ledger. A Cell is
//! only a version-bound projection. Neither routing nor a next-snapshot
//! proposal authorizes a writer, trainer, topology apply or production use.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractGenerationV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf::ppm;
use crate::memory_cell::MemoryCellManifestV1;
use crate::memory_cell::MemoryCellStatusV1;
use crate::memory_cell::MemoryCellTickInputV1;
use crate::memory_cell::MemoryCellTickReceiptV1;

pub const MEMORY_META_SCHEMA_VERSION_V1: u32 = 1;
pub const MAX_MEMORY_META_CANDIDATES_V1: usize = 64;
pub const MAX_MEMORY_META_SELECTED_V1: usize = 16;
pub const MAX_MEMORY_META_BUDGET_UNITS_V1: u32 = 1_000_000;
const PPM_DENOMINATOR: u64 = 1_000_000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryMetaNetworkPolicyV1 {
    pub schema_version: u32,
    pub shared_base_digest: ContractDigestV1,
    pub encoder_digest: ContractDigestV1,
    pub encoder_feature_digest: ContractDigestV1,
    pub evidence_ledger_digest: ContractDigestV1,
    pub snapshot_digest: ContractDigestV1,
    pub source_frontier_digest: ContractDigestV1,
    pub forget_frontier_digest: ContractDigestV1,
    pub graph_generation: ContractGenerationV1,
    pub model_generation: ContractGenerationV1,
    pub maximum_selected_cells: u16,
    pub maximum_compute_units: u32,
    pub minimum_relevance_ppm: u32,
    pub minimum_confidence_ppm: u32,
    pub maximum_ood_ppm: u32,
}

impl MemoryMetaNetworkPolicyV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema_version != MEMORY_META_SCHEMA_VERSION_V1 {
            return Err(HnmfContractError::Invalid("memory meta policy schema"));
        }
        if self.maximum_selected_cells == 0
            || usize::from(self.maximum_selected_cells) > MAX_MEMORY_META_SELECTED_V1
        {
            return Err(HnmfContractError::Invalid("memory meta selected bound"));
        }
        if self.maximum_compute_units == 0
            || self.maximum_compute_units > MAX_MEMORY_META_BUDGET_UNITS_V1
        {
            return Err(HnmfContractError::Invalid("memory meta resource bound"));
        }
        ppm(self.minimum_relevance_ppm, "memory meta relevance")?;
        ppm(self.minimum_confidence_ppm, "memory meta confidence")?;
        ppm(self.maximum_ood_ppm, "memory meta ood")?;
        Ok(())
    }
}

/// No fact text is stored here. The support digest refers to independently
/// verifiable evidence under the exact source and forget frontiers.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryMetaRoutingCandidateV1 {
    pub manifest: MemoryCellManifestV1,
    pub tick_input: MemoryCellTickInputV1,
    pub tick_receipt: MemoryCellTickReceiptV1,
    pub evidence_ledger_digest: ContractDigestV1,
    pub encoder_feature_digest: ContractDigestV1,
    pub support_digest: Option<ContractDigestV1>,
    pub independent_assessment_digest: ContractDigestV1,
    pub relevance_ppm: u32,
    pub resource_cost_units: u32,
    pub association_group_digest: Option<ContractDigestV1>,
    pub contradiction_group_digest: Option<ContractDigestV1>,
}

impl MemoryMetaRoutingCandidateV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        self.manifest.validate()?;
        self.tick_input.validate()?;
        self.tick_receipt.validate()?;
        ppm(self.relevance_ppm, "memory meta candidate relevance")?;
        if self.resource_cost_units == 0
            || self.resource_cost_units > MAX_MEMORY_META_BUDGET_UNITS_V1
        {
            return Err(HnmfContractError::Invalid("memory meta candidate cost"));
        }
        if self.resource_cost_units > self.tick_input.resource_budget_units {
            return Err(HnmfContractError::Conflict("memory meta local tick budget"));
        }
        if self.manifest.cell_id != self.tick_input.cell_id
            || self.manifest.graph_generation != self.tick_input.graph_generation
            || self.manifest.model_generation != self.tick_input.model_generation
            || self.manifest.source_frontier_digest != self.tick_input.source_frontier_digest
            || self.manifest.forget_frontier_digest != self.tick_input.forget_frontier_digest
            || self.tick_input.cell_id != self.tick_receipt.cell_id
            || self.tick_input.graph_generation != self.tick_receipt.graph_generation
            || self.tick_input.model_generation != self.tick_receipt.model_generation
            || self.tick_input.logical_sequence != self.tick_receipt.logical_sequence
            || self.tick_input.predecessor_checkpoint_digest
                != self.tick_receipt.predecessor_checkpoint_digest
        {
            return Err(HnmfContractError::Conflict("memory meta tick binding"));
        }
        if self.tick_receipt.resident_bytes > self.manifest.max_state_bytes {
            return Err(HnmfContractError::Conflict("memory meta resident state"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryMetaRouteDispositionV1 {
    Selected,
    Filtered,
    ConflictSuppressed,
    BudgetDeferred,
    CapacityDeferred,
}

impl MemoryMetaRouteDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Selected => 0,
            Self::Filtered => 1,
            Self::ConflictSuppressed => 2,
            Self::BudgetDeferred => 3,
            Self::CapacityDeferred => 4,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryMetaRouteDecisionV1 {
    pub cell_id: ContractIdV1,
    pub disposition: MemoryMetaRouteDispositionV1,
    pub utility_ppm: u32,
    pub resource_cost_units: u32,
    pub support_digest: Option<ContractDigestV1>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryMetaAssociationV1 {
    pub left_cell_id: ContractIdV1,
    pub right_cell_id: ContractIdV1,
    pub association_group_digest: ContractDigestV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryMetaRouteReceiptV1 {
    pub schema_version: u32,
    pub policy_digest: ContractDigestV1,
    pub complete_candidate_set_digest: ContractDigestV1,
    pub shared_base_digest: ContractDigestV1,
    pub encoder_digest: ContractDigestV1,
    pub encoder_feature_digest: ContractDigestV1,
    pub evidence_ledger_digest: ContractDigestV1,
    pub snapshot_digest: ContractDigestV1,
    pub source_frontier_digest: ContractDigestV1,
    pub forget_frontier_digest: ContractDigestV1,
    pub graph_generation: ContractGenerationV1,
    pub model_generation: ContractGenerationV1,
    pub decisions: Vec<MemoryMetaRouteDecisionV1>,
    pub associations: Vec<MemoryMetaAssociationV1>,
    pub resource_used_units: u32,
    pub abstained: bool,
    pub current_snapshot_immutable: bool,
    pub production_activation_allowed: bool,
    pub route_digest: ContractDigestV1,
}

impl MemoryMetaRouteReceiptV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema_version != MEMORY_META_SCHEMA_VERSION_V1 {
            return Err(HnmfContractError::Invalid("memory meta receipt schema"));
        }
        if !self.current_snapshot_immutable || self.production_activation_allowed {
            return Err(HnmfContractError::Conflict("memory meta route authority"));
        }
        if self.decisions.len() > MAX_MEMORY_META_CANDIDATES_V1 {
            return Err(HnmfContractError::Invalid("memory meta decision count"));
        }
        let mut seen = BTreeSet::new();
        let mut selected = BTreeSet::new();
        let mut spent = 0_u32;
        for decision in &self.decisions {
            if !seen.insert(decision.cell_id.clone()) {
                return Err(HnmfContractError::DuplicateIdentity("memory meta decision"));
            }
            ppm(decision.utility_ppm, "memory meta route utility")?;
            // A deserialized receipt must enforce the same per-candidate
            // resource floor and ceiling as direct routing. A recomputed
            // digest alone cannot make a zero-cost Cell reservation valid.
            if decision.resource_cost_units == 0
                || decision.resource_cost_units > MAX_MEMORY_META_BUDGET_UNITS_V1
            {
                return Err(HnmfContractError::Invalid("memory meta receipt candidate cost"));
            }
            if decision.disposition == MemoryMetaRouteDispositionV1::Selected {
                if decision.support_digest.is_none() {
                    return Err(HnmfContractError::Missing("memory meta selected support"));
                }
                // The live router never selects a zero-utility Cell. A
                // forged, self-rehashed receipt must not relax that invariant.
                if decision.utility_ppm == 0 {
                    return Err(HnmfContractError::Conflict("memory meta selected utility"));
                }
                spent = spent
                    .checked_add(decision.resource_cost_units)
                    .ok_or(HnmfContractError::Invalid("memory meta receipt budget"))?;
                selected.insert(decision.cell_id.clone());
            }
        }
        if spent != self.resource_used_units || self.abstained != selected.is_empty() {
            return Err(HnmfContractError::Conflict("memory meta receipt accounting"));
        }
        if selected.len() > MAX_MEMORY_META_SELECTED_V1
            || spent > MAX_MEMORY_META_BUDGET_UNITS_V1
        {
            return Err(HnmfContractError::Conflict("memory meta receipt capacity"));
        }
        let mut pairs = BTreeSet::new();
        for pair in &self.associations {
            if pair.left_cell_id >= pair.right_cell_id
                || !selected.contains(&pair.left_cell_id)
                || !selected.contains(&pair.right_cell_id)
                // A pair of Cells can belong to only one association group
                // in the original candidates. Distinct group digests must
                // not launder duplicate links into a rehashed receipt.
                || !pairs.insert((pair.left_cell_id.clone(), pair.right_cell_id.clone()))
            {
                return Err(HnmfContractError::Conflict("memory meta association"));
            }
        }
        if self.route_digest != canonical_meta_route_digest(self)? {
            return Err(HnmfContractError::Conflict("memory meta route digest"));
        }
        Ok(())
    }

    /// Re-derive every routing decision against the supplied policy and full
    /// original candidate set. An internally consistent receipt digest alone
    /// cannot prove that its decisions follow the actual source inputs.
    ///
    /// This is deterministic replay verification, not ledger authentication:
    /// callers must independently establish the trusted policy, candidates,
    /// source/forget frontiers and external evidence inclusion.
    pub fn validate_against(
        &self,
        policy: &MemoryMetaNetworkPolicyV1,
        candidates: &[MemoryMetaRoutingCandidateV1],
    ) -> Result<(), HnmfContractError> {
        self.validate()?;
        let expected = route_memory_cells_v1(policy, candidates)?;
        if *self != expected.receipt {
            return Err(HnmfContractError::Conflict(
                "memory meta route source binding",
            ));
        }
        Ok(())
    }
}

/// This wrapper is not a wire contract: authority is sealed and always denied.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryMetaShadowRouteV1 {
    pub receipt: MemoryMetaRouteReceiptV1,
    pub authority: AuthorityPosture,
}

/// Reject cycles among Cell parent links visible in this batch. Parents outside
/// the candidate set are allowed, but must be authenticated by the topology
/// owner separately. This check grants no topology mutation or writer authority.
pub fn validate_memory_meta_parent_forest_v1<'a>(
    manifests: impl IntoIterator<Item = &'a MemoryCellManifestV1>,
) -> Result<(), HnmfContractError> {
    let mut parents: BTreeMap<ContractIdV1, Option<ContractIdV1>> = BTreeMap::new();
    for manifest in manifests {
        if parents
            .insert(manifest.cell_id.clone(), manifest.parent_cell_id.clone())
            .is_some()
        {
            return Err(HnmfContractError::DuplicateIdentity("memory meta cell"));
        }
    }
    let mut acyclic = BTreeSet::new();
    for first in parents.keys() {
        let mut path = BTreeSet::new();
        let mut current = Some(first.clone());
        while let Some(cell_id) = current {
            if acyclic.contains(&cell_id) {
                break;
            }
            if !path.insert(cell_id.clone()) {
                return Err(HnmfContractError::Conflict("memory meta parent cycle"));
            }
            current = parents.get(&cell_id).cloned().flatten();
        }
        acyclic.extend(path);
    }
    Ok(())
}

pub fn route_memory_cells_v1(
    policy: &MemoryMetaNetworkPolicyV1,
    candidates: &[MemoryMetaRoutingCandidateV1],
) -> Result<MemoryMetaShadowRouteV1, HnmfContractError> {
    policy.validate()?;
    if candidates.len() > MAX_MEMORY_META_CANDIDATES_V1 {
        return Err(HnmfContractError::Invalid("memory meta candidate count"));
    }
    let mut by_identity: Vec<&MemoryMetaRoutingCandidateV1> = candidates.iter().collect();
    by_identity.sort_by(|left, right| left.manifest.cell_id.cmp(&right.manifest.cell_id));
    for (index, candidate) in by_identity.iter().enumerate() {
        candidate.validate()?;
        if index > 0 && by_identity[index - 1].manifest.cell_id == candidate.manifest.cell_id {
            return Err(HnmfContractError::DuplicateIdentity("memory meta cell"));
        }
        if candidate.manifest.shared_base_digest != policy.shared_base_digest
            || candidate.manifest.encoder_digest != policy.encoder_digest
            || candidate.encoder_feature_digest != policy.encoder_feature_digest
            || candidate.tick_input.snapshot_digest != policy.snapshot_digest
            || candidate.evidence_ledger_digest != policy.evidence_ledger_digest
            || candidate.manifest.source_frontier_digest != policy.source_frontier_digest
            || candidate.manifest.forget_frontier_digest != policy.forget_frontier_digest
            || candidate.manifest.graph_generation != policy.graph_generation
            || candidate.manifest.model_generation != policy.model_generation
        {
            return Err(HnmfContractError::Conflict("memory meta evidence or generation drift"));
        }
    }
    validate_memory_meta_parent_forest_v1(by_identity.iter().map(|cell| &cell.manifest))?;
    let policy_digest = domain_digest(b"hepta.memory-meta.policy.v1", policy)?;
    let complete_candidate_set_digest =
        domain_digest(b"hepta.memory-meta.candidate-set.v1", &by_identity)?;

    // No preference or budget winner may resolve contradictory fact support.
    // All eligible candidates in a disputed group must abstain from routing.
    let mut contradiction_counts: BTreeMap<ContractDigestV1, u32> = BTreeMap::new();
    for candidate in &by_identity {
        if eligible(policy, candidate) {
            if let Some(group) = candidate.contradiction_group_digest {
                *contradiction_counts.entry(group).or_insert(0) += 1;
            }
        }
    }
    let mut ranked = by_identity;
    ranked.sort_by(|left, right| {
        utility(right)
            .cmp(&utility(left))
            .then_with(|| left.manifest.cell_id.cmp(&right.manifest.cell_id))
    });

    let mut spent = 0_u32;
    let mut selected: Vec<&MemoryMetaRoutingCandidateV1> = Vec::new();
    let mut decisions = Vec::with_capacity(ranked.len());
    for candidate in ranked {
        let conflicted = candidate.contradiction_group_digest.is_some_and(|group| {
            contradiction_counts.get(&group).copied().unwrap_or(0) > 1
        });
        let disposition = if !eligible(policy, candidate) {
            MemoryMetaRouteDispositionV1::Filtered
        } else if conflicted {
            MemoryMetaRouteDispositionV1::ConflictSuppressed
        } else if selected.len() >= usize::from(policy.maximum_selected_cells) {
            MemoryMetaRouteDispositionV1::CapacityDeferred
        } else if candidate.resource_cost_units > policy.maximum_compute_units - spent {
            MemoryMetaRouteDispositionV1::BudgetDeferred
        } else {
            spent += candidate.resource_cost_units;
            selected.push(candidate);
            MemoryMetaRouteDispositionV1::Selected
        };
        decisions.push(MemoryMetaRouteDecisionV1 {
            cell_id: candidate.manifest.cell_id.clone(),
            disposition,
            utility_ppm: utility(candidate),
            resource_cost_units: candidate.resource_cost_units,
            support_digest: candidate.support_digest,
        });
    }
    let mut associations = Vec::new();
    for (index, left) in selected.iter().enumerate() {
        for right in selected.iter().skip(index + 1) {
            if let (Some(left_group), Some(right_group)) = (
                left.association_group_digest,
                right.association_group_digest,
            ) {
                if left_group == right_group {
                    let (first, second) = if left.manifest.cell_id < right.manifest.cell_id {
                        (&left.manifest.cell_id, &right.manifest.cell_id)
                    } else {
                        (&right.manifest.cell_id, &left.manifest.cell_id)
                    };
                    associations.push(MemoryMetaAssociationV1 {
                        left_cell_id: first.clone(),
                        right_cell_id: second.clone(),
                        association_group_digest: left_group,
                    });
                }
            }
        }
    }
    associations.sort_by(|left, right| {
        (
            left.association_group_digest,
            &left.left_cell_id,
            &left.right_cell_id,
        )
            .cmp(&(
                right.association_group_digest,
                &right.left_cell_id,
                &right.right_cell_id,
            ))
    });
    let mut receipt = MemoryMetaRouteReceiptV1 {
        schema_version: MEMORY_META_SCHEMA_VERSION_V1,
        policy_digest,
        complete_candidate_set_digest,
        shared_base_digest: policy.shared_base_digest,
        encoder_digest: policy.encoder_digest,
        encoder_feature_digest: policy.encoder_feature_digest,
        evidence_ledger_digest: policy.evidence_ledger_digest,
        snapshot_digest: policy.snapshot_digest,
        source_frontier_digest: policy.source_frontier_digest,
        forget_frontier_digest: policy.forget_frontier_digest,
        graph_generation: policy.graph_generation,
        model_generation: policy.model_generation,
        decisions,
        associations,
        resource_used_units: spent,
        abstained: selected.is_empty(),
        current_snapshot_immutable: true,
        production_activation_allowed: false,
        route_digest: policy_digest,
    };
    receipt.route_digest = canonical_meta_route_digest(&receipt)?;
    receipt.validate()?;
    Ok(MemoryMetaShadowRouteV1 {
        receipt,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn eligible(
    policy: &MemoryMetaNetworkPolicyV1,
    candidate: &MemoryMetaRoutingCandidateV1,
) -> bool {
    candidate.tick_receipt.status == MemoryCellStatusV1::Selected
        && candidate.support_digest.is_some()
        && candidate.relevance_ppm >= policy.minimum_relevance_ppm
        && candidate.tick_receipt.confidence_ppm >= policy.minimum_confidence_ppm
        && candidate.tick_receipt.ood_ppm <= policy.maximum_ood_ppm
        && utility(candidate) > 0
}

fn utility(candidate: &MemoryMetaRoutingCandidateV1) -> u32 {
    let weighted = u64::from(candidate.relevance_ppm)
        * u64::from(candidate.tick_receipt.confidence_ppm)
        / PPM_DENOMINATOR;
    u32::try_from(weighted.saturating_sub(u64::from(candidate.tick_receipt.ood_ppm)))
        .unwrap_or(u32::MAX)
}

fn domain_digest<T: Serialize + ?Sized>(
    domain: &[u8],
    value: &T,
) -> Result<ContractDigestV1, HnmfContractError> {
    let payload =
        serde_json::to_vec(value).map_err(|_| HnmfContractError::Invalid("meta digest JSON"))?;
    let mut bytes = Vec::with_capacity(domain.len() + payload.len() + 8);
    bytes.extend_from_slice(domain);
    bytes.extend_from_slice(&(payload.len() as u64).to_be_bytes());
    bytes.extend_from_slice(&payload);
    ContractDigestV1::from_digest(Digest32::of_bytes(&bytes))
}

fn canonical_meta_route_digest(
    receipt: &MemoryMetaRouteReceiptV1,
) -> Result<ContractDigestV1, HnmfContractError> {
    let mut bytes = b"hepta.memory-meta.route.v1".to_vec();
    for digest in [
        receipt.policy_digest,
        receipt.complete_candidate_set_digest,
        receipt.shared_base_digest,
        receipt.encoder_digest,
        receipt.encoder_feature_digest,
        receipt.evidence_ledger_digest,
        receipt.snapshot_digest,
        receipt.source_frontier_digest,
        receipt.forget_frontier_digest,
    ] {
        bytes.extend_from_slice(digest.digest().as_array());
    }
    bytes.extend_from_slice(&receipt.graph_generation.get().to_be_bytes());
    bytes.extend_from_slice(&receipt.model_generation.get().to_be_bytes());
    bytes.extend_from_slice(&(receipt.decisions.len() as u64).to_be_bytes());
    for decision in &receipt.decisions {
        frame_id(&mut bytes, &decision.cell_id);
        bytes.push(decision.disposition.tag());
        bytes.extend_from_slice(&decision.utility_ppm.to_be_bytes());
        bytes.extend_from_slice(&decision.resource_cost_units.to_be_bytes());
        frame_optional_digest(&mut bytes, decision.support_digest);
    }
    bytes.extend_from_slice(&(receipt.associations.len() as u64).to_be_bytes());
    for pair in &receipt.associations {
        frame_id(&mut bytes, &pair.left_cell_id);
        frame_id(&mut bytes, &pair.right_cell_id);
        bytes.extend_from_slice(pair.association_group_digest.digest().as_array());
    }
    bytes.extend_from_slice(&receipt.resource_used_units.to_be_bytes());
    bytes.push(u8::from(receipt.abstained));
    bytes.push(u8::from(receipt.current_snapshot_immutable));
    bytes.push(u8::from(receipt.production_activation_allowed));
    ContractDigestV1::from_digest(Digest32::of_bytes(&bytes))
}

fn frame_id(bytes: &mut Vec<u8>, id: &ContractIdV1) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn frame_optional_digest(bytes: &mut Vec<u8>, value: Option<ContractDigestV1>) {
    match value {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.digest().as_array());
        }
        None => bytes.push(0),
    }
}

/// Replay produces only an offline next-generation candidate. A separate
/// independent evaluator and owner must inspect every referenced receipt.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryCellNextSnapshotCandidateV1 {
    pub schema_version: u32,
    pub cell_id: ContractIdV1,
    pub shared_base_digest: ContractDigestV1,
    pub encoder_digest: ContractDigestV1,
    pub source_frontier_digest: ContractDigestV1,
    pub forget_frontier_digest: ContractDigestV1,
    pub predecessor_graph_generation: ContractGenerationV1,
    pub next_graph_generation: ContractGenerationV1,
    pub predecessor_model_generation: ContractGenerationV1,
    pub next_model_generation: ContractGenerationV1,
    pub replay_snapshot_digest: ContractDigestV1,
    pub replay_receipt_digest: ContractDigestV1,
    pub candidate_adapter_artifact_digest: ContractDigestV1,
    pub candidate_head_artifact_digest: ContractDigestV1,
    pub independent_evaluation_digest: ContractDigestV1,
    pub topology_proposal_digest: Option<ContractDigestV1>,
    pub rollback_plan_digest: ContractDigestV1,
    pub current_snapshot_immutable: bool,
    pub production_activation_allowed: bool,
}

impl MemoryCellNextSnapshotCandidateV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.schema_version != MEMORY_META_SCHEMA_VERSION_V1 {
            return Err(HnmfContractError::Invalid("memory next-snapshot schema"));
        }
        if !self.current_snapshot_immutable || self.production_activation_allowed {
            return Err(HnmfContractError::Conflict("memory next-snapshot authority"));
        }
        if self.next_model_generation != self.predecessor_model_generation.next()? {
            return Err(HnmfContractError::Conflict("memory next model generation"));
        }
        let expected_graph_generation = if self.topology_proposal_digest.is_some() {
            self.predecessor_graph_generation.next()?
        } else {
            self.predecessor_graph_generation
        };
        if self.next_graph_generation != expected_graph_generation {
            return Err(HnmfContractError::Conflict("memory next graph generation"));
        }
        Ok(())
    }

    pub fn validate_against(
        &self,
        manifest: &MemoryCellManifestV1,
    ) -> Result<(), HnmfContractError> {
        self.validate()?;
        manifest.validate()?;
        if self.cell_id != manifest.cell_id
            || self.shared_base_digest != manifest.shared_base_digest
            || self.encoder_digest != manifest.encoder_digest
            || self.source_frontier_digest != manifest.source_frontier_digest
            || self.forget_frontier_digest != manifest.forget_frontier_digest
            || self.predecessor_graph_generation != manifest.graph_generation
            || self.predecessor_model_generation != manifest.model_generation
        {
            return Err(HnmfContractError::Conflict("memory next-snapshot predecessor"));
        }
        if self.candidate_adapter_artifact_digest == manifest.adapter_artifact_digest
            && self.candidate_head_artifact_digest == manifest.head_artifact_digest
            && self.topology_proposal_digest.is_none()
        {
            return Err(HnmfContractError::Conflict("memory next-snapshot no-op"));
        }
        Ok(())
    }

    /// Strict frozen-Encoder shadow handoff between successive offline
    /// proposals. Source/forget frontier changes require a separately
    /// authenticated ledger migration; this method never infers one.
    ///
    /// The evaluator and replay receipts are opaque references here:
    /// non-reuse is necessary but does not prove evaluator independence.
    pub fn validate_after(
        &self,
        predecessor: &Self,
    ) -> Result<(), HnmfContractError> {
        predecessor.validate()?;
        self.validate()?;
        if self.cell_id != predecessor.cell_id
            || self.shared_base_digest != predecessor.shared_base_digest
            || self.encoder_digest != predecessor.encoder_digest
            || self.source_frontier_digest != predecessor.source_frontier_digest
            || self.forget_frontier_digest != predecessor.forget_frontier_digest
            || self.predecessor_graph_generation != predecessor.next_graph_generation
            || self.predecessor_model_generation != predecessor.next_model_generation
        {
            return Err(HnmfContractError::Conflict(
                "memory next-snapshot chain predecessor",
            ));
        }
        if self.replay_snapshot_digest == predecessor.replay_snapshot_digest
            || self.replay_receipt_digest == predecessor.replay_receipt_digest
            || self.independent_evaluation_digest == predecessor.independent_evaluation_digest
        {
            return Err(HnmfContractError::Conflict(
                "memory next-snapshot recycled evidence",
            ));
        }
        if self.candidate_adapter_artifact_digest
            == predecessor.candidate_adapter_artifact_digest
            && self.candidate_head_artifact_digest
                == predecessor.candidate_head_artifact_digest
            && self.topology_proposal_digest.is_none()
        {
            return Err(HnmfContractError::Conflict(
                "memory next-snapshot chain no-op",
            ));
        }
        Ok(())
    }

    /// Validate a bounded, oldest-first set of offline learning proposals.
    /// Adjacent checks alone permit reusing a replay/evaluator reference after
    /// an intervening generation; reject reuse anywhere in the supplied chain.
    /// Digest uniqueness is necessary but does not establish independent data,
    /// evaluator provenance, signed artifacts or production authority.
    pub fn validate_chain(chain: &[Self]) -> Result<(), HnmfContractError> {
        if !(3..=64).contains(&chain.len()) {
            return Err(HnmfContractError::Invalid(
                "memory next-snapshot chain length",
            ));
        }
        let mut replay_snapshots = BTreeSet::new();
        let mut replay_receipts = BTreeSet::new();
        let mut evaluations = BTreeSet::new();
        let mut topology_proposals = BTreeSet::new();
        for (index, candidate) in chain.iter().enumerate() {
            candidate.validate()?;
            if index > 0 {
                candidate.validate_after(&chain[index - 1])?;
            }
            if !replay_snapshots.insert(candidate.replay_snapshot_digest)
                || !replay_receipts.insert(candidate.replay_receipt_digest)
                || !evaluations.insert(candidate.independent_evaluation_digest)
            {
                return Err(HnmfContractError::Conflict(
                    "memory next-snapshot recycled chain evidence",
                ));
            }
            if let Some(topology) = candidate.topology_proposal_digest {
                if !topology_proposals.insert(topology) {
                    return Err(HnmfContractError::Conflict(
                        "memory next-snapshot recycled topology",
                    ));
                }
            }
        }
        Ok(())
    }

    /// Anchor the oldest proposal to a real current Cell manifest before
    /// assessing the internal multi-generation continuity of a candidate
    /// chain. Otherwise an internally consistent history could start at an
    /// invented owner, model generation or obsolete forget frontier.
    pub fn validate_chain_against(
        manifest: &MemoryCellManifestV1,
        chain: &[Self],
    ) -> Result<(), HnmfContractError> {
        let first = chain.first().ok_or(HnmfContractError::Invalid(
            "memory next-snapshot chain length",
        ))?;
        first.validate_against(manifest)?;
        Self::validate_chain(chain)
    }
}

#[cfg(test)]
#[path = "memory_meta_network_tests.rs"]
mod tests;
