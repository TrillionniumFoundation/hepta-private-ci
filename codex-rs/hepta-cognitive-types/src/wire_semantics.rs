//! Closed native contract inventory and checked-wire semantic invariants.
//!
//! Raw compatibility structs remain constructible for owner-side migration.
//! Every wire codec and `Validated<T>` for a registered contract passes here.
//! Membership in this inventory is deliberately not implementable downstream.

use std::collections::BTreeSet;
use std::io;
use std::io::Write;

use serde::Serialize;

use crate::hnmf::CrossModalBindingV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf::MemoryEventV1;
use crate::hnmf::ModalitySpanRefV1;
use crate::hnmf_learning::EngramNodeV1;
use crate::hnmf_learning::ForgetPropagationReceiptV1;
use crate::hnmf_learning::MemoryCueV1;
use crate::hnmf_learning::OutcomeSignalV1;
use crate::hnmf_learning::PlasticityBatchV1;
use crate::hnmf_learning::RecallPacketV1;
use crate::hnmf_learning::ReplaySelectionReceiptV1;
use crate::hnmf_learning::SynapseV1;
use crate::hnmf_learning::TopologyProposalV1;

/// Seals the wire inventory and supplies the additional logical-key checks.
/// This trait is public only inside its private parent module.
pub trait Sealed {
    fn validate_semantics(&self) -> Result<(), HnmfContractError> {
        Ok(())
    }
}

impl Sealed for MemoryEventV1 {
    fn validate_semantics(&self) -> Result<(), HnmfContractError> {
        unique(
            self.provenance.iter().map(|row| (&row.source_id, row.source_revision)),
            "provenance.sourceId/sourceRevision",
        )
    }
}

impl Sealed for RecallPacketV1 {
    fn validate_semantics(&self) -> Result<(), HnmfContractError> {
        unique(
            self.selected_events.iter().map(|row| (&row.event_id, row.revision)),
            "selectedEvents.eventId/revision",
        )?;
        unique(self.active_nodes.iter().map(|row| &row.node_id), "activeNodes.nodeId")?;
        unique(
            self.activation_paths.iter().map(|row| {
                (&row.source_node_id, &row.target_node_id, row.relation)
            }),
            "activationPaths.source/target/relation",
        )
    }
}

impl Sealed for PlasticityBatchV1 {
    fn validate_semantics(&self) -> Result<(), HnmfContractError> {
        unique(
            self.weight_proposals.iter().map(|row| {
                (&row.source_node_id, &row.target_node_id, row.relation)
            }),
            "weightProposals.source/target/relation",
        )?;
        unique(
            self.threshold_proposals.iter().map(|row| &row.node_id),
            "thresholdProposals.nodeId",
        )
    }
}

impl Sealed for TopologyProposalV1 {
    fn validate_semantics(&self) -> Result<(), HnmfContractError> {
        unique(self.typed_nodes_edges.nodes.iter().map(|row| &row.node_id), "topologyNodes.nodeId")
    }
}

impl Sealed for ModalitySpanRefV1 {}
impl Sealed for CrossModalBindingV1 {}
impl Sealed for EngramNodeV1 {}
impl Sealed for SynapseV1 {}
impl Sealed for MemoryCueV1 {}
impl Sealed for OutcomeSignalV1 {}
impl Sealed for ReplaySelectionReceiptV1 {}
impl Sealed for ForgetPropagationReceiptV1 {}

fn unique<K: Ord>(keys: impl IntoIterator<Item = K>, field: &'static str) -> Result<(), HnmfContractError> {
    let mut seen = BTreeSet::new();
    for key in keys {
        if !seen.insert(key) {
            return Err(HnmfContractError::Conflict(field));
        }
    }
    Ok(())
}

/// Count the actual JSON serialization without allocating a payload-sized Vec.
/// Abort at the first byte beyond the cap, before compatibility validators that
/// still serialize internally and before building the canonical JSON value.
/// `maximum + 1` is a lower bound, not a claim to have scanned the whole object.
pub(crate) fn validate_serialized_bound<T: Serialize>(
    value: &T,
    maximum: usize,
) -> Result<(), HnmfContractError> {
    let mut sink = ByteBudget { remaining: maximum, exceeded: false };
    let result = serde_json::to_writer(&mut sink, value);
    if sink.exceeded {
        return Err(HnmfContractError::LimitExceeded {
            field: "payload",
            actual: maximum.saturating_add(1),
            maximum,
        });
    }
    result.map_err(|_| HnmfContractError::Invalid("contract serialization"))
}

struct ByteBudget {
    remaining: usize,
    exceeded: bool,
}

impl Write for ByteBudget {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > self.remaining {
            self.exceeded = true;
            return Err(io::Error::other("cognitive payload byte limit exceeded"));
        }
        self.remaining -= bytes.len();
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
