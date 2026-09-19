//! Deletion-bound generation rebuild admission.
//!
//! A rebuild never reuses the predecessor checkpoint state. It binds the exact
//! withdrawal evidence and requires a fresh successor generation so deleted or
//! revoked source influence cannot silently survive through a checkpoint.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronDeletionRebuildPlanV1 {
    pub rebuild_id: StableId,
    pub predecessor_generation: Generation,
    pub successor_generation: Generation,
    pub predecessor_checkpoint_digest: Digest32,
    pub withdrawal_registry_head_digest: Digest32,
    pub withdrawal_event_digest: Digest32,
    pub retained_dataset_set_digest: Digest32,
    pub source_event_set_digest: Digest32,
    pub retained_event_count: u64,
    pub deleted_event_count: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronDeletionRebuildReceiptV1 {
    pub rebuild_id: StableId,
    pub predecessor_generation: Generation,
    pub successor_generation: Generation,
    pub predecessor_checkpoint_digest: Digest32,
    pub withdrawal_registry_head_digest: Digest32,
    pub withdrawal_event_digest: Digest32,
    pub retained_dataset_set_digest: Digest32,
    pub source_event_set_digest: Digest32,
    pub retained_event_count: u64,
    pub deleted_event_count: u64,
    pub state_reused: bool,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DeletionRebuildError {
    GenerationNotExactSuccessor,
    EmptyDigest(&'static str),
    NoDeletedEvents,
    PredecessorMismatch,
    SuccessorMismatch,
}

impl fmt::Display for DeletionRebuildError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DeletionRebuildError {}

pub fn validate_deletion_rebuild(
    plan: &NeuronDeletionRebuildPlanV1,
) -> Result<NeuronDeletionRebuildReceiptV1, DeletionRebuildError> {
    if plan.predecessor_generation.next().ok() != Some(plan.successor_generation) {
        return Err(DeletionRebuildError::GenerationNotExactSuccessor);
    }
    for (name, digest) in [
        ("predecessor checkpoint", plan.predecessor_checkpoint_digest),
        ("withdrawal registry head", plan.withdrawal_registry_head_digest),
        ("withdrawal event", plan.withdrawal_event_digest),
        ("retained dataset set", plan.retained_dataset_set_digest),
        ("source event set", plan.source_event_set_digest),
    ] {
        if digest.is_zero() {
            return Err(DeletionRebuildError::EmptyDigest(name));
        }
    }
    if plan.deleted_event_count == 0 {
        return Err(DeletionRebuildError::NoDeletedEvents);
    }
    let mut bytes = b"hepta.neuron.deletion-rebuild.v1".to_vec();
    push_id(&mut bytes, &plan.rebuild_id);
    bytes.extend_from_slice(&plan.predecessor_generation.get().to_be_bytes());
    bytes.extend_from_slice(&plan.successor_generation.get().to_be_bytes());
    for digest in [
        plan.predecessor_checkpoint_digest,
        plan.withdrawal_registry_head_digest,
        plan.withdrawal_event_digest,
        plan.retained_dataset_set_digest,
        plan.source_event_set_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&plan.retained_event_count.to_be_bytes());
    bytes.extend_from_slice(&plan.deleted_event_count.to_be_bytes());
    bytes.push(0);
    let receipt_digest = Digest32::of_bytes(&bytes);
    Ok(NeuronDeletionRebuildReceiptV1 {
        rebuild_id: plan.rebuild_id.clone(),
        predecessor_generation: plan.predecessor_generation,
        successor_generation: plan.successor_generation,
        predecessor_checkpoint_digest: plan.predecessor_checkpoint_digest,
        withdrawal_registry_head_digest: plan.withdrawal_registry_head_digest,
        withdrawal_event_digest: plan.withdrawal_event_digest,
        retained_dataset_set_digest: plan.retained_dataset_set_digest,
        source_event_set_digest: plan.source_event_set_digest,
        retained_event_count: plan.retained_event_count,
        deleted_event_count: plan.deleted_event_count,
        state_reused: false,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "deletion_tests.rs"]
mod tests;
