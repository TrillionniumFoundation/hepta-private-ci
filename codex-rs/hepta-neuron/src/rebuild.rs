//! Deletion-aware deterministic neuron state rebuild.
//!
//! Rebuild accepts only caller-authenticated recomputation receipts. The neuron
//! module cannot authenticate their provenance itself; it does guarantee that a
//! revoked source is excluded before any sparse state mutation and that surviving
//! events are replayed into a fresh sequence chain.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::SparseCheckpoint;
use crate::SparseConfig;
use crate::SparseError;
use crate::SparseTick;
use crate::sparse_tick;

const MAX_REBUILD_EVENTS: usize = 4096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecomputedSparseEventV1 {
    pub source_digest: Digest32,
    pub recomputation_receipt_digest: Digest32,
    pub tick: SparseTick,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DeletionRebuildRequestV1 {
    pub events: Vec<RecomputedSparseEventV1>,
    pub revoked_source_digests: BTreeSet<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DeletionRebuildReceiptV1 {
    pub source_set_digest: Digest32,
    pub final_checkpoint_digest: Digest32,
    pub survivor_count: u32,
    pub removed_count: u32,
    pub cleared: bool,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DeletionRebuildOutputV1 {
    pub checkpoint: Option<SparseCheckpoint>,
    pub receipt: DeletionRebuildReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RebuildError {
    EventLimit,
    InvalidSource,
    InvalidRecomputationReceipt,
    SourceBinding,
    DuplicateSource,
    EventOrder,
    Sparse(SparseError),
    Arithmetic,
}

impl fmt::Display for RebuildError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RebuildError {}

impl From<SparseError> for RebuildError {
    fn from(value: SparseError) -> Self {
        Self::Sparse(value)
    }
}

pub fn rebuild_after_deletion(
    config: &SparseConfig,
    request: &DeletionRebuildRequestV1,
) -> Result<DeletionRebuildOutputV1, RebuildError> {
    if request.events.len() > MAX_REBUILD_EVENTS {
        return Err(RebuildError::EventLimit);
    }
    let mut seen_sources = BTreeSet::new();
    let mut previous_sequence = 0_u64;
    let mut previous_clock = 0_u64;
    for event in &request.events {
        if event.source_digest.is_zero() {
            return Err(RebuildError::InvalidSource);
        }
        if event.recomputation_receipt_digest.is_zero() {
            return Err(RebuildError::InvalidRecomputationReceipt);
        }
        if event.tick.input_digest != event.source_digest {
            return Err(RebuildError::SourceBinding);
        }
        if !seen_sources.insert(event.source_digest) {
            return Err(RebuildError::DuplicateSource);
        }
        if event.tick.sequence == 0
            || event.tick.sequence <= previous_sequence
            || event.tick.monotonic_micros <= previous_clock
        {
            return Err(RebuildError::EventOrder);
        }
        previous_sequence = event.tick.sequence;
        previous_clock = event.tick.monotonic_micros;
    }
    if request
        .revoked_source_digests
        .iter()
        .any(|digest| digest.is_zero())
    {
        return Err(RebuildError::InvalidSource);
    }

    let mut checkpoint = None;
    let mut survivors = Vec::new();
    let mut removed = 0_u32;
    for event in &request.events {
        if request
            .revoked_source_digests
            .contains(&event.source_digest)
        {
            removed = removed.checked_add(1).ok_or(RebuildError::Arithmetic)?;
            continue;
        }
        let next_sequence =
            u64::try_from(survivors.len() + 1).map_err(|_| RebuildError::Arithmetic)?;
        let mut tick = event.tick.clone();
        tick.sequence = next_sequence;
        let (next, _) = sparse_tick(config, &tick, checkpoint.as_ref())?;
        survivors.push((
            event.source_digest,
            event.recomputation_receipt_digest,
            next.digest(),
        ));
        checkpoint = Some(next);
    }

    let source_set_digest = digest_survivors(&survivors)?;
    let final_checkpoint_digest = checkpoint
        .as_ref()
        .map_or(Digest32::ZERO, SparseCheckpoint::digest);
    let survivor_count = u32::try_from(survivors.len()).map_err(|_| RebuildError::Arithmetic)?;
    let cleared = checkpoint.is_none();
    let receipt_digest = digest_receipt(
        source_set_digest,
        final_checkpoint_digest,
        survivor_count,
        removed,
        cleared,
    );
    let receipt = DeletionRebuildReceiptV1 {
        source_set_digest,
        final_checkpoint_digest,
        survivor_count,
        removed_count: removed,
        cleared,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok(DeletionRebuildOutputV1 {
        checkpoint,
        receipt,
    })
}

fn digest_survivors(
    survivors: &[(Digest32, Digest32, Digest32)],
) -> Result<Digest32, RebuildError> {
    let mut bytes = b"hepta.neuron.deletion-rebuild-sources.v1".to_vec();
    let length = u32::try_from(survivors.len()).map_err(|_| RebuildError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    for (source, recomputation, checkpoint) in survivors {
        bytes.extend_from_slice(source.as_array());
        bytes.extend_from_slice(recomputation.as_array());
        bytes.extend_from_slice(checkpoint.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_receipt(
    source_set_digest: Digest32,
    final_checkpoint_digest: Digest32,
    survivor_count: u32,
    removed_count: u32,
    cleared: bool,
) -> Digest32 {
    let mut bytes = b"hepta.neuron.deletion-rebuild-receipt.v1".to_vec();
    bytes.extend_from_slice(source_set_digest.as_array());
    bytes.extend_from_slice(final_checkpoint_digest.as_array());
    bytes.extend_from_slice(&survivor_count.to_be_bytes());
    bytes.extend_from_slice(&removed_count.to_be_bytes());
    bytes.push(u8::from(cleared));
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "rebuild_tests.rs"]
mod tests;
