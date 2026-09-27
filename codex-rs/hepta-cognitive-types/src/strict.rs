//! Cross-field validators that require more than local shape validity.

use std::collections::BTreeSet;

use crate::hnmf::AssetManifestV1;
use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf::ModalityKindV1;
use crate::hnmf::ModalitySpanRefV1;
use crate::hnmf::SpanRangeV1;
use crate::hnmf::validate_span_against_manifest_v1;
use crate::hnmf_learning::ForgetPropagationReceiptV1;
use crate::hnmf_learning::PlasticityBatchV1;
use crate::hnmf_learning::PlasticityClassV1;
use crate::hnmf_learning::ReplaySelectionReceiptV1;
use crate::hnmf_learning::SynapseRelationV1;
use crate::hnmf_learning::SynapseV1;
use crate::hnmf_learning::TopologyOperationV1;
use crate::hnmf_learning::TopologyProposalV1;
use crate::lane_c::FederatedCompletenessV1;
use crate::lane_c::FederatedEvidenceResultV1;
use crate::lane_c::FederatedValidityV1;
use crate::lane_c::LaneCContractError;

pub const MAX_SELECTOR_INDEX_ENTRIES_V1: usize = 65_536;
pub const MAX_REPLAY_BUCKETS_V1: usize = 256;
pub const MAX_PLASTICITY_WEIGHT_PROPOSALS_V1: usize = 32_768;
pub const MAX_PLASTICITY_THRESHOLD_PROPOSALS_V1: usize = 4_096;
pub const MAX_FORGET_RETIRED_NODES_V1: usize = 4_096;
pub const MAX_FORGET_RETIRED_SYNAPSES_V1: usize = 32_768;

pub trait ValidateStrictV1 {
    type Error;

    fn validate_strict_v1(&self) -> Result<(), Self::Error>;
}

impl ValidateStrictV1 for FederatedEvidenceResultV1 {
    type Error = LaneCContractError;

    fn validate_strict_v1(&self) -> Result<(), Self::Error> {
        self.validate()?;
        let coverage = &self.coverage;
        match self.completeness {
            FederatedCompletenessV1::Complete => {
                if coverage.completed_peers != coverage.requested_peers
                    || coverage.failed_peers != 0
                    || coverage.truncated_items != 0
                    || self.items.is_empty()
                    || matches!(self.validity, FederatedValidityV1::Indeterminate)
                {
                    return Err(LaneCContractError::InvalidState(
                        "federated_complete_binding",
                    ));
                }
            }
            FederatedCompletenessV1::Partial => {
                let explains_partial = coverage.completed_peers < coverage.requested_peers
                    || coverage.failed_peers > 0
                    || coverage.truncated_items > 0;
                if !explains_partial || self.items.is_empty() {
                    return Err(LaneCContractError::InvalidState(
                        "federated_partial_binding",
                    ));
                }
            }
            FederatedCompletenessV1::Empty => {
                if !self.items.is_empty()
                    || coverage.completed_peers != coverage.requested_peers
                    || coverage.failed_peers != 0
                    || coverage.truncated_items != 0
                {
                    return Err(LaneCContractError::InvalidState(
                        "federated_empty_binding",
                    ));
                }
            }
            FederatedCompletenessV1::Indeterminate => {
                if !self.items.is_empty()
                    || !matches!(self.validity, FederatedValidityV1::Indeterminate)
                    || (coverage.failed_peers == 0
                        && coverage.completed_peers == coverage.requested_peers)
                {
                    return Err(LaneCContractError::InvalidState(
                        "federated_indeterminate_binding",
                    ));
                }
            }
        }

        // A result may not present two revisions of one semantic record as if
        // both were current evidence.
        let mut records = BTreeSet::new();
        for item in &self.items {
            if !records.insert((item.source_owner_id.clone(), item.record_id.clone())) {
                return Err(LaneCContractError::DuplicateIdentity(
                    "federated_semantic_record",
                ));
            }
        }
        Ok(())
    }
}

impl ValidateStrictV1 for SynapseV1 {
    type Error = HnmfContractError;

    fn validate_strict_v1(&self) -> Result<(), Self::Error> {
        self.validate()?;
        if self.weight_q16 == 0
            || (self.relation.is_negative() && self.weight_q16 >= 0)
            || (!self.relation.is_negative() && self.weight_q16 <= 0)
        {
            return Err(HnmfContractError::Conflict("synapse relation/weight sign"));
        }
        if matches!(self.plasticity_class, PlasticityClassV1::Fixed)
            && self.eligibility_ppm != 0
        {
            return Err(HnmfContractError::Conflict("fixed synapse eligibility"));
        }
        Ok(())
    }
}

impl ValidateStrictV1 for ReplaySelectionReceiptV1 {
    type Error = HnmfContractError;

