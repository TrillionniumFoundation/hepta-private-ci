//! Shared-encoder and bounded cell-worker primitives.
//!
//! This module is deliberately deterministic and authority-free. It provides
//! the P1/P2 serving skeleton: one immutable feature snapshot can be evaluated
//! by many lightweight cell heads, and a bounded round-robin queue prevents a
//! busy cell scope from starving other scopes. It is not a trainer and does not
//! mutate a live model or topology.

#![allow(clippy::module_name_repetitions)]

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const FEATURE_WIDTH: usize = 8;
const MAX_FEATURE_WIDTH: usize = 256;
const MAX_BATCH_ITEMS: usize = 1_024;
const MAX_QUEUE_ITEMS: usize = 16_384;

/// An immutable feature snapshot that may be shared by many cell heads.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ImmutableFeatureSnapshotV1 {
    generation: Generation,
    encoder_digest: Digest32,
    input_digest: Digest32,
    features: Arc<[i64]>,
}

impl ImmutableFeatureSnapshotV1 {
    /// Bind immutable features to the digest of the original source input.
    ///
    /// Distinct inputs can encode into identical features. Hashing feature
    /// values as input identity would alias different requests in the cache.
    /// The production Encoder owner must independently verify this provenance.
    pub fn new_for_input(
        generation: Generation,
        encoder_digest: Digest32,
        input_digest: Digest32,
        features: Vec<i64>,
    ) -> Result<Self, CellBatchError> {
        if encoder_digest.is_zero() {
            return Err(CellBatchError::ZeroDigest("encoder"));
        }
        if input_digest.is_zero() {
            return Err(CellBatchError::ZeroDigest("input"));
        }
        if features.is_empty() || features.len() > MAX_FEATURE_WIDTH {
            return Err(CellBatchError::FeatureWidth);
        }
        Ok(Self {
            generation,
            encoder_digest,
            input_digest,
            features: Arc::from(features),
        })
    }

    /// Deterministic reference encoder used by parity and routing fixtures.
    /// Production learned encoders can replace this constructor while keeping
    /// the snapshot/head and queue contracts unchanged.
    pub fn encode(
        generation: Generation,
        encoder_digest: Digest32,
        input: &[u8],
    ) -> Result<Self, CellBatchError> {
        if input.is_empty() {
            return Err(CellBatchError::EmptyInput);
        }
        let digest = Digest32::of_parts(&[&encoder_digest.as_array()[..], input]);
        let bytes = digest.as_array();
        let features = (0..FEATURE_WIDTH)
            .map(|index| {
                let offset = index * 4;
                i64::from(u32::from_be_bytes([
                    bytes[offset],
                    bytes[offset + 1],
                    bytes[offset + 2],
                    bytes[offset + 3],
                ]))
            })
            .collect();
        Self::new_for_input(
            generation,
            encoder_digest,
            Digest32::of_bytes(input),
            features,
        )
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub const fn encoder_digest(&self) -> Digest32 {
        self.encoder_digest
    }

    #[must_use]
    pub const fn input_digest(&self) -> Digest32 {
        self.input_digest
    }

    #[must_use]
    pub fn features(&self) -> &[i64] {
        &self.features
    }
}

/// A same-generation batch of immutable feature snapshots.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeatureBatchV1 {
    generation: Generation,
    snapshots: Arc<[ImmutableFeatureSnapshotV1]>,
}

impl FeatureBatchV1 {
    pub fn new(snapshots: Vec<ImmutableFeatureSnapshotV1>) -> Result<Self, CellBatchError> {
        let Some(first) = snapshots.first() else {
            return Err(CellBatchError::EmptyBatch);
        };
        if snapshots.len() > MAX_BATCH_ITEMS {
            return Err(CellBatchError::BatchCapacity);
        }
        let generation = first.generation();
        if snapshots
            .iter()
            .any(|snapshot| snapshot.generation() != generation)
        {
            return Err(CellBatchError::GenerationMismatch);
        }
        let encoder_digest = first.encoder_digest();
        if snapshots
            .iter()
            .any(|snapshot| snapshot.encoder_digest() != encoder_digest)
        {
            return Err(CellBatchError::EncoderMismatch);
        }
        Ok(Self {
            generation,
            snapshots: Arc::from(snapshots),
        })
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub fn snapshots(&self) -> &[ImmutableFeatureSnapshotV1] {
        &self.snapshots
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.snapshots.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.snapshots.is_empty()
    }
}

/// A lightweight immutable adapter/head owned by one logical cell.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellAdapterHeadV1 {
    pub cell_id: StableId,
    pub scope_id: StableId,
    pub generation: Generation,
    encoder_digest: Digest32,
    weights: Arc<[i64]>,
    bias: i64,
}

