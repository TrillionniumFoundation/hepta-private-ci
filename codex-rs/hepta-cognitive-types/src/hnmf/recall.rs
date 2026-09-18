use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::CanonicalJsonV1;
use super::CueIdV1;
use super::EngramPopulationV1;
use super::EventIdV1;
use super::HnmfContractError;
use super::MAX_ACTIVATION_PATHS;
use super::MAX_CUE_SEEDS;
use super::MAX_RECALL_EVENTS;
use super::MAX_SEMANTIC_KEYS;
use super::ModalityKindV1;
use super::NodeIdV1;
use super::SynapseRelationV1;
use super::ValidateHnmfV1;
use super::ppm;
use super::signed_ppm;
use super::validate_keys;

pub const MAX_CANDIDATE_EVENTS: u32 = 512;
pub const MAX_ENGRAM_NODES: u32 = 4_096;
pub const MAX_ENGRAM_SYNAPSES: u32 = 32_768;
pub const MAX_RECURRENT_STEPS: u8 = 4;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ResourceBudgetV1 {
    maximum_candidate_events: u32,
    maximum_nodes: u32,
    maximum_synapses: u32,
    maximum_recurrent_steps: u8,
    maximum_recall_events: u16,
    maximum_activation_paths: u16,
}

impl ResourceBudgetV1 {
    pub fn try_new(
        maximum_candidate_events: u32,
        maximum_nodes: u32,
        maximum_synapses: u32,
        maximum_recurrent_steps: u8,
        maximum_recall_events: u16,
        maximum_activation_paths: u16,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            maximum_candidate_events,
            maximum_nodes,
            maximum_synapses,
            maximum_recurrent_steps,
            maximum_recall_events,
            maximum_activation_paths,
        };
        value.validate()?;
        Ok(value)
    }
}

impl Default for ResourceBudgetV1 {
    fn default() -> Self {
        Self {
            maximum_candidate_events: MAX_CANDIDATE_EVENTS,
            maximum_nodes: MAX_ENGRAM_NODES,
            maximum_synapses: MAX_ENGRAM_SYNAPSES,
            maximum_recurrent_steps: MAX_RECURRENT_STEPS,
            maximum_recall_events: MAX_RECALL_EVENTS as u16,
            maximum_activation_paths: MAX_ACTIVATION_PATHS as u16,
        }
    }
}

impl ValidateHnmfV1 for ResourceBudgetV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.maximum_candidate_events == 0
            || self.maximum_candidate_events > MAX_CANDIDATE_EVENTS
            || self.maximum_nodes == 0
            || self.maximum_nodes > MAX_ENGRAM_NODES
            || self.maximum_synapses == 0
            || self.maximum_synapses > MAX_ENGRAM_SYNAPSES
            || self.maximum_recurrent_steps == 0
            || self.maximum_recurrent_steps > MAX_RECURRENT_STEPS
            || self.maximum_recall_events == 0
            || usize::from(self.maximum_recall_events) > MAX_RECALL_EVENTS
            || self.maximum_activation_paths == 0
            || usize::from(self.maximum_activation_paths) > MAX_ACTIVATION_PATHS
        {
            return Err(HnmfContractError::BoundExceeded("recall resource budget"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryCueV1 {
    cue_id: CueIdV1,
    #[serde(with = "super::wire::digest")]
    objective_digest: Digest32,
    #[serde(with = "super::wire::digest")]
    ndu_state_digest: Digest32,
    modalities: BTreeSet<ModalityKindV1>,
    semantic_keys: BTreeSet<String>,
    seed_node_ids: BTreeSet<NodeIdV1>,
    now_unix_ms: i64,
    resource_budget: ResourceBudgetV1,
}

impl MemoryCueV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        cue_id: CueIdV1,
        objective_digest: Digest32,
        ndu_state_digest: Digest32,
        modalities: BTreeSet<ModalityKindV1>,
        semantic_keys: BTreeSet<String>,
        seed_node_ids: BTreeSet<NodeIdV1>,
        now_unix_ms: i64,
        resource_budget: ResourceBudgetV1,
    ) -> Result<Self, HnmfContractError> {
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
}

impl ValidateHnmfV1 for MemoryCueV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.cue_id == 0 || self.objective_digest.is_zero() || self.ndu_state_digest.is_zero() {
            return Err(HnmfContractError::Invalid(
                "cue identity and objective/NDU digests must be non-zero",
            ));
        }
        if self.modalities.is_empty() || self.modalities.len() > ModalityKindV1::ALL.len() {
            return Err(HnmfContractError::BoundExceeded("cue modalities"));
        }
        validate_keys(&self.semantic_keys, MAX_SEMANTIC_KEYS, "cue semantic keys")?;
        if self.seed_node_ids.len() > MAX_CUE_SEEDS || self.seed_node_ids.contains(&0) {
            return Err(HnmfContractError::BoundExceeded("cue seed nodes"));
        }
        self.resource_budget.validate()
    }
}