    fn validate_strict_v1(&self) -> Result<(), Self::Error> {
        self.validate()?;
        if self.source_bucket_counts.len() > MAX_REPLAY_BUCKETS_V1 {
            return Err(HnmfContractError::LimitExceeded {
                field: "sourceBucketCounts",
                actual: self.source_bucket_counts.len(),
                maximum: MAX_REPLAY_BUCKETS_V1,
            });
        }
        if self.resource_receipt.selected_count == 0
            && (!self.selected_event_ids.is_empty() || !self.source_bucket_counts.is_empty())
        {
            return Err(HnmfContractError::Conflict("empty replay selection"));
        }
        Ok(())
    }
}

impl ValidateStrictV1 for PlasticityBatchV1 {
    type Error = HnmfContractError;

    fn validate_strict_v1(&self) -> Result<(), Self::Error> {
        self.validate()?;
        if self.weight_proposals.is_empty() && self.threshold_proposals.is_empty() {
            return Err(HnmfContractError::Invalid("empty plasticity batch"));
        }
        if self.weight_proposals.len() > MAX_PLASTICITY_WEIGHT_PROPOSALS_V1 {
            return Err(HnmfContractError::LimitExceeded {
                field: "weightProposals",
                actual: self.weight_proposals.len(),
                maximum: MAX_PLASTICITY_WEIGHT_PROPOSALS_V1,
            });
        }
        if self.threshold_proposals.len() > MAX_PLASTICITY_THRESHOLD_PROPOSALS_V1 {
            return Err(HnmfContractError::LimitExceeded {
                field: "thresholdProposals",
                actual: self.threshold_proposals.len(),
                maximum: MAX_PLASTICITY_THRESHOLD_PROPOSALS_V1,
            });
        }
        for proposal in &self.weight_proposals {
            let negative = proposal.relation.is_negative();
            if proposal.new_weight_q16 == 0
                || (negative
                    && (proposal.old_weight_q16 > 0 || proposal.new_weight_q16 >= 0))
                || (!negative
                    && (proposal.old_weight_q16 < 0 || proposal.new_weight_q16 <= 0))
            {
                return Err(HnmfContractError::Conflict(
                    "plasticity relation/weight sign",
                ));
            }
        }
        Ok(())
    }
}

impl ValidateStrictV1 for TopologyProposalV1 {
    type Error = HnmfContractError;

    fn validate_strict_v1(&self) -> Result<(), Self::Error> {
        self.validate()?;
        let node_count = i64::try_from(self.typed_nodes_edges.nodes.len())
            .map_err(|_| HnmfContractError::Invalid("topology node count"))?;
        let edge_count = i64::try_from(self.typed_nodes_edges.edges.len())
            .map_err(|_| HnmfContractError::Invalid("topology edge count"))?;
        let expected_node_delta = match self.operation {
            TopologyOperationV1::Add => node_count,
            TopologyOperationV1::Retire => -node_count,
            TopologyOperationV1::Split => node_count
                .checked_sub(1)
                .ok_or(HnmfContractError::Invalid("topology split delta"))?,
            TopologyOperationV1::Merge => 1i64
                .checked_sub(node_count)
                .ok_or(HnmfContractError::Invalid("topology merge delta"))?,
            TopologyOperationV1::Rewire => 0,
        };
        if self.resource_delta.node_delta != expected_node_delta {
            return Err(HnmfContractError::Conflict("topology node delta"));
        }
        match self.operation {
            TopologyOperationV1::Add if self.resource_delta.edge_delta != edge_count => {
                return Err(HnmfContractError::Conflict("topology add edge delta"));
            }
            TopologyOperationV1::Retire if self.resource_delta.edge_delta != -edge_count => {
                return Err(HnmfContractError::Conflict("topology retire edge delta"));
            }
            TopologyOperationV1::Rewire
                if node_count != 0 || edge_count == 0 || self.resource_delta.edge_delta != 0 =>
            {
                return Err(HnmfContractError::Conflict("topology rewire delta"));
            }
            _ => {}
        }
        let net_objects = self
            .resource_delta
            .node_delta
            .checked_add(self.resource_delta.edge_delta)
            .ok_or(HnmfContractError::Invalid("topology resource delta overflow"))?;
        if (net_objects > 0 && self.resource_delta.resident_bytes_upper_bound_delta <= 0)
            || (net_objects < 0 && self.resource_delta.resident_bytes_upper_bound_delta >= 0)
        {
            return Err(HnmfContractError::Conflict("topology resident byte delta"));
        }
        Ok(())
    }
}

impl ValidateStrictV1 for ForgetPropagationReceiptV1 {
    type Error = HnmfContractError;

