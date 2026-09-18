use serde::Deserialize;
use serde::Serialize;

use super::CanonicalContractV1;
use super::CanonicalDigestV1;
use super::ContractErrorV1;
use super::EngramPopulationV1;
use super::NodeIdV1;
use super::SynapseRelationV1;
use super::validate_nonzero;
use super::validate_signed_ppm;
use super::validate_text;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct WeightProposalV1 {
    source_node_id: NodeIdV1,
    target_node_id: NodeIdV1,
    relation: SynapseRelationV1,
    old_weight_q16: i32,
    new_weight_q16: i32,
    delta_q16: i32,
    new_eligibility_q16: i32,
}

impl WeightProposalV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn try_new(
        source_node_id: NodeIdV1,
        target_node_id: NodeIdV1,
        relation: SynapseRelationV1,
        old_weight_q16: i32,
        new_weight_q16: i32,
        delta_q16: i32,
        new_eligibility_q16: i32,
    ) -> Result<Self, ContractErrorV1> {
        validate_nonzero(source_node_id, "weight proposal source must be non-zero")?;
        validate_nonzero(target_node_id, "weight proposal target must be non-zero")?;
        if source_node_id == target_node_id {
            return Err(ContractErrorV1::Invalid(
                "weight proposal endpoints must be distinct",
            ));
        }
        validate_signed_ppm(old_weight_q16, "old weight")?;
        validate_signed_ppm(new_weight_q16, "new weight")?;
        validate_signed_ppm(delta_q16, "weight delta")?;
        validate_signed_ppm(new_eligibility_q16, "new eligibility")?;
        if new_weight_q16 - old_weight_q16 != delta_q16 {
            return Err(ContractErrorV1::Conflict(
                "weight proposal delta does not match old/new values",
            ));
        }
        Ok(Self {
            source_node_id,
            target_node_id,
            relation,
            old_weight_q16,
            new_weight_q16,
            delta_q16,
            new_eligibility_q16,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
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
    ) -> Result<Self, ContractErrorV1> {
        validate_nonzero(node_id, "threshold proposal node must be non-zero")?;
        validate_signed_ppm(old_threshold_q16, "old threshold")?;
        validate_signed_ppm(new_threshold_q16, "new threshold")?;
        validate_signed_ppm(delta_q16, "threshold delta")?;
        if new_threshold_q16 - old_threshold_q16 != delta_q16 {
            return Err(ContractErrorV1::Conflict(
                "threshold proposal delta does not match old/new values",
            ));
        }
        Ok(Self {
            node_id,
            old_threshold_q16,
            new_threshold_q16,
            delta_q16,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct PlasticityBatchV1 {
    predecessor_generation: u64,
    next_generation: u64,
    outcome_signal_digest: CanonicalDigestV1,
    weight_proposals: Vec<WeightProposalV1>,
    threshold_proposals: Vec<ThresholdProposalV1>,
    current_snapshot_immutable: bool,
    production_activation_allowed: bool,
}

impl PlasticityBatchV1 {
    pub fn try_new(
        predecessor_generation: u64,
        next_generation: u64,
        outcome_signal_digest: CanonicalDigestV1,
        weight_proposals: Vec<WeightProposalV1>,
        threshold_proposals: Vec<ThresholdProposalV1>,
        current_snapshot_immutable: bool,
        production_activation_allowed: bool,
    ) -> Result<Self, ContractErrorV1> {
        let value = Self {
            predecessor_generation,
            next_generation,
            outcome_signal_digest,
            weight_proposals,
            threshold_proposals,
            current_snapshot_immutable,
            production_activation_allowed,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        validate_nonzero(
            self.predecessor_generation,
            "plasticity predecessor generation must be non-zero",
        )?;
        if self.next_generation != self.predecessor_generation.saturating_add(1) {
            return Err(ContractErrorV1::Conflict(
                "plasticity next generation must be exact predecessor + 1",
            ));
        }
        if !self.current_snapshot_immutable || self.production_activation_allowed {
            return Err(ContractErrorV1::AuthorityBoundary);
        }
        Ok(())
    }
}

impl CanonicalContractV1 for PlasticityBatchV1 {
    const SCHEMA_ID: &'static str = "PlasticityBatchV1";
    const MAX_ENCODED_BYTES: usize = 262_144;

    fn validate_contract(&self) -> Result<(), ContractErrorV1> {
        self.validate()
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum TopologyOperationV1 {
    AddNode {
        label: String,
        population: EngramPopulationV1,
    },
    SplitNode {
        node_id: NodeIdV1,
        labels: [String; 2],
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
    fn validate(&self) -> Result<(), ContractErrorV1> {
        match self {
            Self::AddNode { label, .. } => validate_text(label, 128, "topology label"),
            Self::SplitNode { node_id, labels } => {
                validate_nonzero(*node_id, "split node id must be non-zero")?;
                validate_text(&labels[0], 128, "split label")?;
                validate_text(&labels[1], 128, "split label")?;
                if labels[0] == labels[1] {
                    return Err(ContractErrorV1::Conflict("split labels must be distinct"));
                }
                Ok(())
            }
            Self::MergeNodes {
                left_node_id,
                right_node_id,
                label,
            } => {
                validate_nonzero(*left_node_id, "merge left node must be non-zero")?;
                validate_nonzero(*right_node_id, "merge right node must be non-zero")?;
                if left_node_id == right_node_id {
                    return Err(ContractErrorV1::Invalid("merge nodes must be distinct"));
                }
                validate_text(label, 128, "topology label")
            }
            Self::RetireNode { node_id, reason } => {
                validate_nonzero(*node_id, "retire node id must be non-zero")?;
                validate_text(reason, 128, "retire reason")
            }
            Self::Rewire {
                source_node_id,
                old_target_node_id,
                new_target_node_id,
                ..
            } => {
                for value in [source_node_id, old_target_node_id, new_target_node_id] {
                    validate_nonzero(*value, "rewire endpoint must be non-zero")?;
                }
                if source_node_id == old_target_node_id
                    || source_node_id == new_target_node_id
                    || old_target_node_id == new_target_node_id
                {
                    return Err(ContractErrorV1::Invalid("rewire endpoints are invalid"));
                }
                Ok(())
            }
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
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
        capability_typed: bool,
        sandbox_only: bool,
        operator_accepted: bool,
        production_activation_allowed: bool,
    ) -> Result<Self, ContractErrorV1> {
        let value = Self {
            predecessor_generation,
            next_generation,
            operation,
            capability_typed,
            sandbox_only,
            operator_accepted,
            production_activation_allowed,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        validate_nonzero(
            self.predecessor_generation,
            "topology predecessor generation must be non-zero",
        )?;
        if self.next_generation != self.predecessor_generation.saturating_add(1)
            || !self.capability_typed
            || !self.sandbox_only
            || self.operator_accepted
            || self.production_activation_allowed
        {
            return Err(ContractErrorV1::AuthorityBoundary);
        }
        self.operation.validate()
    }
}

impl CanonicalContractV1 for TopologyProposalV1 {
    const SCHEMA_ID: &'static str = "TopologyProposalV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate_contract(&self) -> Result<(), ContractErrorV1> {
        self.validate()
    }
}
