//! Authority-free, bounded inference batching. This is a scheduler, not a
//! durable dispatch or model owner: the caller MUST durably commit the returned
//! batch intent before calling confirm_durable or invoking a worker.

use std::collections::{BTreeMap, VecDeque};
use std::sync::Arc;

use codex_hepta_types::{Digest32, StableId};

const MAX_FEATURES: usize = 4_096;
const MAX_PENDING: usize = 16_384;
const MAX_BATCH_COUNT: usize = 128;
const MAX_BATCH_BYTES: usize = 4 * 1024 * 1024;
const MAX_QUEUED_BYTES: usize = 256 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct BatchLaneKeyV1 {
    pub scope_digest: Digest32,
    pub model_digest: Digest32,
    pub generation: u64,
    pub fence_digest: Digest32,
    pub authority_epoch: u64,
    pub revocation_frontier_digest: Digest32,
}

impl BatchLaneKeyV1 {
    pub fn validate(self) -> Result<(), BatchError> {
        if self.scope_digest.is_zero()
            || self.model_digest.is_zero()
            || self.generation == 0
            || self.fence_digest.is_zero()
            || self.authority_epoch == 0
            || self.revocation_frontier_digest.is_zero()
        {
            return Err(BatchError::InvalidBinding);
        }
        Ok(())
    }
}

/// An immutable feature payload; cloning this descriptor does not copy Q24
/// values. The digest is computed once, with a length-bound canonical encoding.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedFeaturesQ24V1 {
    values: Arc<[i64]>,
    digest: Digest32,
}

impl SharedFeaturesQ24V1 {
    pub fn new(values: Vec<i64>) -> Result<Self, BatchError> {
        if values.is_empty() || values.len() > MAX_FEATURES {
            return Err(BatchError::InvalidFeatures);
        }
        let mut bytes = b"hepta.infer.features.q24.v1".to_vec();
        bytes.extend_from_slice(&(values.len() as u32).to_be_bytes());
        for value in &values {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Self {
            values: Arc::from(values),
            digest: Digest32::of_bytes(&bytes),
        })
    }

