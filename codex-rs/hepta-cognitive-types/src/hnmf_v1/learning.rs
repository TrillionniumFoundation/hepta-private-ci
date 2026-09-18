use super::*;
use std::collections::BTreeMap;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeSignalV1 {
    #[serde(with = "super::exact_u64")]
    pub episode_id: EpisodeIdV1,
    pub utility_delta_ppm: i32,
    pub prediction_error_ppm: u32,
    pub novelty_ppm: u32,
    pub risk_ppm: u32,
    pub ood_ppm: u32,
    pub observer_digest: Sha256DigestV1,
    pub authority: AuthorityPostureV1,
}

impl CanonicalJsonV1 for OutcomeSignalV1 {
    const SCHEMA_ID: &'static str = "OutcomeSignalV1";
    const MAX_ENCODED_BYTES: usize = 32_768;

    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.episode_id == 0 || !(-1_000_000..=1_000_000).contains(&self.utility_delta_ppm) {
            return Err(HnmfContractError::Invalid("outcome identity/utility is invalid"));
        }
        for (name, value) in [
            ("prediction error", self.prediction_error_ppm),
            ("novelty", self.novelty_ppm),
            ("risk", self.risk_ppm),
            ("OOD", self.ood_ppm),
        ] {
            ppm(value, name)?;
        }
        self.authority.validate()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReplaySelectionReceiptV1 {
    pub candidate_set_digest: Sha256DigestV1,
    #[serde(with = "super::exact_u64_vec")]
    pub selected_event_ids: Vec<EventIdV1>,
    pub source_bucket_counts: BTreeMap<String, u32>,
    pub selection_policy_digest: Sha256DigestV1,
    pub resource_receipt: ResourceReceiptV1,
    pub authority: AuthorityPostureV1,
}

impl CanonicalJsonV1 for ReplaySelectionReceiptV1 {
    const SCHEMA_ID: &'static str = "ReplaySelectionReceiptV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate(&self) -> Result<(), HnmfContractError> {
        validate_sorted_unique_u64_bounded(&self.selected_event_ids, MAX_REPLAY_SELECTION, "replay selection")?;
        if self.source_bucket_counts.len() > MAX_REPLAY_SELECTION {
            return Err(HnmfContractError::BoundExceeded("source bucket counts"));
        }
        for key in self.source_bucket_counts.keys() {
            validate_text(key, 128, "source bucket")?;
        }
        self.resource_receipt.validate()?;
        self.authority.validate()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WeightProposalV1 {
    #[serde(with = "super::exact_u64")]
    pub source_node_id: NodeIdV1,
    #[serde(with = "super::exact_u64")]
    pub target_node_id: NodeIdV1,
    pub relation: SynapseRelationV1,
    pub old_weight_q16: i32,
    pub new_weight_q16: i32,
    pub delta_ppm: i32,
    pub new_eligibility_ppm: i32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ThresholdProposalV1 {
    #[serde(with = "super::exact_u64")]
    pub node_id: NodeIdV1,
    pub old_threshold_q16: i32,
    pub new_threshold_q16: i32,
    pub delta_ppm: i32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PlasticityBatchV1 {
    #[serde(with = "super::exact_u64")]
    pub predecessor_generation: u64,
    #[serde(with = "super::exact_u64")]
    pub next_generation: u64,
    pub outcome_signal_digest: Sha256DigestV1,
    pub weight_proposals: Vec<WeightProposalV1>,
    pub threshold_proposals: Vec<ThresholdProposalV1>,
    pub current_snapshot_immutable: bool,
    pub production_activation_allowed: bool,
    pub authority: AuthorityPostureV1,
}

impl CanonicalJsonV1 for PlasticityBatchV1 {
    const SCHEMA_ID: &'static str = "PlasticityBatchV1";
    const MAX_ENCODED_BYTES: usize = 262_144;

    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.predecessor_generation == 0
            || self.next_generation != self.predecessor_generation.checked_add(1).ok_or(HnmfContractError::Invalid("plasticity generation overflow"))?
            || !self.current_snapshot_immutable
            || self.production_activation_allowed
        {
            return Err(HnmfContractError::Invalid("plasticity generation/authority state is invalid"));
        }
        if self.weight_proposals.len() > MAX_WEIGHT_PROPOSALS
            || self.threshold_proposals.len() > MAX_THRESHOLD_PROPOSALS
        {
            return Err(HnmfContractError::BoundExceeded("plasticity proposal count"));
        }
        for proposal in &self.weight_proposals {
            if proposal.source_node_id == 0
                || proposal.target_node_id == 0
                || proposal.source_node_id == proposal.target_node_id
                || !(-50_000..=50_000).contains(&proposal.delta_ppm)
                || !(-1_000_000..=1_000_000).contains(&proposal.new_eligibility_ppm)
            {
                return Err(HnmfContractError::Invalid("weight proposal is invalid"));
            }
        }
        for proposal in &self.threshold_proposals {
            if proposal.node_id == 0 || !(-50_000..=50_000).contains(&proposal.delta_ppm) {
                return Err(HnmfContractError::Invalid("threshold proposal is invalid"));
            }
        }
        self.authority.validate()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", rename_all_fields = "camelCase", deny_unknown_fields)]
pub enum TopologyOperationV1 {
    AddNode { label: String, population: EngramPopulationV1 },
    SplitNode {
        #[serde(with = "super::exact_u64")]
        node_id: NodeIdV1,
        labels: [String; 2],
    },
    MergeNodes {
        #[serde(with = "super::exact_u64")]
        left: NodeIdV1,
        #[serde(with = "super::exact_u64")]
        right: NodeIdV1,
        label: String,
    },
    RetireNode {
        #[serde(with = "super::exact_u64")]
        node_id: NodeIdV1,
        reason: String,
    },
    Rewire {
        #[serde(with = "super::exact_u64")]
        source: NodeIdV1,
        #[serde(with = "super::exact_u64")]
        old_target: NodeIdV1,
        #[serde(with = "super::exact_u64")]
        new_target: NodeIdV1,
        relation: SynapseRelationV1,
    },
}

impl TopologyOperationV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        match self {
            Self::AddNode { label, .. } => {
                validate_text(label, MAX_TOPOLOGY_LABEL_BYTES, "topology label")
            }
            Self::MergeNodes { left, right, label } => {
                if *left == 0 || *right == 0 || left == right {
                    return Err(HnmfContractError::Invalid("merge endpoints are invalid"));
                }
                validate_text(label, MAX_TOPOLOGY_LABEL_BYTES, "topology label")
            }
            Self::SplitNode { node_id, labels } => {
                if *node_id == 0 || labels[0] == labels[1] {
                    return Err(HnmfContractError::Invalid("split node/labels are invalid"));
                }
                validate_text(&labels[0], MAX_TOPOLOGY_LABEL_BYTES, "topology label")?;
                validate_text(&labels[1], MAX_TOPOLOGY_LABEL_BYTES, "topology label")
            }
            Self::RetireNode { node_id, reason } => {
                if *node_id == 0 {
                    return Err(HnmfContractError::Invalid("retire node id is zero"));
                }
                validate_text(reason, MAX_TOPOLOGY_LABEL_BYTES, "retire reason")
            }
            Self::Rewire { source, old_target, new_target, .. } => {
                if *source == 0 || *old_target == 0 || *new_target == 0
                    || source == old_target || source == new_target || old_target == new_target
                {
                    return Err(HnmfContractError::Invalid("rewire endpoints are invalid"));
                }
                Ok(())
            }
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TopologyProposalV1 {
    #[serde(with = "super::exact_u64")]
    pub predecessor_generation: u64,
    #[serde(with = "super::exact_u64")]
    pub next_generation: u64,
    pub operation: TopologyOperationV1,
    pub capability_typed: bool,
    pub sandbox_only: bool,
    pub operator_accepted: bool,
    pub production_activation_allowed: bool,
    pub authority: AuthorityPostureV1,
}

impl CanonicalJsonV1 for TopologyProposalV1 {
    const SCHEMA_ID: &'static str = "TopologyProposalV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.predecessor_generation == 0
            || self.next_generation != self.predecessor_generation.checked_add(1).ok_or(HnmfContractError::Invalid("topology generation overflow"))?
            || !self.capability_typed
            || !self.sandbox_only
            || self.operator_accepted
            || self.production_activation_allowed
        {
            return Err(HnmfContractError::AuthorityGranted);
        }
        self.operation.validate()?;
        self.authority.validate()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SynapseRefV1 {
    #[serde(with = "super::exact_u64")]
    pub source_node_id: NodeIdV1,
    #[serde(with = "super::exact_u64")]
    pub target_node_id: NodeIdV1,
    pub relation: SynapseRelationV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ForgetPropagationReceiptV1 {
    #[serde(with = "super::exact_u64")]
    pub event_id: EventIdV1,
    #[serde(with = "super::exact_u64")]
    pub predecessor_generation: u64,
    #[serde(with = "super::exact_u64")]
    pub next_generation: u64,
    #[serde(with = "super::exact_u64_vec")]
    pub retired_node_ids: Vec<NodeIdV1>,
    pub retired_synapses: Vec<SynapseRefV1>,
    pub projection_rebuild_required: bool,
    pub artifact_revocation_required: bool,
    pub authority: AuthorityPostureV1,
}

impl CanonicalJsonV1 for ForgetPropagationReceiptV1 {
    const SCHEMA_ID: &'static str = "ForgetPropagationReceiptV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.event_id == 0
            || self.predecessor_generation == 0
            || self.next_generation != self.predecessor_generation.checked_add(1).ok_or(HnmfContractError::Invalid("forget generation overflow"))?
            || !self.projection_rebuild_required
            || !self.artifact_revocation_required
        {
            return Err(HnmfContractError::Invalid("forget propagation state is invalid"));
        }
        validate_sorted_unique_u64_bounded(&self.retired_node_ids, MAX_SUBGRAPH_NODES, "retired nodes")?;
        if self.retired_synapses.len() > 32_768 {
            return Err(HnmfContractError::BoundExceeded("retired synapses"));
        }
        for pair in self.retired_synapses.windows(2) {
            if pair[0] >= pair[1] {
                return Err(HnmfContractError::Conflict(
                    "retired synapses are not strictly sorted/unique",
                ));
            }
        }
        self.authority.validate()
    }
}