impl CanonicalJsonV1 for MemoryCueV1 {
    const SCHEMA_ID: &'static str = "hepta.hnmf.memory-cue.v1";
    const MAX_ENCODED_BYTES: usize = 65_536;
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SelectedEventV1 {
    event_id: EventIdV1,
    revision: u64,
    #[serde(with = "super::wire::digest")]
    event_digest: Digest32,
}

impl SelectedEventV1 {
    pub fn try_new(
        event_id: EventIdV1,
        revision: u64,
        event_digest: Digest32,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            event_id,
            revision,
            event_digest,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for SelectedEventV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.event_id == 0 || self.revision == 0 || self.event_digest.is_zero() {
            return Err(HnmfContractError::Invalid("selected event identity"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ActiveNodeSummaryV1 {
    node_id: NodeIdV1,
    population: EngramPopulationV1,
    activation_ppm: i32,
}

impl ActiveNodeSummaryV1 {
    pub fn try_new(
        node_id: NodeIdV1,
        population: EngramPopulationV1,
        activation_ppm: i32,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            node_id,
            population,
            activation_ppm,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for ActiveNodeSummaryV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.node_id == 0 {
            return Err(HnmfContractError::Invalid("active node id"));
        }
        signed_ppm(self.activation_ppm, "active node activation")
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
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
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            source_node_id,
            target_node_id,
            relation,
            contribution_ppm,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for ActivationPathV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.source_node_id == 0
            || self.target_node_id == 0
            || self.source_node_id == self.target_node_id
        {
            return Err(HnmfContractError::Invalid("activation path endpoints"));
        }
        signed_ppm(self.contribution_ppm, "activation path contribution")
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ContradictionV1 {
    left_node_id: NodeIdV1,
    right_node_id: NodeIdV1,
}

impl ContradictionV1 {
    pub fn try_new(
        left_node_id: NodeIdV1,
        right_node_id: NodeIdV1,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            left_node_id,
            right_node_id,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for ContradictionV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.left_node_id == 0
            || self.right_node_id == 0
            || self.left_node_id == self.right_node_id
        {
            return Err(HnmfContractError::Invalid("contradiction endpoints"));
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
    StaleSnapshot,
    RevokedSupport,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ResourceReceiptV1 {
    candidate_events_examined: u32,
    nodes_expanded: u32,
    synapses_traversed: u32,
    settling_steps: u8,
}

impl ResourceReceiptV1 {
    pub fn try_new(
        candidate_events_examined: u32,
        nodes_expanded: u32,
        synapses_traversed: u32,
        settling_steps: u8,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            candidate_events_examined,
            nodes_expanded,
            synapses_traversed,
            settling_steps,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for ResourceReceiptV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.candidate_events_examined > MAX_CANDIDATE_EVENTS
            || self.nodes_expanded > MAX_ENGRAM_NODES
            || self.synapses_traversed > MAX_ENGRAM_SYNAPSES
            || self.settling_steps > MAX_RECURRENT_STEPS
        {
            return Err(HnmfContractError::BoundExceeded("recall resource receipt"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecallPacketV1 {
    #[serde(with = "super::wire::digest")]
    cue_digest: Digest32,
    #[serde(with = "super::wire::digest")]
    event_snapshot_digest: Digest32,
    #[serde(with = "super::wire::digest")]
    engram_snapshot_digest: Digest32,
    selected_events: Vec<SelectedEventV1>,
    active_nodes: Vec<ActiveNodeSummaryV1>,
    activation_paths: Vec<ActivationPathV1>,
    contradictions: Vec<ContradictionV1>,
    coverage_ppm: u32,
    confidence_ppm: u32,
    ood_ppm: u32,
    abstain: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    abstain_reason: Option<RecallAbstainReasonV1>,
    resource_receipt: ResourceReceiptV1,
}

impl RecallPacketV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        cue_digest: Digest32,
        event_snapshot_digest: Digest32,
        engram_snapshot_digest: Digest32,
        selected_events: Vec<SelectedEventV1>,
        active_nodes: Vec<ActiveNodeSummaryV1>,
        activation_paths: Vec<ActivationPathV1>,
        contradictions: Vec<ContradictionV1>,
        coverage_ppm: u32,
        confidence_ppm: u32,
        ood_ppm: u32,
        abstain: bool,
        abstain_reason: Option<RecallAbstainReasonV1>,
        resource_receipt: ResourceReceiptV1,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
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
            abstain_reason,
            resource_receipt,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for RecallPacketV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        for digest in [
            self.cue_digest,
            self.event_snapshot_digest,
            self.engram_snapshot_digest,
        ] {
            if digest.is_zero() {
                return Err(HnmfContractError::Invalid("recall packet digest"));
            }
        }
        if self.selected_events.len() > MAX_RECALL_EVENTS
            || self.activation_paths.len() > MAX_ACTIVATION_PATHS
            || self.active_nodes.len() > MAX_ENGRAM_NODES as usize
        {
            return Err(HnmfContractError::BoundExceeded("recall packet collection"));
        }
        if self.abstain != self.abstain_reason.is_some() {
            return Err(HnmfContractError::Conflict("recall abstention state"));
        }
        for event in &self.selected_events {
            event.validate()?;
        }
        let mut node_ids = BTreeSet::new();
        for node in &self.active_nodes {
            node.validate()?;
            if !node_ids.insert(node.node_id) {
                return Err(HnmfContractError::Conflict("duplicate active node"));
            }
        }
        for path in &self.activation_paths {
            path.validate()?;
        }
        let mut contradictions = BTreeSet::new();
        for contradiction in &self.contradictions {
            contradiction.validate()?;
            if !contradictions.insert(contradiction.clone()) {
                return Err(HnmfContractError::Conflict("duplicate contradiction"));
            }
        }
        ppm(self.coverage_ppm, "recall coverage")?;
        ppm(self.confidence_ppm, "recall confidence")?;
        ppm(self.ood_ppm, "recall OOD")?;
        self.resource_receipt.validate()
    }
}

impl CanonicalJsonV1 for RecallPacketV1 {
    const SCHEMA_ID: &'static str = "hepta.hnmf.recall-packet.v1";
    const MAX_ENCODED_BYTES: usize = 262_144;
}