    pub fn as_slice(&self) -> &[i64] {
        &self.values
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn byte_len(&self) -> usize {
        self.values.len() * std::mem::size_of::<i64>()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BatchRequestV1 {
    pub operation_id: StableId,
    pub idempotency_digest: Digest32,
    pub lane: BatchLaneKeyV1,
    pub enqueued_at_ms: u64,
    pub deadline_ms: u64,
    pub features: SharedFeaturesQ24V1,
}

impl BatchRequestV1 {
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.infer.batch-request.v1".to_vec();
        bytes.extend_from_slice(self.operation_id.as_str().as_bytes());
        bytes.extend_from_slice(self.idempotency_digest.as_array());
        push_lane(&mut bytes, self.lane);
        bytes.extend_from_slice(&self.enqueued_at_ms.to_be_bytes());
        bytes.extend_from_slice(&self.deadline_ms.to_be_bytes());
        bytes.extend_from_slice(self.features.digest().as_array());
        Digest32::of_bytes(&bytes)
    }

    fn validate(&self) -> Result<(), BatchError> {
        self.lane.validate()?;
        if self.idempotency_digest.is_zero()
            || self.deadline_ms <= self.enqueued_at_ms
            || self.features.as_slice().is_empty()
        {
            return Err(BatchError::InvalidRequest);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BatchPolicyV1 {
    pub max_pending: usize,
    pub max_queued_feature_bytes: usize,
    pub max_batch_count: usize,
    pub max_batch_bytes: usize,
    pub max_queue_delay_ms: u64,
}

impl BatchPolicyV1 {
    pub fn validate(self) -> Result<(), BatchError> {
        if self.max_pending == 0
            || self.max_pending > MAX_PENDING
            || self.max_queued_feature_bytes == 0
            || self.max_queued_feature_bytes > MAX_QUEUED_BYTES
            || self.max_batch_count == 0
            || self.max_batch_count > MAX_BATCH_COUNT
            || self.max_batch_bytes == 0
            || self.max_batch_bytes > MAX_BATCH_BYTES
            || self.max_queue_delay_ms == 0
        {
            return Err(BatchError::InvalidPolicy);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BatchIntentV1 {
    pub lane: BatchLaneKeyV1,
    pub requests: Vec<BatchRequestV1>,
    pub total_feature_bytes: usize,
    pub intent_digest: Digest32,
}

impl BatchIntentV1 {
    fn calculate_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.infer.batch-intent.v1".to_vec();
        push_lane(&mut bytes, self.lane);
        bytes.extend_from_slice(&(self.requests.len() as u32).to_be_bytes());
        bytes.extend_from_slice(&(self.total_feature_bytes as u64).to_be_bytes());
        for request in &self.requests {
            bytes.extend_from_slice(request.digest().as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BatchError {
    InvalidBinding,
    InvalidPolicy,
    InvalidRequest,
    InvalidFeatures,
    CapacityExceeded,
    Conflict,
    DeadlineExpired,
    IntentMismatch,
}

/// A deterministic admission queue. This queue owns no persistence, grant,
/// restart semantics or dispatch authority. Durable request intents and a
/// durable batch-intent acknowledgement are preconditions imposed on its host.
#[derive(Debug)]
pub struct BoundedBatchSchedulerV1 {
    policy: BatchPolicyV1,
    lanes: BTreeMap<BatchLaneKeyV1, VecDeque<BatchRequestV1>>,
    pending: BTreeMap<StableId, Digest32>,
    queued_bytes: usize,
}

impl BoundedBatchSchedulerV1 {
    pub fn new(policy: BatchPolicyV1) -> Result<Self, BatchError> {
        policy.validate()?;
        Ok(Self {
            policy,
            lanes: BTreeMap::new(),
            pending: BTreeMap::new(),
            queued_bytes: 0,
        })
    }

    pub fn admit(&mut self, request: BatchRequestV1) -> Result<bool, BatchError> {
        request.validate()?;
        if request.features.byte_len() > self.policy.max_batch_bytes {
            return Err(BatchError::CapacityExceeded);
        }
        let digest = request.digest();
        if let Some(previous) = self.pending.get(&request.operation_id) {
            return if *previous == digest {
                Ok(false)
            } else {
                Err(BatchError::Conflict)
            };
        }
        if self.pending.len() >= self.policy.max_pending {
            return Err(BatchError::CapacityExceeded);
        }
        let next_bytes = self
            .queued_bytes
            .checked_add(request.features.byte_len())
            .ok_or(BatchError::CapacityExceeded)?;
        if next_bytes > self.policy.max_queued_feature_bytes {
            return Err(BatchError::CapacityExceeded);
        }
        self.queued_bytes = next_bytes;
        self.pending.insert(request.operation_id.clone(), digest);
        self.lanes.entry(request.lane).or_default().push_back(request);
        Ok(true)
    }

    pub fn pending_count(&self) -> usize {
        self.pending.len()
    }

    pub fn queued_feature_bytes(&self) -> usize {
        self.queued_bytes
    }

    /// Peek without removing requests. The host writes/flushes this exact
    /// intent to the durable request ledger BEFORE confirming admission.
    pub fn next_ready(&self, now_ms: u64) -> Result<Option<BatchIntentV1>, BatchError> {
        let mut selected: Option<(u64, BatchLaneKeyV1)> = None;
        for (key, queue) in &self.lanes {
            let Some(front) = queue.front() else {
                continue;
            };
            if front.deadline_ms <= now_ms {
                return Err(BatchError::DeadlineExpired);
            }
            let due = front.enqueued_at_ms.saturating_add(self.policy.max_queue_delay_ms);
            let urgent = front.deadline_ms <= now_ms.saturating_add(self.policy.max_queue_delay_ms);
            let count_ready = queue.len() >= self.policy.max_batch_count;
            if due > now_ms && !urgent && !count_ready {
                continue;
            }
            let candidate = (front.enqueued_at_ms, *key);
            if selected.is_none_or(|best| candidate < best) {
                selected = Some(candidate);
            }
        }
        let Some((_, lane)) = selected else {
            return Ok(None);
        };
        let queue = self.lanes.get(&lane).ok_or(BatchError::IntentMismatch)?;
        let mut requests = Vec::new();
        let mut bytes = 0_usize;
        for request in queue {
            if request.deadline_ms <= now_ms {
                break;
            }
            let next_bytes = bytes.saturating_add(request.features.byte_len());
            if requests.len() >= self.policy.max_batch_count
                || next_bytes > self.policy.max_batch_bytes
            {
                break;
            }
            bytes = next_bytes;
            requests.push(request.clone());
        }
        if requests.is_empty() {
            return Err(BatchError::DeadlineExpired);
        }
        let mut intent = BatchIntentV1 {
            lane,
            requests,
            total_feature_bytes: bytes,
            intent_digest: Digest32::ZERO,
        };
        intent.intent_digest = intent.calculate_digest();
        Ok(Some(intent))
    }

    /// Must be called only after the host durably commits the exact intent.
    /// This method neither writes storage nor invokes a worker. An unknown
    /// durable outcome must be reconciled, never confirmed optimistically.
    pub fn confirm_durable(&mut self, intent: &BatchIntentV1) -> Result<(), BatchError> {
        if intent.requests.is_empty()
            || intent.requests.len() > self.policy.max_batch_count
            || intent.total_feature_bytes > self.policy.max_batch_bytes
            || intent.calculate_digest() != intent.intent_digest
        {
            return Err(BatchError::IntentMismatch);
        }
        let queue = self.lanes.get(&intent.lane).ok_or(BatchError::IntentMismatch)?;
        let front: Vec<_> = queue.iter().take(intent.requests.len()).collect();
        if front.len() != intent.requests.len()
            || !front.iter().zip(&intent.requests).all(|(a, b)| *a == b)
            || intent.total_feature_bytes
                != intent.requests.iter().map(|r| r.features.byte_len()).sum::<usize>()
        {
            return Err(BatchError::IntentMismatch);
        }
        let queue = self.lanes.get_mut(&intent.lane).ok_or(BatchError::IntentMismatch)?;
        for request in &intent.requests {
            let removed = queue.pop_front().ok_or(BatchError::IntentMismatch)?;
            debug_assert_eq!(removed, *request);
            self.pending.remove(&request.operation_id);
            self.queued_bytes -= request.features.byte_len();
        }
        if queue.is_empty() {
            self.lanes.remove(&intent.lane);
        }
        Ok(())
    }
}

fn push_lane(bytes: &mut Vec<u8>, key: BatchLaneKeyV1) {
    for digest in [
        key.scope_digest,
        key.model_digest,
        key.fence_digest,
        key.revocation_frontier_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [key.generation, key.authority_epoch] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
}

#[cfg(test)]
#[path = "bounded_batch_tests.rs"]
mod tests;
