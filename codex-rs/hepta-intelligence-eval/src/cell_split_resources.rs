//! Resource and host-observation receipts consumed by CellSplit evaluation.
//!
//! A local fixture may produce the same deterministic shape, but its origin is
//! explicit and cannot be presented as a production target-host qualification.

use codex_hepta_types::CellResourceDeltaV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::LongitudinalTimeEvidenceV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellSplitResourceEvidenceOriginV1 {
    LocalSimulation,
    TargetHostMeasurement,
}

impl CellSplitResourceEvidenceOriginV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::LocalSimulation => 0,
            Self::TargetHostMeasurement => 1,
        }
    }
}

/// Measured costs and host receipts. The signature over this payload belongs
/// to the host's observer trust store; this type itself grants no authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitResourceReceiptV1 {
    pub split_id: StableId,
    pub measurement_id: StableId,
    pub target_host_id: StableId,
    pub origin: CellSplitResourceEvidenceOriginV1,
    pub resources: CellResourceDeltaV1,
    pub dispatch_receipt_digest: Digest32,
    pub restart_receipt_digest: Digest32,
    pub rollback_receipt_digest: Digest32,
    pub source_tree_digest: Digest32,
    pub observed_window_digest: Digest32,
}

impl CellSplitResourceReceiptV1 {
    pub fn validate_for(
        &self,
        split: &CellSplitV1,
        timing: &LongitudinalTimeEvidenceV1,
    ) -> Result<(), &'static str> {
        split.validate_plan().map_err(|_| "split plan")?;
        if self.split_id != split.split_id
            || self.measurement_id.as_str().is_empty()
            || self.target_host_id.as_str().is_empty()
            || timing.windows.len() < 2
            || self.dispatch_receipt_digest.is_zero()
            || self.restart_receipt_digest.is_zero()
            || self.rollback_receipt_digest.is_zero()
            || self.source_tree_digest.is_zero()
            || self.observed_window_digest.is_zero()
        {
            return Err("resource binding");
        }
        if !within(self.resources, split.resources) {
            return Err("resource budget");
        }
        if total(self.resources) == 0 {
            return Err("empty resource measurement");
        }
        Ok(())
    }

    #[must_use]
    pub fn signing_payload(&self) -> Vec<u8> {
        let mut bytes = b"hepta.learning.cell-split.resource-receipt.v1".to_vec();
        push_id(&mut bytes, &self.split_id);
        push_id(&mut bytes, &self.measurement_id);
        push_id(&mut bytes, &self.target_host_id);
        bytes.push(self.origin.tag());
        encode_resources(&mut bytes, self.resources);
        for digest in [
            self.dispatch_receipt_digest,
            self.restart_receipt_digest,
            self.rollback_receipt_digest,
            self.source_tree_digest,
            self.observed_window_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes
    }

    #[must_use]
    pub fn receipt_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.signing_payload())
    }
}

fn within(value: CellResourceDeltaV1, budget: CellResourceDeltaV1) -> bool {
    value.inference_latency_micros <= budget.inference_latency_micros
        && value.training_steps <= budget.training_steps
        && value.communication_bytes <= budget.communication_bytes
        && value.migration_bytes <= budget.migration_bytes
        && value.evaluation_steps <= budget.evaluation_steps
        && value.resident_bytes <= budget.resident_bytes
        && value.checkpoint_bytes <= budget.checkpoint_bytes
}

fn total(value: CellResourceDeltaV1) -> u64 {
    value
        .inference_latency_micros
        .saturating_add(value.training_steps)
        .saturating_add(value.communication_bytes)
        .saturating_add(value.migration_bytes)
        .saturating_add(value.evaluation_steps)
        .saturating_add(value.resident_bytes)
        .saturating_add(value.checkpoint_bytes)
}

fn encode_resources(bytes: &mut Vec<u8>, value: CellResourceDeltaV1) {
    for item in [
        value.inference_latency_micros,
        value.training_steps,
        value.communication_bytes,
        value.migration_bytes,
        value.evaluation_steps,
        value.resident_bytes,
        value.checkpoint_bytes,
    ] {
        bytes.extend_from_slice(&item.to_be_bytes());
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let value = id.as_str().as_bytes();
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value);
}
