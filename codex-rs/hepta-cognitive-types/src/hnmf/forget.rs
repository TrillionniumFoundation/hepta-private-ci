use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use super::CanonicalJsonV1;
use super::EventIdV1;
use super::HnmfContractError;
use super::MAX_FORGET_NODES;
use super::MAX_FORGET_SYNAPSES;
use super::NodeIdV1;
use super::SynapseRelationV1;
use super::ValidateHnmfV1;

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SynapseIdentityV1 {
    source_node_id: NodeIdV1,
    target_node_id: NodeIdV1,
    relation: SynapseRelationV1,
}

impl SynapseIdentityV1 {
    pub fn try_new(
        source_node_id: NodeIdV1,
        target_node_id: NodeIdV1,
        relation: SynapseRelationV1,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            source_node_id,
            target_node_id,
            relation,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for SynapseIdentityV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.source_node_id == 0
            || self.target_node_id == 0
            || self.source_node_id == self.target_node_id
        {
            return Err(HnmfContractError::Invalid("forget synapse identity"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ForgetPropagationReceiptV1 {
    event_id: EventIdV1,
    predecessor_generation: u64,
    next_generation: u64,
    retired_node_ids: BTreeSet<NodeIdV1>,
    retired_synapses: BTreeSet<SynapseIdentityV1>,
    projection_rebuild_required: bool,
    artifact_revocation_required: bool,
}

impl ForgetPropagationReceiptV1 {
    pub fn try_new(
        event_id: EventIdV1,
        predecessor_generation: u64,
        next_generation: u64,
        retired_node_ids: BTreeSet<NodeIdV1>,
        retired_synapses: BTreeSet<SynapseIdentityV1>,
    ) -> Result<Self, HnmfContractError> {
        let value = Self {
            event_id,
            predecessor_generation,
            next_generation,
            retired_node_ids,
            retired_synapses,
            projection_rebuild_required: true,
            artifact_revocation_required: true,
        };
        value.validate()?;
        Ok(value)
    }
}

impl ValidateHnmfV1 for ForgetPropagationReceiptV1 {
    fn validate(&self) -> Result<(), HnmfContractError> {
        if self.event_id == 0
            || self.predecessor_generation == 0
            || self.predecessor_generation.checked_add(1) != Some(self.next_generation)
        {
            return Err(HnmfContractError::Conflict("forget generation chain"));
        }
        if self.retired_node_ids.len() > MAX_FORGET_NODES
            || self.retired_synapses.len() > MAX_FORGET_SYNAPSES
        {
            return Err(HnmfContractError::BoundExceeded("forget propagation"));
        }
        if self.retired_node_ids.contains(&0) {
            return Err(HnmfContractError::Invalid("retired node id"));
        }
        if !self.projection_rebuild_required || !self.artifact_revocation_required {
            return Err(HnmfContractError::Conflict(
                "forget propagation must rebuild projections and revoke artifacts",
            ));
        }
        for synapse in &self.retired_synapses {
            synapse.validate()?;
        }
        Ok(())
    }
}

impl CanonicalJsonV1 for ForgetPropagationReceiptV1 {
    const SCHEMA_ID: &'static str = "hepta.hnmf.forget-propagation-receipt.v1";
    const MAX_ENCODED_BYTES: usize = 65_536;
}