impl CellAdapterHeadV1 {
    pub fn new(
        cell_id: StableId,
        scope_id: StableId,
        generation: Generation,
        encoder_digest: Digest32,
        weights: Vec<i64>,
        bias: i64,
    ) -> Result<Self, CellBatchError> {
        if encoder_digest.is_zero() {
            return Err(CellBatchError::ZeroDigest("encoder"));
        }
        if weights.is_empty() || weights.len() > MAX_FEATURE_WIDTH {
            return Err(CellBatchError::FeatureWidth);
        }
        Ok(Self {
            cell_id,
            scope_id,
            generation,
            encoder_digest,
            weights: Arc::from(weights),
            bias,
        })
    }

    /// Zero-delta parity keeps the currently selected generation immutable.
    ///
    /// A nonzero update must use `with_successor_delta` so that the changed
    /// weights cannot be evaluated under the currently selected generation.
    pub fn with_delta(&self, delta: &[i64]) -> Result<Self, CellBatchError> {
        if delta.len() != self.weights.len() {
            return Err(CellBatchError::DeltaWidth);
        }
        if delta.iter().any(|update| *update != 0) {
            return Err(CellBatchError::ParameterUpdateRequiresSuccessor);
        }
        Ok(self.clone())
    }

    /// Stage an updated candidate in the *next* generation. This creates a
    /// value, not activation or promotion authority: Control still owns
    /// selection, signed artifact admission and the route cutover.
    pub fn with_successor_delta(
        &self,
        successor_generation: Generation,
        delta: &[i64],
    ) -> Result<Self, CellBatchError> {
        if self.generation.next() != Ok(successor_generation) {
            return Err(CellBatchError::GenerationNotSuccessor);
        }
        if delta.len() != self.weights.len() {
            return Err(CellBatchError::DeltaWidth);
        }
        let weights = self
            .weights
            .iter()
            .zip(delta)
            .map(|(weight, update)| {
                weight
                    .checked_add(*update)
                    .ok_or(CellBatchError::Arithmetic)
            })
            .collect::<Result<Vec<_>, _>>()?;
        Self::new(
            self.cell_id.clone(),
            self.scope_id.clone(),
            successor_generation,
            self.encoder_digest,
            weights,
            self.bias,
        )
    }

    pub fn activate(
        &self,
        snapshot: &ImmutableFeatureSnapshotV1,
    ) -> Result<CellActivationV1, CellBatchError> {
        if self.generation != snapshot.generation() {
            return Err(CellBatchError::GenerationMismatch);
        }
        if self.encoder_digest != snapshot.encoder_digest() {
            return Err(CellBatchError::EncoderMismatch);
        }
        if self.weights.len() != snapshot.features().len() {
            return Err(CellBatchError::FeatureWidth);
        }
        let score = self.weights.iter().zip(snapshot.features()).try_fold(
            self.bias,
            |score, (weight, feature)| {
                score
                    .checked_add(
                        weight
                            .checked_mul(*feature)
                            .ok_or(CellBatchError::Arithmetic)?,
                    )
                    .ok_or(CellBatchError::Arithmetic)
            },
        )?;
        Ok(CellActivationV1 {
            cell_id: self.cell_id.clone(),
            scope_id: self.scope_id.clone(),
            feature_generation: snapshot.generation(),
            score,
        })
    }

    pub fn activate_batch(
        &self,
        batch: &FeatureBatchV1,
    ) -> Result<CellActivationBatchV1, CellBatchError> {
        if self.generation != batch.generation() {
            return Err(CellBatchError::GenerationMismatch);
        }
        let activations = batch
            .snapshots()
            .iter()
            .map(|snapshot| self.activate(snapshot))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(CellActivationBatchV1 {
            cell_id: self.cell_id.clone(),
            scope_id: self.scope_id.clone(),
            feature_generation: batch.generation(),
            activations: Arc::from(activations),
        })
    }
}

/// Result of one cell head activation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellActivationV1 {
    pub cell_id: StableId,
    pub scope_id: StableId,
    pub feature_generation: Generation,
    pub score: i64,
}

/// Batch result preserving the head and generation binding for every score.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellActivationBatchV1 {
    pub cell_id: StableId,
    pub scope_id: StableId,
    pub feature_generation: Generation,
    pub activations: Arc<[CellActivationV1]>,
}

/// Small state witness used by migration fixtures.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellStateV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub hidden_state_digest: Digest32,
}

