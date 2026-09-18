use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use super::CanonicalContractV1;
use super::CanonicalDigestV1;
use super::ContractErrorV1;
use super::EventIdV1;
use super::NodeIdV1;
use super::SynapseRelationV1;
use super::validate_nonzero;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ForgetRequestV1 {
    event_id: EventIdV1,
    reason_digest: CanonicalDigestV1,
    expected_generation: u64,
}

impl ForgetRequestV1 {
    pub fn try_new(
        event_id: EventIdV1,
        reason_digest: CanonicalDigestV1,
        expected_generation: u64,
    ) -> Result<Self, ContractErrorV1> {
        validate_nonzero(event_id, "forget event id must be non-zero")?;
        validate_nonzero(
            expected_generation,
            "forget expected generation must be non-zero",
        )?;
        Ok(Self {
            event_id,
            reason_digest,
            expected_generation,
        })
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct RetiredSynapseV1 {
    source_node_id: NodeIdV1,
    target_node_id: NodeIdV1,
    relation: SynapseRelationV1,
}

impl RetiredSynapseV1 {
    pub fn try_new(
        source_node_id: NodeIdV1,
        target_node_id: NodeIdV1,
        relation: SynapseRelationV1,
    ) -> Result<Self, ContractErrorV1> {
        let value = Self {
            source_node_id,
            target_node_id,
            relation,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        validate_nonzero(
            self.source_node_id,
            "retired synapse source must be non-zero",
        )?;
        validate_nonzero(
            self.target_node_id,
            "retired synapse target must be non-zero",
        )?;
        if self.source_node_id == self.target_node_id {
            return Err(ContractErrorV1::Invalid(
                "retired synapse endpoints must be distinct",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct ForgetPropagationReceiptV1 {
    event_id: EventIdV1,
    predecessor_generation: u64,
    next_generation: u64,
    retired_node_ids: Vec<NodeIdV1>,
    retired_synapses: Vec<RetiredSynapseV1>,
    projection_rebuild_required: bool,
    artifact_revocation_required: bool,
}

impl ForgetPropagationReceiptV1 {
    pub fn try_new(
        event_id: EventIdV1,
        predecessor_generation: u64,
        next_generation: u64,
        retired_node_ids: Vec<NodeIdV1>,
        retired_synapses: Vec<RetiredSynapseV1>,
        projection_rebuild_required: bool,
        artifact_revocation_required: bool,
    ) -> Result<Self, ContractErrorV1> {
        let value = Self {
            event_id,
            predecessor_generation,
            next_generation,
            retired_node_ids,
            retired_synapses,
            projection_rebuild_required,
            artifact_revocation_required,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        validate_nonzero(self.event_id, "forget event id must be non-zero")?;
        validate_nonzero(
            self.predecessor_generation,
            "forget predecessor generation must be non-zero",
        )?;
        if self.next_generation != self.predecessor_generation.saturating_add(1) {
            return Err(ContractErrorV1::Conflict(
                "forget next generation must be exact predecessor + 1",
            ));
        }
        if self.retired_node_ids.contains(&0) {
            return Err(ContractErrorV1::Invalid(
                "retired node ids must be non-zero",
            ));
        }
        let mut nodes = self.retired_node_ids.clone();
        nodes.sort_unstable();
        nodes.dedup();
        if nodes.len() != self.retired_node_ids.len() {
            return Err(ContractErrorV1::Conflict("duplicate retired node id"));
        }
        let mut synapses = BTreeSet::new();
        for synapse in &self.retired_synapses {
            synapse.validate()?;
            if !synapses.insert(synapse.clone()) {
                return Err(ContractErrorV1::Conflict("duplicate retired synapse"));
            }
        }
        if !self.projection_rebuild_required || !self.artifact_revocation_required {
            return Err(ContractErrorV1::AuthorityBoundary);
        }
        Ok(())
    }
}

impl CanonicalContractV1 for ForgetPropagationReceiptV1 {
    const SCHEMA_ID: &'static str = "ForgetPropagationReceiptV1";
    const MAX_ENCODED_BYTES: usize = 65_536;

    fn validate_contract(&self) -> Result<(), ContractErrorV1> {
        self.validate()
    }
}
