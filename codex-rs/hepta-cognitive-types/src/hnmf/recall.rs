use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use super::CanonicalContractV1;
use super::CanonicalDigestV1;
use super::ContractErrorV1;
use super::EngramPopulationV1;
use super::EventIdV1;
use super::ModalityKindV1;
use super::NodeIdV1;
use super::SynapseRelationV1;
use super::validate_nonzero;
use super::validate_ppm;
use super::validate_semantic_keys;
use super::validate_signed_ppm;
use super::MAX_CUE_SEEDS;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ResourceBudgetV1 {
    maximum_candidate_events: u32,
    maximum_nodes: u32,
    maximum_synapses: u32,
    maximum_active_nodes: u32,
    maximum_active_per_population: u32,
    maximum_recurrent_steps: u8,
    maximum_recall_events: u32,
    maximum_activation_paths: u32,
}

impl ResourceBudgetV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        maximum_candidate_events: u32,
        maximum_nodes: u32,
        maximum_synapses: u32,
        maximum_active_nodes: u32,
        maximum_active_per_population: u32,
        maximum_recurrent_steps: u8,
        maximum_recall_events: u32,
        maximum_activation_paths: u32,
    ) -> Result<Self, ContractErrorV1> {
        let value = Self {
            maximum_candidate_events,
            maximum_nodes,
            maximum_synapses,
            maximum_active_nodes,
            maximum_active_per_population,
            maximum_recurrent_steps,
            maximum_recall_events,
            maximum_activation_paths,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn hnmf_default() -> Self {
        Self {
            maximum_candidate_events: 512,
            maximum_nodes: 4096,
            maximum_synapses: 32_768,
            maximum_active_nodes: 4096,
            maximum_active_per_population: 64,
            maximum_recurrent_steps: 4,
            maximum_recall_events: 16,
            maximum_activation_paths: 32,
        }
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        if self.maximum_candidate_events == 0
            || self.maximum_candidate_events > 512
            || self.maximum_nodes == 0
            || self.maximum_nodes > 4096
            || self.maximum_synapses == 0
            || self.maximum_synapses > 32_768
            || self.maximum_active_nodes == 0
            || self.maximum_active_nodes > self.maximum_nodes
            || self.maximum_active_per_population == 0
            || self.maximum_active_per_population > 64
            || self.maximum_recurrent_steps == 0
            || self.maximum_recurrent_steps > 4
            || self.maximum_recall_events == 0
            || self.maximum_recall_events > 16
            || self.maximum_activation_paths == 0
            || self.maximum_activation_paths > 32
        {
            return Err(ContractErrorV1::BoundExceeded("resource budget"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ResourceReceiptV1 {
    candidate_events: u32,
    expanded_nodes: u32,
    traversed_synapses: u32,
    active_nodes: u32,
    recurrent_steps: u8,
    returned_events: u32,
    activation_paths: u32,
    truncated: bool,
}

impl ResourceReceiptV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        candidate_events: u32,
        expanded_nodes: u32,
        traversed_synapses: u32,
        active_nodes: u32,
        recurrent_steps: u8,
        returned_events: u32,
        activation_paths: u32,
        truncated: bool,
        budget: &ResourceBudgetV1,
    ) -> Result<Self, ContractErrorV1> {
        budget.validate()?;
        if candidate_events > budget.maximum_candidate_events
            || expanded_nodes > budget.maximum_nodes
            || traversed_synapses > budget.maximum_synapses
            || active_nodes > budget.maximum_active_nodes
            || recurrent_steps > budget.maximum_recurrent_steps
            || returned_events > budget.maximum_recall_events
            || activation_paths > budget.maximum_activation_paths
        {
            return Err(ContractErrorV1::BoundExceeded("resource receipt"));
        }
        Ok(Self {
            candidate_events,
            expanded_nodes,
            traversed_synapses,
            active_nodes,
            recurrent_steps,
            returned_events,
            activation_paths,
            truncated,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct MemoryCueV1 {
    cue_id: u64,
    objective_digest: CanonicalDigestV1,
    ndu_state_digest: CanonicalDigestV1,
    modalities: BTreeSet<ModalityKindV1>,
    semantic_keys: BTreeSet<String>,
    seed_node_ids: BTreeSet<NodeIdV1>,
    now_unix_ms: i64,
    resource_budget: ResourceBudgetV1,
}

impl MemoryCueV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        cue_id: u64,
        objective_digest: CanonicalDigestV1,
        ndu_state_digest: CanonicalDigestV1,
        modalities: BTreeSet<ModalityKindV1>,
        semantic_keys: BTreeSet<String>,
        seed_node_ids: BTreeSet<NodeIdV1>,
        now_unix_ms: i64,
        resource_budget: ResourceBudgetV1,
    ) -> Result<Self, ContractErrorV1> {
        let value = Self {
            cue_id,
            objective_digest,
            ndu_state_digest,
            modalities,
            semantic_keys,
            seed_node_ids,
            now_unix_ms,
            resource_budget,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        validate_nonzero(self.cue_id, "cue id must be non-zero")?;
        if self.modalities.is_empty() || self.modalities.len() > ModalityKindV1::ALL.len() {
            return Err(ContractErrorV1::BoundExceeded("cue modalities"));
        }
        validate_semantic_keys(&self.semantic_keys)?;
        if self.seed_node_ids.len() > MAX_CUE_SEEDS || self.seed_node_ids.contains(&0) {
            return Err(ContractErrorV1::BoundExceeded("cue seed nodes"));
        }
        self.resource_budget.validate()
    }
}

impl CanonicalContractV1 for MemoryCueV1 {
    const SCHEMA_ID: &'static str = "MemoryCueV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate_contract(&self) -> Result<(), ContractErrorV1> {
        self.validate()
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ActiveNodeV1 {
    node_id: NodeIdV1,
    population: EngramPopulationV1,
    activation_ppm: i32,
}

impl ActiveNodeV1 {
    pub fn try_new(
        node_id: NodeIdV1,
        population: EngramPopulationV1,
        activation_ppm: i32,
    ) -> Result<Self, ContractErrorV1> {
        validate_nonzero(node_id, "active node id must be non-zero")?;
        validate_signed_ppm(activation_ppm, "active node activation")?;
        Ok(Self {
            node_id,
            population,
            activation_ppm,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ActivationPathV1 {
    source_node_id: NodeIdV1,
    target_node_id: NodeIdV1,
    relation: SynapseRelationV1,
    contribution_ppm: i32,
}

impl ActivationPathV1 {
    pub fn try_new(
        source_node_id: NodeIdV1,
        target_node_id: NodeIdV1,
        relation: SynapseRelationV1,
        contribution_ppm: i32,
    ) -> Result<Self, ContractErrorV1> {
        validate_nonzero(source_node_id, "activation path source must be non-zero")?;
        validate_nonzero(target_node_id, "activation path target must be non-zero")?;
        if source_node_id == target_node_id {
            return Err(ContractErrorV1::Invalid("activation path endpoints must be distinct"));
        }
        validate_signed_ppm(contribution_ppm, "activation contribution")?;
        Ok(Self {
            source_node_id,
            target_node_id,
            relation,
            contribution_ppm,
        })
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ContradictionV1 {
    left_node_id: NodeIdV1,
    right_node_id: NodeIdV1,
}

impl ContradictionV1 {
    pub fn try_new(left_node_id: NodeIdV1, right_node_id: NodeIdV1) -> Result<Self, ContractErrorV1> {
        validate_nonzero(left_node_id, "contradiction left node must be non-zero")?;
        validate_nonzero(right_node_id, "contradiction right node must be non-zero")?;
        if left_node_id == right_node_id {
            return Err(ContractErrorV1::Invalid("contradiction endpoints must be distinct"));
        }
        Ok(Self {
            left_node_id,
            right_node_id,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecallAbstainReasonV1 {
    NoCandidate,
    OutOfDistribution,
    LowConfidence,
    UnresolvedContradiction,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct RecallPacketV1 {
    cue_digest: CanonicalDigestV1,
    event_snapshot_digest: CanonicalDigestV1,
    engram_snapshot_digest: CanonicalDigestV1,
    selected_events: Vec<EventIdV1>,
    active_nodes: Vec<ActiveNodeV1>,
    activation_paths: Vec<ActivationPathV1>,
    contradictions: Vec<ContradictionV1>,
    coverage_ppm: u32,
    confidence_ppm: u32,
    ood_ppm: u32,
    abstain: Option<RecallAbstainReasonV1>,
    resource_receipt: ResourceReceiptV1,
}

impl RecallPacketV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        cue_digest: CanonicalDigestV1,
        event_snapshot_digest: CanonicalDigestV1,
        engram_snapshot_digest: CanonicalDigestV1,
        selected_events: Vec<EventIdV1>,
        active_nodes: Vec<ActiveNodeV1>,
        activation_paths: Vec<ActivationPathV1>,
        contradictions: Vec<ContradictionV1>,
        coverage_ppm: u32,
        confidence_ppm: u32,
        ood_ppm: u32,
        abstain: Option<RecallAbstainReasonV1>,
        resource_receipt: ResourceReceiptV1,
    ) -> Result<Self, ContractErrorV1> {
        if selected_events.len() > 16 || selected_events.contains(&0) {
            return Err(ContractErrorV1::BoundExceeded("recall selected events"));
        }
        if active_nodes.len() > 4096 {
            return Err(ContractErrorV1::BoundExceeded("recall active nodes"));
        }
        if activation_paths.len() > 32 {
            return Err(ContractErrorV1::BoundExceeded("recall activation paths"));
        }
        validate_ppm(coverage_ppm, "recall coverage")?;
        validate_ppm(confidence_ppm, "recall confidence")?;
        validate_ppm(ood_ppm, "recall ood")?;
        let mut seen = BTreeSet::new();
        if selected_events.iter().any(|event_id| !seen.insert(*event_id)) {
            return Err(ContractErrorV1::Conflict("duplicate selected event"));
        }
        if !contradictions.is_empty() && abstain.is_none() {
            return Err(ContractErrorV1::Conflict(
                "unresolved contradiction requires abstention",
            ));
        }
        Ok(Self {
            cue_digest,
            event_snapshot_digest,
            engram_snapshot_digest,
            selected_events,
            active_nodes,
            activation_paths,
            contradictions,
            coverage_ppm,
            confidence_ppm,
            ood_ppm,
            abstain,
            resource_receipt,
        })
    }
}

impl CanonicalContractV1 for RecallPacketV1 {
    const SCHEMA_ID: &'static str = "RecallPacketV1";
    const MAX_ENCODED_BYTES: usize = 262_144;

    fn validate_contract(&self) -> Result<(), ContractErrorV1> {
        validate_ppm(self.coverage_ppm, "recall coverage")?;
        validate_ppm(self.confidence_ppm, "recall confidence")?;
        validate_ppm(self.ood_ppm, "recall ood")?;
        if !self.contradictions.is_empty() && self.abstain.is_none() {
            return Err(ContractErrorV1::Conflict(
                "unresolved contradiction requires abstention",
            ));
        }
        Ok(())
    }
}