impl CellStateV1 {
    pub fn migrate_to(&self, successor_generation: Generation) -> Result<Self, CellBatchError> {
        if self.generation.next() != Ok(successor_generation) {
            return Err(CellBatchError::GenerationNotSuccessor);
        }
        if self.hidden_state_digest.is_zero() {
            return Err(CellBatchError::ZeroDigest("hidden state"));
        }
        Ok(Self {
            cell_id: self.cell_id.clone(),
            generation: successor_generation,
            hidden_state_digest: self.hidden_state_digest,
        })
    }
}

/// One bounded request in the shared worker queue.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QueuedCellRequestV1 {
    pub request_id: StableId,
    pub cell_id: StableId,
    pub scope_id: StableId,
    pub feature_generation: Generation,
}

/// Deterministic, bounded round-robin scheduler across logical scopes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FairCellQueueV1 {
    maximum_items: usize,
    length: usize,
    queues: BTreeMap<StableId, VecDeque<QueuedCellRequestV1>>,
    ready_scopes: VecDeque<StableId>,
    request_ids: BTreeSet<StableId>,
}

impl FairCellQueueV1 {
    pub fn new(maximum_items: usize) -> Result<Self, CellBatchError> {
        if maximum_items == 0 {
            return Err(CellBatchError::ZeroCapacity);
        }
        Ok(Self {
            maximum_items: maximum_items.min(MAX_QUEUE_ITEMS),
            length: 0,
            queues: BTreeMap::new(),
            ready_scopes: VecDeque::new(),
            request_ids: BTreeSet::new(),
        })
    }

    pub fn push(&mut self, request: QueuedCellRequestV1) -> Result<(), CellBatchError> {
        if self.length >= self.maximum_items {
            return Err(CellBatchError::QueueFull);
        }
        if !self.request_ids.insert(request.request_id.clone()) {
            return Err(CellBatchError::DuplicateRequest);
        }
        let scope = request.scope_id.clone();
        let queue = self.queues.entry(scope.clone()).or_default();
        if queue.is_empty() {
            self.ready_scopes.push_back(scope);
        }
        queue.push_back(request);
        self.length += 1;
        Ok(())
    }

    pub fn drain_batch(&mut self, maximum: usize) -> Vec<QueuedCellRequestV1> {
        let mut batch = Vec::with_capacity(maximum.min(self.length));
        while batch.len() < maximum {
            let Some(scope) = self.ready_scopes.pop_front() else {
                break;
            };
            let Some(queue) = self.queues.get_mut(&scope) else {
                continue;
            };
            let Some(request) = queue.pop_front() else {
                continue;
            };
            self.request_ids.remove(&request.request_id);
            self.length -= 1;
            batch.push(request);
            if queue.is_empty() {
                // Retire empty per-scope metadata. A bounded request queue must
                // not retain every historical scope after its last dispatch.
                self.queues.remove(&scope);
            } else {
                self.ready_scopes.push_back(scope);
            }
        }
        batch
    }

    #[must_use]
    pub const fn len(&self) -> usize {
        self.length
    }

    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.length == 0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellBatchError {
    Arithmetic,
    BatchCapacity,
    EmptyBatch,
    EmptyInput,
    FeatureWidth,
    DeltaWidth,
    ParameterUpdateRequiresSuccessor,
    ZeroDigest(&'static str),
    GenerationNotSuccessor,
    GenerationMismatch,
    EncoderMismatch,
    ZeroCapacity,
    QueueFull,
    DuplicateRequest,
}

impl fmt::Display for CellBatchError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CellBatchError {}

#[cfg(test)]
#[path = "cell_batch_tests.rs"]
mod tests;

#[cfg(test)]
#[test]
fn draining_transient_scopes_reclaims_all_queue_metadata() {
    let mut queue = FairCellQueueV1::new(2).expect("queue");
    for index in 0..128 {
        let request_id = StableId::new(format!("request:reclaim:{index}")).expect("request");
        let scope_id = StableId::new(format!("scope:reclaim:{index}")).expect("scope");
        queue
            .push(QueuedCellRequestV1 {
                request_id,
                cell_id: StableId::new("cell:reclaim").expect("cell"),
                scope_id,
                feature_generation: Generation::new(1).expect("generation"),
            })
            .expect("bounded admission");
        assert_eq!(queue.drain_batch(1).len(), 1);
        assert!(queue.is_empty());
        assert!(queue.queues.is_empty(), "stale scope metadata");
        assert!(queue.ready_scopes.is_empty(), "stale ready-scope metadata");
        assert!(queue.request_ids.is_empty(), "stale request dedup entry");
    }
}
