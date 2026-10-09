//! Read-only NDU-to-neuron stage binding.
//!
//! A stage carries only digests, never the NDU projection or policy object.
//! Product callers must independently verify the NDU owner's signed read
//! receipt before supplying its digest. This module cannot grant authority.

use codex_hepta_types::{AuthorityPosture, Digest32, Generation, NduSnapshotRefV1, StableId};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronStageBindingErrorV1 {
    InvalidSnapshot,
    ScopeMismatch,
    GenerationMismatch,
    SnapshotMismatch,
    MissingReadReceipt,
    MissingTickDigest,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronNduStageBindingV1 {
    pub tick_digest: Digest32,
    pub snapshot_ref_digest: Digest32,
    pub read_receipt_digest: Digest32,
    pub binding_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn bind_ndu_snapshot_stage_v1(
    subject_id: &StableId,
    generation: Generation,
    expected_snapshot_digest: Digest32,
    tick_digest: Digest32,
    snapshot: &NduSnapshotRefV1,
    admitted_read_receipt_digest: Digest32,
) -> Result<NeuronNduStageBindingV1, NeuronStageBindingErrorV1> {
    let reference_digest = snapshot
        .semantic_digest()
        .map_err(|_| NeuronStageBindingErrorV1::InvalidSnapshot)?;
    if &snapshot.scope_id != subject_id {
        return Err(NeuronStageBindingErrorV1::ScopeMismatch);
    }
    if snapshot.generation != generation {
        return Err(NeuronStageBindingErrorV1::GenerationMismatch);
    }
    if expected_snapshot_digest.is_zero()
        || snapshot.snapshot_digest != expected_snapshot_digest
    {
        return Err(NeuronStageBindingErrorV1::SnapshotMismatch);
    }
    if admitted_read_receipt_digest.is_zero() {
        return Err(NeuronStageBindingErrorV1::MissingReadReceipt);
    }
    if tick_digest.is_zero() {
        return Err(NeuronStageBindingErrorV1::MissingTickDigest);
    }
    let mut bytes = b"hepta.neuron.ndu-stage-binding.v1".to_vec();
    bytes.extend_from_slice(tick_digest.as_array());
    bytes.extend_from_slice(reference_digest.as_array());
    bytes.extend_from_slice(admitted_read_receipt_digest.as_array());
    Ok(NeuronNduStageBindingV1 {
        tick_digest,
        snapshot_ref_digest: reference_digest,
        read_receipt_digest: admitted_read_receipt_digest,
        binding_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "ndu_stage_tests.rs"]
mod tests;
