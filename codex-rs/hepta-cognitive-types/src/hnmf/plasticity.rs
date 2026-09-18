use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::CanonicalJsonV1;
use super::EngramPopulationV1;
use super::HnmfContractError;
use super::MAX_THRESHOLD_PROPOSALS;
use super::MAX_WEIGHT_PROPOSALS;
use super::NodeIdV1;
use super::SynapseRelationV1;
use super::ValidateHnmfV1;
use super::q16_unit;
use super::validate_text;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WeightProposalV1 {
    source_node_id: NodeIdV1,
    target_node_id: NodeIdV1,
    relation: SynapseRelationV1,
    old_weight_q16: i32,
    new_weight_q16: i32,
    delta_q16: i32,
}

impl WeightProposalV1 {
    pub fn try_new(
        source_node_id: NodeIdV1,
        target_node_id: NodeIdV1,
        relation: SynapseRelationV1,
        old_weight_q16: i32,
        new_weight_q16: i32,
        delta_q16: i32,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            source_node_id,
            target_node_id,
            relation,
            old_weight_q16,
            new_weight_q16,
            delta_q16,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for WeightProposalV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.source_node_id == 0
            || self.target_node_id == 0
            || self.source_node_id == self.target_node_id
        {
            return Err(HnmfContractError::Invalid("weight proposal endpoints"));
        }
        q16_unit(self.old_weight_q16, "old weight")?;
        q16_unit(self.new_weight_q16, "new weight")?;
        q16_unit(self.delta_q16, "weight delta")?;
        if i64::from(self.new_weight_q16) - i64::from(self.old_weight_q16)
            != i64::from(self.delta_q16)
        {
            return Err(HnmfContractError::Conflict("weight proposal delta"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ThresholdProposalV1 {
    node_id: NodeIdV1,
    old_threshold_q16: i32,
    new_threshold_q16: i32,
    delta_q16: i32,
}

impl ThresholdProposalV1 {
    pub fn try_new(
        node_id: NodeIdV1,
        old_threshold_q16: i32,
        new_threshold_q16: i32,
        delta_q16: i32,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            node_id,
            old_threshold_q16,
            new_threshold_q16,
            delta_q16,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for ThresholdProposalV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.node_id == 0 {
            return Err(HnmfContractError::Invalid("threshold proposal node id"));
        }
        q16_unit(self.old_threshold_q16, "old threshold")?;
        q16_unit(self.new_threshold_q16, "new threshold")?;
        q16_unit(self.delta_q16, "threshold delta")?;
        if i64::from(self.new_threshold_q16) - i64::from(self.old_threshold_q16)
            != i64::from(self.delta_q16)
        {
            return Err(HnmfContractError::Conflict("threshold proposal delta"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PlasticityBatchV1 {
    predecessor_generation: u64,
    next_generation: u64,
    #[serde(with = "super::wire::digest")]
    outcome_signal_digest: Digest32,
    weight_proposals: Vec<WeightProposalV1>,
    threshold_proposals: Vec<ThresholdProposalV1>,
    current_snapshot_immutable: bool,
    production_activation_allowed: bool,
}

impl PlasticityBatchV1 {
    pub fn try_new(
        predecessor_generation: u64,
        next_generation: u64,
        outcome_signal_digest: Digest32,
        weight_proposals: Vec<WeightProposalV1>,
        threshold_proposals: Vec<ThresholdProposalV1>,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            predecessor_generation,
            next_generation,
            outcome_signal_digest,
            weight_proposals,
            threshold_proposals,
            current_snapshot_immutable: true,
            production_activation_allowed: false,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for PlasticityBatchV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.predecessor_generation == 0
            || self.predecessor_generation.checked_add(1) != Some(self.next_generation)
        {
            return Err(HnmfContractError::Conflict("plasticity generation chain"));
        }
        if self.outcome_signal_digest.is_zero() {
            return Err(HnmfContractError::Invalid("outcome signal digest"));
        }
        if !self.current_snapshot_immutable || self.production_activation_allowed {
            return Err(HnmfContractError::Conflict("plasticity authority boundary"));
        }
        if self.weight_proposals.len() > MAX_WEIGHT_PROPOSALS
            || self.threshold_proposals.len() > MAX_THRESHOLD_PROPOSALS
        {
            return Err(HnmfContractError::BoundExceeded("plasticity proposals"));
        }
        for proposal in &self.weight_proposals {
            proposal.validate()?;
        }
        for proposal in &self.threshold_proposals {
            proposal.validate()?;
        }
        Ok(())
    }
}

impl CanonicalJsonV1 for PlasticityBatchV1 {
    const SCHEMA_ID: &'static str = "hepta.hnmf.plasticity-batch.v1";
    const MAX_ENCODED_BYTES: usize = 262_144;
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(\n    tag = "kind",\n    rename_all = "snake_case",\n    rename_all_fields = "camelCase",\n    deny_unknown_fields\n)]
pub enum TopologyOperationV1 {
    AddNode {
        label: String,
        population: EngramPopulationV1,
    },
    SplitNode {
        node_id: NodeIdV1,
        left_label: String,
        right_label: String,
    },
    MergeNodes {
        left_node_id: NodeIdV1,
        right_node_id: NodeIdV1,
        label: String,
    },
    RetireNode {
        node_id: NodeIdV1,
        reason: String,
    },
    Rewire {
        source_node_id: NodeIdV1,
        old_target_node_id: NodeIdV1,
        new_target_node_id: NodeIdV1,
        relation: SynapseRelationV1,
    },
}

impl TopologyOperationV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        match self {
            Self::AddNode { label, .. } => validate_text(label, 128, "topology label"),
            Self::SplitNode {
                node_id,
                left_label,
                right_label,
            } => {
                if *node_id == 0 || left_label == right_label {
                    return Err(HnmfContractError::Invalid("split node operation"));
                }
                validate_text(left_label, 128, "split label")?;
                validate_text(right_label, 128, "split label")
            }
            Self::MergeNodes {
                left_node_id,
                right_node_id,
                label,
            } => {
                if *left_node_id == 0 || *right_node_id == 0 || left_node_id == right_node_id {
                    return Err(HnmfContractError::Invalid("merge node operation"));
                }
                validate_text(label, 128, "merge label")
            }
            Self::RetireNode { node_id, reason } => {
                if *node_id == 0 {
                    return Err(HnmfContractError::Invalid("retire node id"));
                }
                validate_text(reason, 128, "retire reason")
            }
            Self::Rewire {
                source_node_id,
                old_target_node_id,
                new_target_node_id,
                ..
            } => {
                if *source_node_id == 0
                    || *old_target_node_id == 0
                    || *new_target_node_id == 0
                    || source_node_id == old_target_node_id
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
    predecessor_generation: u64,
    next_generation: u64,
    operation: TopologyOperationV1,
    capability_typed: bool,
    sandbox_only: bool,
    operator_accepted: bool,
    production_activation_allowed: bool,
}

impl TopologyProposalV1 {
    pub fn try_new(
        predecessor_generation: u64,
        next_generation: u64,
        operation: TopologyOperationV1,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            predecessor_generation,
            next_generation,
            operation,
            capability_typed: true,
            sandbox_only: true,
            operator_accepted: false,
            production_activation_allowed: false,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for TopologyProposalV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.predecessor_generation == 0
            || self.predecessor_generation.checked_add(1) != Some(self.next_generation)
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

impl CanonicalJsonV1 for TopologyProposalV1 {
    const SCHEMA_ID: &'static str = "hepta.hnmf.topology-proposal.v1";
    const MAX_ENCODED_BYTES: usize = 65_536;
}