    fn validate_strict_v1(&self) -> Result<(), Self::Error> {
        self.validate()?;
        if self.retired_node_ids.is_empty() && self.retired_synapses.is_empty() {
            return Err(HnmfContractError::Invalid("empty forget propagation"));
        }
        if self.retired_node_ids.len() > MAX_FORGET_RETIRED_NODES_V1 {
            return Err(HnmfContractError::LimitExceeded {
                field: "retiredNodeIds",
                actual: self.retired_node_ids.len(),
                maximum: MAX_FORGET_RETIRED_NODES_V1,
            });
        }
        if self.retired_synapses.len() > MAX_FORGET_RETIRED_SYNAPSES_V1 {
            return Err(HnmfContractError::LimitExceeded {
                field: "retiredSynapses",
                actual: self.retired_synapses.len(),
                maximum: MAX_FORGET_RETIRED_SYNAPSES_V1,
            });
        }
        if self
            .retired_synapses
            .iter()
            .any(|synapse| synapse.source_node_id == synapse.target_node_id)
        {
            return Err(HnmfContractError::Invalid("retired synapse self-loop"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectorResolutionContextV1 {
    manifest: AssetManifestV1,
    selector_index_sha256: ContractDigestV1,
    ast_paths: BTreeSet<String>,
    gui_node_ids: BTreeSet<ContractIdV1>,
    json_pointers: BTreeSet<String>,
}

impl SelectorResolutionContextV1 {
    pub fn new(
        manifest: AssetManifestV1,
        selector_index_sha256: ContractDigestV1,
        ast_paths: BTreeSet<String>,
        gui_node_ids: BTreeSet<ContractIdV1>,
        json_pointers: BTreeSet<String>,
    ) -> Result<Self, HnmfContractError> {
        for (field, len) in [
            ("astPaths", ast_paths.len()),
            ("guiNodeIds", gui_node_ids.len()),
            ("jsonPointers", json_pointers.len()),
        ] {
            if len > MAX_SELECTOR_INDEX_ENTRIES_V1 {
                return Err(HnmfContractError::LimitExceeded {
                    field,
                    actual: len,
                    maximum: MAX_SELECTOR_INDEX_ENTRIES_V1,
                });
            }
        }
        for pointer in &json_pointers {
            validate_json_pointer_v1(pointer)?;
        }
        Ok(Self {
            manifest,
            selector_index_sha256,
            ast_paths,
            gui_node_ids,
            json_pointers,
        })
    }

    pub fn validate_span(&self, span: &ModalitySpanRefV1) -> Result<(), HnmfContractError> {
        validate_span_against_manifest_v1(&self.manifest, span)?;
        match (&span.range, span.modality) {
            (SpanRangeV1::AstPath { path }, ModalityKindV1::CodeAst)
                if self.ast_paths.contains(path) =>
            {
                Ok(())
            }
            (SpanRangeV1::GuiNode { stable_node_id }, ModalityKindV1::GuiState)
                if self.gui_node_ids.contains(stable_node_id) =>
            {
                Ok(())
            }
            (SpanRangeV1::JsonPointer { pointer }, ModalityKindV1::StructuredData) => {
                validate_json_pointer_v1(pointer)?;
                if self.json_pointers.contains(pointer) {
                    Ok(())
                } else {
                    Err(HnmfContractError::Missing("JSON pointer in selector index"))
                }
            }
            (SpanRangeV1::AstPath { .. }, ModalityKindV1::CodeAst) => {
                Err(HnmfContractError::Missing("AST path in selector index"))
            }
            (SpanRangeV1::GuiNode { .. }, ModalityKindV1::GuiState) => {
                Err(HnmfContractError::Missing("GUI node in selector index"))
            }
            _ => Ok(()),
        }
    }

    #[must_use]
    pub const fn selector_index_sha256(&self) -> ContractDigestV1 {
        self.selector_index_sha256
    }
}

pub fn validate_json_pointer_v1(pointer: &str) -> Result<(), HnmfContractError> {
    if pointer.is_empty() {
        return Ok(());
    }
    if !pointer.starts_with('/') || pointer.chars().any(char::is_control) {
        return Err(HnmfContractError::Invalid("JSON pointer"));
    }
    let bytes = pointer.as_bytes();
    let mut index = 0usize;
    while index < bytes.len() {
        if bytes[index] == b'~' {
            let Some(next) = bytes.get(index + 1) else {
                return Err(HnmfContractError::Invalid("JSON pointer escape"));
            };
            if !matches!(*next, b'0' | b'1') {
                return Err(HnmfContractError::Invalid("JSON pointer escape"));
            }
            index += 2;
        } else {
            index += 1;
        }
    }
    Ok(())
}

#[must_use]
pub const fn relation_requires_negative_weight_v1(relation: SynapseRelationV1) -> bool {
    relation.is_negative()
}
