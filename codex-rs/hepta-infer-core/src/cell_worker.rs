//! P2 shared-worker, routing, cache and batching contracts.
//!
//! These types keep logical cells in one host worker pool. They contain no OS
//! process creation, model authority or online parameter mutation.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::cell_batch::CellBatchError;
use crate::cell_batch::FairCellQueueV1;
use crate::cell_batch::ImmutableFeatureSnapshotV1;
use crate::cell_batch::QueuedCellRequestV1;

const MAX_INDEX_ENTRIES: usize = 16_384;

/// Stable hash-based router over a sorted set of logical cells.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DeterministicRouterV1 {
    cells: Vec<StableId>,
}

impl DeterministicRouterV1 {
    pub fn new(mut cells: Vec<StableId>) -> Result<Self, CellWorkerError> {
        cells.sort();
        cells.dedup();
        if cells.is_empty() {
            return Err(CellWorkerError::EmptyCellSet);
        }
        Ok(Self { cells })
    }

    #[must_use]
    pub fn route(&self, routing_seed: Digest32) -> StableId {
        let mut bytes = [0; 8];
        bytes.copy_from_slice(&routing_seed.as_array()[..8]);
        let index = (u64::from_be_bytes(bytes) % self.cells.len() as u64) as usize;
        self.cells[index].clone()
    }

    #[must_use]
    pub fn cells(&self) -> &[StableId] {
        &self.cells
    }
}

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct FeatureCacheKeyV1 {
    pub scope_id: StableId,
    pub encoder_digest: Digest32,
    pub input_digest: Digest32,
}

/// Generation-aware immutable feature cache.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct FeatureCacheV1 {
    entries: BTreeMap<FeatureCacheKeyV1, ImmutableFeatureSnapshotV1>,
}

impl FeatureCacheV1 {
    pub fn insert(
        &mut self,
        scope_id: StableId,
        snapshot: ImmutableFeatureSnapshotV1,
    ) -> Result<(), CellWorkerError> {
        let key = FeatureCacheKeyV1 {
            scope_id,
            encoder_digest: snapshot.encoder_digest(),
            input_digest: snapshot.input_digest(),
        };
        // One generation, scope, encoder and input must have exactly one
        // immutable feature value.  Replacing it silently would let different
        // cells consume conflicting representations under the same binding.
        if let Some(existing) = self.entries.get(&key) {
            if existing.generation().get() > snapshot.generation().get() {
                return Err(CellWorkerError::StaleFeatureGeneration);
            }
            if existing.generation() == snapshot.generation() && existing != &snapshot {
                return Err(CellWorkerError::FeatureSnapshotConflict);
            }
        } else if self.entries.len() >= MAX_INDEX_ENTRIES {
            return Err(CellWorkerError::IndexCapacity);
        }
        self.entries.insert(key, snapshot);
        Ok(())
    }

    #[must_use]
    pub fn get(
        &self,
        key: &FeatureCacheKeyV1,
        expected_generation: Generation,
    ) -> Option<&ImmutableFeatureSnapshotV1> {
        self.entries
            .get(key)
            .filter(|snapshot| snapshot.generation() == expected_generation)
    }

    pub fn invalidate_generation(&mut self, generation: Generation) {
        self.entries
            .retain(|_, snapshot| snapshot.generation() == generation);
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct CompatibleModelKeyV1 {
    pub model_digest: Digest32,
    pub encoder_digest: Digest32,
    pub output_width: u16,
}

/// Second index for heads that can consume the same model/encoder shape.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct CompatibleModelIndexV1 {
    entries: BTreeMap<CompatibleModelKeyV1, BTreeSet<StableId>>,
    entry_count: usize,
}

impl CompatibleModelIndexV1 {
    pub fn register(
        &mut self,
        key: CompatibleModelKeyV1,
        cell_id: StableId,
    ) -> Result<(), CellWorkerError> {
        if key.model_digest.is_zero() || key.encoder_digest.is_zero() || key.output_width == 0 {
            return Err(CellWorkerError::InvalidModelKey);
        }
        let already_registered = self
            .entries
            .get(&key)
            .is_some_and(|cells| cells.contains(&cell_id));
        if !already_registered && self.entry_count >= MAX_INDEX_ENTRIES {
            return Err(CellWorkerError::IndexCapacity);
        }
        if self.entries.entry(key).or_default().insert(cell_id) {
            // Keep registration O(log N): scanning all sets on every insert
            // made the model's "second index" O(N^2) for large cell fleets.
            self.entry_count += 1;
        }
        Ok(())
    }

