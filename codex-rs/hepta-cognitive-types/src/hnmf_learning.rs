//! Canonical HNMF V1 engram, recall, replay, plasticity, topology and forget contracts.

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::hnmf::{
    ContractDigestV1, ContractGenerationV1, ContractIdV1, HnmfContractError, ModalityKindV1,
    PPM, ppm, validate_keys, validate_text,
};

pub const MAX_CUE_SEEDS: usize = 64;
pub const MAX_CANDIDATE_EVENTS: usize = 512;
pub const MAX_NODES: usize = 4_096;
pub const MAX_SYNAPSES: usize = 32_768;
pub const MAX_ACTIVE_NODES: usize = 4_096;
pub const MAX_ACTIVE_PER_POPULATION: usize = 64;
pub const MAX_RECURRENT_STEPS: u8 = 4;
pub const MAX_RECALL_EVENTS: usize = 16;
pub const MAX_ACTIVATION_PATHS: usize = 32;
pub const MAX_REPLAY_CANDIDATES: usize = 4_096;
pub const MAX_REPLAY_SELECTION: usize = 256;
pub const MAX_WEIGHT_DELTA_PPM: i32 = 50_000;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EngramPopulationV1 {
    SensoryTrace,
    EpisodicBinding,
    SemanticConcept,
    ProceduralSkill,
    PredictiveWorld,
    UtilitySalience,
    MetaMemory,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SynapseRelationV1 {
    Associative,
    Temporal,
    Causal,
    Procedural,
    Predictive,
    Supports,
    Inhibitory,
    Contradicts,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PlasticityClassV1 {
    Fixed,
    Hebbian,
    EligibilityGated,
    Homeostatic,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EngramNodeV1 {
    pub node_id: ContractIdV1,
    pub population: EngramPopulationV1,
    pub modality_mask: BTreeSet<ModalityKindV1>,
    pub semantic_keys: BTreeSet<String>,
    pub support_manifest_sha256: ContractDigestV1,
    pub threshold_q16: i32,
    pub target_activity_ppm: u32,
    pub confidence_ppm: u32,
    pub snapshot_generation: ContractGenerationV1,
}

impl EngramNodeV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.modality_mask.is_empty() {
            return Err(HnmfContractError::Invalid("engram modality mask"));
        }
        validate_keys(&self.semantic_keys)?;
        ppm(self.target_activity_ppm, "engram target activity")?;
        ppm(self.confidence_ppm, "engram confidence")?;
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SynapseV1 {
    pub source_node_id: ContractIdV1,
    pub target_node_id: ContractIdV1,
    pub relation: SynapseRelationV1,
    pub weight_q16: i32,
    pub delay_steps: u16,
    pub plasticity_class: PlasticityClassV1,
    pub support_manifest_sha256: ContractDigestV1,
    pub snapshot_generation: ContractGenerationV1,
}

impl SynapseV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.source_node_id == self.target_node_id {
            return Err(HnmfContractError::Invalid("synapse self-loop"));
        }
        if self.delay_steps > 4_096 {
            return Err(HnmfContractError::Invalid("synapse delay"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecallResourceBudgetV1 {
    pub maximum_candidate_events: u16,
    pub maximum_nodes: u16,
    pub maximum_synapses: u32,
    pub maximum_active_nodes: u16,
    pub maximum_active_per_population: u16,
    pub maximum_recurrent_steps: u8,
    pub maximum_recall_events: u8,
    pub maximum_activation_paths: u8,
}

impl RecallResourceBudgetV1 {
    pub fn validate(self) -> Result<(), HnmfContractError> {
        let checks = [
            (
                usize::from(self.maximum_candidate_events),
                MAX_CANDIDATE_EVENTS,
                "maximumCandidateEvents",
            ),
            (usize::from(self.maximum_nodes), MAX_NODES, "maximumNodes"),
            (
                usize::try_from(self.maximum_synapses).unwrap_or(usize::MAX),
                MAX_SYNAPSES,
                "maximumSynapses",
            ),
            (
                usize::from(self.maximum_active_nodes),
                MAX_ACTIVE_NODES,
                "maximumActiveNodes",
            ),
            (
                usize::from(self.maximum_active_per_population),
                MAX_ACTIVE_PER_POPULATION,
                "maximumActivePerPopulation",
            ),
            (
                usize::from(self.maximum_recurrent_steps),
                usize::from(MAX_RECURRENT_STEPS),
                "maximumRecurrentSteps",
            ),
            (
                usize::from(self.maximum_recall_events),
                MAX_RECALL_EVENTS,
                "maximumRecallEvents",
            ),
            (
                usize::from(self.maximum_activation_paths),
                MAX_ACTIVATION_PATHS,
                "maximumActivationPaths",
            ),
        ];
        for (actual, maximum, field) in checks {
            if actual == 0 || actual > maximum {
                return Err(HnmfContractError::LimitExceeded {
                    field,
                    actual,
                    maximum,
                });
            }
        }
        Ok(())
    }
}

impl Default for RecallResourceBudgetV1 {
    fn default() -> Self {
        Self {
            maximum_candidate_events: MAX_CANDIDATE_EVENTS as u16,
            maximum_nodes: MAX_NODES as u16,
            maximum_synapses: MAX_SYNAPSES as u32,
            maximum_active_nodes: MAX_ACTIVE_NODES as u16,
            maximum_active_per_population: MAX_ACTIVE_PER_POPULATION as u16,
            maximum_recurrent_steps: MAX_RECURRENT_STEPS,
            maximum_recall_events: MAX_RECALL_EVENTS as u8,
            maximum_activation_paths: MAX_ACTIVATION_PATHS as u8,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryCueV1 {
    pub cue_id: ContractIdV1,
    pub objective_digest: ContractDigestV1,
    pub ndu_state_digest: ContractDigestV1,
    pub modalities: BTreeSet<ModalityKindV1>,
    pub semantic_keys: BTreeSet<String>,
    pub seed_node_ids: BTreeSet<ContractIdV1>,
    pub now_unix_ms: u64,
    pub resource_budget: RecallResourceBudgetV1,
}

impl MemoryCueV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.modalities.is_empty() {
            return Err(HnmfContractError::Invalid("cue modalities"));
        }
        validate_keys(&self.semantic_keys)?;
        if self.seed_node_ids.len() > MAX_CUE_SEEDS {
            return Err(HnmfContractError::LimitExceeded {
                field: "seedNodeIds",
                actual: self.seed_node_ids.len(),
                maximum: MAX_CUE_SEEDS,
            });
        }
        if self.now_unix_ms == 0 {
            return Err(HnmfContractError::ZeroValue("nowUnixMs"));
        }
        self.resource_budget.validate()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SelectedEventRefV1 {
    pub event_id: ContractIdV1,
    pub revision: u64,
    pub event_digest: ContractDigestV1,
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ActiveNodeV1 {
    pub node_id: ContractIdV1,
    pub population: EngramPopulationV1,
    pub activation_ppm: u32,
}

impl ActiveNodeV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        ppm(self.activation_ppm, "active node activation")
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ActivationPathV1 {
    pub source_node_id: ContractIdV1,
    pub target_node_id: ContractIdV1,
    pub relation: SynapseRelationV1,
    pub contribution_ppm: i32,
}

impl ActivationPathV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.source_node_id == self.target_node_id
            || !(-(PPM as i32)..=PPM as i32).contains(&self.contribution_ppm)
        {
            return Err(HnmfContractError::Invalid("activation path"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ContradictionV1 {
    pub left_node_id: ContractIdV1,
    pub right_node_id: ContractIdV1,
}

impl ContradictionV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.left_node_id >= self.right_node_id {
            return Err(HnmfContractError::Invalid("contradiction ordering"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecallAbstainReasonV1 {
    NoCandidate,
    OutOfDistribution,
    LowConfidence,
    UnresolvedContradiction,
    InsufficientCoverage,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecallResourceReceiptV1 {
    pub candidate_event_count: u16,
    pub node_count: u16,
    pub synapse_count: u32,
    pub active_node_count: u16,
    pub settling_steps: u8,
}

impl RecallResourceReceiptV1 {
    fn validate(self) -> Result<(), HnmfContractError> {
        if usize::from(self.candidate_event_count) > MAX_CANDIDATE_EVENTS
            || usize::from(self.node_count) > MAX_NODES
            || usize::try_from(self.synapse_count).unwrap_or(usize::MAX) > MAX_SYNAPSES
            || usize::from(self.active_node_count) > MAX_ACTIVE_NODES
            || self.settling_steps > MAX_RECURRENT_STEPS
        {
            return Err(HnmfContractError::Invalid("recall resource receipt"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecallPacketV1 {
    pub cue_digest: ContractDigestV1,
    pub event_snapshot_digest: ContractDigestV1,
    pub engram_snapshot_digest: ContractDigestV1,
    pub selected_events: Vec<SelectedEventRefV1>,
    pub active_nodes: Vec<ActiveNodeV1>,
    pub activation_paths: Vec<ActivationPathV1>,
    pub contradictions: Vec<ContradictionV1>,
    pub coverage_ppm: u32,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: Option<RecallAbstainReasonV1>,
    pub resource_receipt: RecallResourceReceiptV1,
}

impl RecallPacketV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.selected_events.len() > MAX_RECALL_EVENTS
            || self.active_nodes.len() > MAX_ACTIVE_NODES
            || self.activation_paths.len() > MAX_ACTIVATION_PATHS
        {
            return Err(HnmfContractError::Invalid("recall collection bound"));
        }
        for value in [self.coverage_ppm, self.confidence_ppm, self.ood_ppm] {
            ppm(value, "recall probability")?;
        }
        ensure_strict_order(&self.selected_events, "selectedEvents")?;
        ensure_strict_order(&self.active_nodes, "activeNodes")?;
        ensure_strict_order(&self.activation_paths, "activationPaths")?;
        ensure_strict_order(&self.contradictions, "contradictions")?;
        for node in &self.active_nodes {
            node.validate()?;
        }
        for path in &self.activation_paths {
            path.validate()?;
        }
        for contradiction in &self.contradictions {
            contradiction.validate()?;
        }
        self.resource_receipt.validate()?;
        if self.abstain.is_none() && self.selected_events.is_empty() {
            return Err(HnmfContractError::Invalid("empty non-abstaining recall"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeSignalV1 {
    pub episode_id: ContractIdV1,
    pub utility_delta_ppm: i32,
    pub prediction_error_ppm: u32,
    pub novelty_ppm: u32,
    pub risk_ppm: u32,
    pub ood_ppm: u32,
    pub observer_digest: ContractDigestV1,
}

impl OutcomeSignalV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if !(-(PPM as i32)..=PPM as i32).contains(&self.utility_delta_ppm) {
            return Err(HnmfContractError::Invalid("utility delta"));
        }
        for value in [
            self.prediction_error_ppm,
            self.novelty_ppm,
            self.risk_ppm,
            self.ood_ppm,
        ] {
            ppm(value, "outcome component")?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceBucketCountV1 {
    pub source_bucket: u16,
    pub selected_count: u16,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReplaySelectionReceiptV1 {
    pub candidate_set_digest: ContractDigestV1,
    pub selected_event_ids: Vec<ContractIdV1>,
    pub source_bucket_counts: Vec<SourceBucketCountV1>,
    pub selection_policy_digest: ContractDigestV1,
    pub resource_receipt: ReplayResourceReceiptV1,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReplayResourceReceiptV1 {
    pub candidate_count: u16,
    pub selected_count: u16,
    pub maximum_per_source_bucket: u16,
}

impl ReplaySelectionReceiptV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if usize::from(self.resource_receipt.candidate_count) > MAX_REPLAY_CANDIDATES
            || usize::from(self.resource_receipt.selected_count) > MAX_REPLAY_SELECTION
            || self.selected_event_ids.len() != usize::from(self.resource_receipt.selected_count)
            || self.resource_receipt.maximum_per_source_bucket == 0
            || self.resource_receipt.maximum_per_source_bucket
                > self.resource_receipt.selected_count.max(1)
        {
            return Err(HnmfContractError::Invalid("replay resource receipt"));
        }
        ensure_strict_order(&self.selected_event_ids, "selectedEventIds")?;
        ensure_strict_order(&self.source_bucket_counts, "sourceBucketCounts")?;
        if self
            .source_bucket_counts
            .iter()
            .any(|row| row.selected_count > self.resource_receipt.maximum_per_source_bucket)
        {
            return Err(HnmfContractError::Invalid("replay source quota"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WeightProposalV1 {
    pub source_node_id: ContractIdV1,
    pub target_node_id: ContractIdV1,
    pub relation: SynapseRelationV1,
    pub old_weight_q16: i32,
    pub new_weight_q16: i32,
    pub delta_ppm: i32,
}

impl WeightProposalV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.source_node_id == self.target_node_id
            || i64::from(self.delta_ppm).abs() > i64::from(MAX_WEIGHT_DELTA_PPM)
        {
            return Err(HnmfContractError::Invalid("weight proposal"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ThresholdProposalV1 {
    pub node_id: ContractIdV1,
    pub old_threshold_q16: i32,
    pub new_threshold_q16: i32,
    pub delta_ppm: i32,
}

impl ThresholdProposalV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if i64::from(self.delta_ppm).abs() > i64::from(MAX_WEIGHT_DELTA_PPM) {
            return Err(HnmfContractError::Invalid("threshold proposal"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PlasticityBatchV1 {
    pub predecessor_generation: ContractGenerationV1,
    pub next_generation: ContractGenerationV1,
    pub outcome_signal_digest: ContractDigestV1,
    pub weight_proposals: Vec<WeightProposalV1>,
    pub threshold_proposals: Vec<ThresholdProposalV1>,
    pub current_snapshot_immutable: bool,
    pub production_activation_allowed: bool,
}

impl PlasticityBatchV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.predecessor_generation.next()? != self.next_generation
            || !self.current_snapshot_immutable
            || self.production_activation_allowed
        {
            return Err(HnmfContractError::Conflict(
                "plasticity generation/authority",
            ));
        }
        ensure_strict_order(&self.weight_proposals, "weightProposals")?;
        ensure_strict_order(&self.threshold_proposals, "thresholdProposals")?;
        for proposal in &self.weight_proposals {
            proposal.validate()?;
        }
        for proposal in &self.threshold_proposals {
            proposal.validate()?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum TopologyOperationV1 {
    AddNode {
        label: String,
        population: EngramPopulationV1,
    },
    SplitNode {
        node_id: ContractIdV1,
        left_label: String,
        right_label: String,
    },
    MergeNodes {
        left_node_id: ContractIdV1,
        right_node_id: ContractIdV1,
        label: String,
    },
    RetireNode {
        node_id: ContractIdV1,
        reason: String,
    },
    Rewire {
        source_node_id: ContractIdV1,
        old_target_node_id: ContractIdV1,
        new_target_node_id: ContractIdV1,
        relation: SynapseRelationV1,
    },
}

impl TopologyOperationV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        match self {
            Self::AddNode { label, .. } | Self::MergeNodes { label, .. } => {
                validate_text(label, 128, "topology label")
            }
            Self::SplitNode {
                left_label,
                right_label,
                ..
            } => {
                validate_text(left_label, 128, "split left label")?;
                validate_text(right_label, 128, "split right label")?;
                if left_label == right_label {
                    return Err(HnmfContractError::Invalid("split labels"));
                }
                Ok(())
            }
            Self::RetireNode { reason, .. } => validate_text(reason, 128, "retire reason"),
            Self::Rewire {
                source_node_id,
                old_target_node_id,
                new_target_node_id,
                ..
            } => {
                if source_node_id == old_target_node_id
                    || source_node_id == new_target_node_id
                    || old_target_node_id == new_target_node_id
                {
                    return Err(HnmfContractError::Invalid("rewire endpoints"));
                }
                Ok(())
            }
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TopologyProposalV1 {
    pub predecessor_generation: ContractGenerationV1,
    pub next_generation: ContractGenerationV1,
    pub operation: TopologyOperationV1,
    pub capability_typed: bool,
    pub sandbox_only: bool,
    pub operator_accepted: bool,
    pub production_activation_allowed: bool,
}

impl TopologyProposalV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.predecessor_generation.next()? != self.next_generation
            || !self.capability_typed
            || !self.sandbox_only
            || self.operator_accepted
            || self.production_activation_allowed
        {
            return Err(HnmfContractError::Conflict("topology authority boundary"));
        }
        self.operation.validate()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RetiredSynapseRefV1 {
    pub source_node_id: ContractIdV1,
    pub target_node_id: ContractIdV1,
    pub relation: SynapseRelationV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ForgetPropagationReceiptV1 {
    pub event_id: ContractIdV1,
    pub predecessor_generation: ContractGenerationV1,
    pub next_generation: ContractGenerationV1,
    pub retired_node_ids: Vec<ContractIdV1>,
    pub retired_synapses: Vec<RetiredSynapseRefV1>,
    pub projection_rebuild_required: bool,
    pub artifact_revocation_required: bool,
}

impl ForgetPropagationReceiptV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.predecessor_generation.next()? != self.next_generation
            || !self.projection_rebuild_required
            || !self.artifact_revocation_required
        {
            return Err(HnmfContractError::Conflict("forget propagation"));
        }
        ensure_strict_order(&self.retired_node_ids, "retiredNodeIds")?;
        ensure_strict_order(&self.retired_synapses, "retiredSynapses")
    }
}

fn ensure_strict_order<T: Ord>(
    values: &[T],
    field: &'static str,
) -> Result<(), HnmfContractError> {
    if values.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(HnmfContractError::Invalid(field));
    }
    Ok(())
}

/// A compact table useful to assert exact per-population active-node bounds.
pub fn population_counts_v1(
    nodes: &[ActiveNodeV1],
) -> Result<BTreeMap<EngramPopulationV1, usize>, HnmfContractError> {
    let mut counts = BTreeMap::new();
    for node in nodes {
        node.validate()?;
        let count = counts.entry(node.population).or_insert(0usize);
        *count += 1;
        if *count > MAX_ACTIVE_PER_POPULATION {
            return Err(HnmfContractError::LimitExceeded {
                field: "activeNodesPerPopulation",
                actual: *count,
                maximum: MAX_ACTIVE_PER_POPULATION,
            });
        }
    }
    Ok(counts)
}