    #[must_use]
    pub fn lookup(&self, key: &CompatibleModelKeyV1) -> Vec<StableId> {
        self.entries
            .get(key)
            .map(|cells| cells.iter().cloned().collect())
            .unwrap_or_default()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedWorkerBatchV1 {
    pub requests: Vec<QueuedCellRequestV1>,
    pub group_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GroupCommitMetricsV1 {
    pub groups_committed: u64,
    pub activations_committed: u64,
    pub dropped_requests: u64,
}

/// One in-process worker pool shared by many logical cells.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedWorkerPoolV1 {
    queue: FairCellQueueV1,
    maximum_batch: usize,
    metrics: GroupCommitMetricsV1,
}

impl SharedWorkerPoolV1 {
    pub fn new(maximum_queue: usize, maximum_batch: usize) -> Result<Self, CellWorkerError> {
        if maximum_batch == 0 {
            return Err(CellWorkerError::ZeroBatchSize);
        }
        Ok(Self {
            queue: FairCellQueueV1::new(maximum_queue).map_err(CellWorkerError::Queue)?,
            maximum_batch,
            metrics: GroupCommitMetricsV1 {
                groups_committed: 0,
                activations_committed: 0,
                dropped_requests: 0,
            },
        })
    }

    pub fn submit(&mut self, request: QueuedCellRequestV1) -> Result<(), CellWorkerError> {
        if let Err(error) = self.queue.push(request) {
            self.metrics.dropped_requests = self.metrics.dropped_requests.saturating_add(1);
            return Err(CellWorkerError::Queue(error));
        }
        Ok(())
    }

    pub fn drain(&mut self) -> SharedWorkerBatchV1 {
        let requests = self.queue.drain_batch(self.maximum_batch);
        let group_digest = digest_batch(&requests);
        if !requests.is_empty() {
            self.metrics.groups_committed = self.metrics.groups_committed.saturating_add(1);
            self.metrics.activations_committed = self
                .metrics
                .activations_committed
                .saturating_add(requests.len() as u64);
        }
        SharedWorkerBatchV1 {
            requests,
            group_digest,
        }
    }

    #[must_use]
    pub const fn metrics(&self) -> &GroupCommitMetricsV1 {
        &self.metrics
    }
}

fn digest_batch(requests: &[QueuedCellRequestV1]) -> Digest32 {
    // V2 frames every identity and binds the selected cell as well as scope.
    // Concatenating arbitrary IDs would alias (request="a", scope="bc")
    // with (request="ab", scope="c") and omit cell identity entirely.
    let mut bytes = b"hepta.cell.worker.batch.v2".to_vec();
    bytes.extend_from_slice(&(requests.len() as u32).to_be_bytes());
    for request in requests {
        push_batch_id(&mut bytes, &request.request_id);
        push_batch_id(&mut bytes, &request.cell_id);
        push_batch_id(&mut bytes, &request.scope_id);
        bytes.extend_from_slice(&request.feature_generation.get().to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn push_batch_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellWorkerError {
    EmptyCellSet,
    IndexCapacity,
    FeatureSnapshotConflict,
    StaleFeatureGeneration,
    InvalidModelKey,
    ZeroBatchSize,
    Queue(CellBatchError),
}

impl fmt::Display for CellWorkerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CellWorkerError {}

#[cfg(test)]
#[path = "cell_worker_tests.rs"]
mod tests;

#[cfg(test)]
#[test]
fn group_digest_frames_id_boundaries_and_cell_identity() {
    fn request(request_id: &str, cell_id: &str, scope_id: &str) -> QueuedCellRequestV1 {
        QueuedCellRequestV1 {
            request_id: StableId::new(request_id).expect("request"),
            cell_id: StableId::new(cell_id).expect("cell"),
            scope_id: StableId::new(scope_id).expect("scope"),
            feature_generation: Generation::new(1).expect("generation"),
        }
    }

    let baseline = digest_batch(&[request("a", "cell:one", "bc")]);
    let boundary_collision = digest_batch(&[request("ab", "cell:one", "c")]);
    let different_cell = digest_batch(&[request("a", "cell:two", "bc")]);
    assert_ne!(baseline, boundary_collision, "IDs must be length framed");
    assert_ne!(baseline, different_cell, "cell identity must be included");
    assert_ne!(baseline, digest_batch(&[]), "batch size must be included");
}

#[cfg(test)]
#[test]
fn compatible_model_index_counts_unique_cells_without_recounting() {
    let key = CompatibleModelKeyV1 {
        model_digest: Digest32::of_bytes(b"model"),
        encoder_digest: Digest32::of_bytes(b"encoder"),
        output_width: 8,
    };
    let mut index = CompatibleModelIndexV1::default();
    for number in 0..4096 {
        let cell_id = StableId::new(format!("cell:index:{number}")).expect("cell");
        index.register(key.clone(), cell_id.clone()).expect("register");
        index.register(key.clone(), cell_id).expect("idempotent registration");
    }
    assert_eq!(index.entry_count, 4096);
    assert_eq!(index.lookup(&key).len(), 4096);
}
