//! Bounded, authority-free admission and fair microbatch planning for inference intents.
//!
//! The control owner must validate leases, reservations and revocation before
//! enqueue and again at final use. Grouping never issues a grant or dispatches
//! a worker. Each lane has at most one batch of work in memory.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;

use crate::SharedFeatureBufferV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub const MAX_SCHEDULER_PENDING: usize = 16_384;
pub const MAX_MICROBATCH_SIZE: usize = 256;
pub const MAX_LANES_SCANNED_PER_POLL: usize = 64;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct MicrobatchKeyV1 {
    pub scope_id: StableId,
    pub model_digest: Digest32,
    pub generation: Generation,
    pub route_fence: u64,
    pub authority_epoch: u64,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct PhysicalBatchKeyV1 {
    model_digest: Digest32,
    generation: Generation,
    authority_epoch: u64,
}

impl MicrobatchKeyV1 {
    fn physical_key(&self) -> PhysicalBatchKeyV1 {
        PhysicalBatchKeyV1 {
            model_digest: self.model_digest,
            generation: self.generation,
            authority_epoch: self.authority_epoch,
        }
    }

    /// Physical batch compatibility is weaker than authorization identity.
    /// Full scope/fence binding stays with each intent and is verified again
    /// by the final-use owner; only the model, worker generation and epoch
    /// may be shared by the native backend.
    pub fn physical_compatible_with(&self, other: &Self) -> bool {
        self.model_digest == other.model_digest
            && self.generation == other.generation
            && self.authority_epoch == other.authority_epoch
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InferenceIntentV1 {
    pub request_id: StableId,
    pub key: MicrobatchKeyV1,
    pub feature_digest: Digest32,
    /// Optional immutable payload shared across batch consumers.
    pub shared_features: Option<SharedFeatureBufferV1>,
    pub deadline_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MicrobatchLimitsV1 {
    pub max_pending: usize,
    pub max_batch_size: usize,
    pub max_lanes_per_poll: usize,
    pub max_wait_ms: u64,
}

impl MicrobatchLimitsV1 {
    pub fn validate(self) -> Result<Self, SchedulerErrorV1> {
        if self.max_pending == 0
            || self.max_pending > MAX_SCHEDULER_PENDING
            || self.max_batch_size == 0
            || self.max_batch_size > MAX_MICROBATCH_SIZE
            || self.max_batch_size > self.max_pending
            || self.max_lanes_per_poll == 0
            || self.max_lanes_per_poll > MAX_LANES_SCANNED_PER_POLL
            || self.max_wait_ms == 0
        {
            return Err(SchedulerErrorV1::InvalidLimits);
        }
        Ok(self)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SchedulerErrorV1 {
    InvalidLimits,
    Capacity,
    LaneCapacity,
    DuplicateRequest,
    EmptyDigest,
    FeatureMismatch,
    InvalidFence,
    Expired,
    ClockRegressed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MicrobatchPlanV1 {
    /// Representative lane key. A physical batch may contain different
    /// scope IDs and route fences: check requests[i].key at final use.
    pub key: MicrobatchKeyV1,
    pub requests: Vec<InferenceIntentV1>,
    pub oldest_queue_age_ms: u64,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MicrobatchPollV1 {
    pub batch: Option<MicrobatchPlanV1>,
    pub expired_request_ids: Vec<StableId>,
    pub scanned_lanes: usize,
    pub pending: usize,
}

#[derive(Clone, Debug)]
struct QueuedIntent {
    intent: InferenceIntentV1,
    enqueued_at_ms: u64,
}

/// Local planner, not a durable ledger and not a control-plane cache.
/// The product owner is responsible for replay-safe completion accounting.
#[derive(Debug)]
pub struct BoundedMicrobatchSchedulerV1 {
    limits: MicrobatchLimitsV1,
    lanes: BTreeMap<MicrobatchKeyV1, VecDeque<QueuedIntent>>,
    // Secondary affinity index; never conflates per-scope authorization.
    physical_lanes: BTreeMap<PhysicalBatchKeyV1, BTreeSet<MicrobatchKeyV1>>,
    physical_cursor: BTreeMap<PhysicalBatchKeyV1, MicrobatchKeyV1>,
    round_robin: VecDeque<MicrobatchKeyV1>,
    queued_ids: BTreeSet<StableId>,
    last_now_ms: Option<u64>,
}

impl BoundedMicrobatchSchedulerV1 {
    pub fn new(limits: MicrobatchLimitsV1) -> Result<Self, SchedulerErrorV1> {
        Ok(Self {
            limits: limits.validate()?,
            lanes: BTreeMap::new(),
            physical_lanes: BTreeMap::new(),
            physical_cursor: BTreeMap::new(),
            round_robin: VecDeque::new(),
            queued_ids: BTreeSet::new(),
            last_now_ms: None,
        })
    }

    pub fn pending(&self) -> usize {
        self.queued_ids.len()
    }

    pub fn active_lanes(&self) -> usize {
        self.lanes.len()
    }

    fn remove_physical_lane(&mut self, key: &MicrobatchKeyV1) {
        let group = key.physical_key();
        if let Some(members) = self.physical_lanes.get_mut(&group) {
            members.remove(key);
            if members.is_empty() {
                self.physical_lanes.remove(&group);
                self.physical_cursor.remove(&group);
            }
        }
    }

    // Cross-scope coalescing deliberately leaves stale round-robin slots.
    // Rebuild infrequently and outside any global control lock rather than
    // scanning all scopes for every physical model batch.
    fn compact_round_robin_if_needed(&mut self) {
        let limit = self
            .lanes
            .len()
            .saturating_mul(2)
            .saturating_add(self.limits.max_batch_size);
        if self.round_robin.len() > limit {
            self.round_robin.retain(|key| self.lanes.contains_key(key));
        }
    }

    fn clock(&mut self, now_ms: u64) -> Result<(), SchedulerErrorV1> {
        if self.last_now_ms.is_some_and(|last| now_ms < last) {
            return Err(SchedulerErrorV1::ClockRegressed);
        }
        self.last_now_ms = Some(now_ms);
        Ok(())
    }

    pub fn enqueue(
        &mut self,
        now_ms: u64,
        intent: InferenceIntentV1,
    ) -> Result<(), SchedulerErrorV1> {
        self.clock(now_ms)?;
        if intent.key.model_digest.is_zero() || intent.feature_digest.is_zero() {
            return Err(SchedulerErrorV1::EmptyDigest);
        }
        if intent
            .shared_features
            .as_ref()
            .is_some_and(|buffer| buffer.digest() != intent.feature_digest)
        {
            return Err(SchedulerErrorV1::FeatureMismatch);
        }
        if intent.key.route_fence == 0 || intent.key.authority_epoch == 0 {
            return Err(SchedulerErrorV1::InvalidFence);
        }
        if intent.deadline_ms <= now_ms {
            return Err(SchedulerErrorV1::Expired);
        }
        if self.queued_ids.contains(&intent.request_id) {
            return Err(SchedulerErrorV1::DuplicateRequest);
        }
        if self.pending() >= self.limits.max_pending {
            return Err(SchedulerErrorV1::Capacity);
        }
        if self
            .lanes
            .get(&intent.key)
            .is_some_and(|lane| lane.len() >= self.limits.max_batch_size)
        {
            return Err(SchedulerErrorV1::LaneCapacity);
        }
        let key = intent.key.clone();
        let id = intent.request_id.clone();
        if !self.lanes.contains_key(&key) {
            self.round_robin.push_back(key.clone());
            self.physical_lanes
                .entry(key.physical_key())
                .or_default()
                .insert(key.clone());
        }
        self.lanes.entry(key).or_default().push_back(QueuedIntent {
            intent,
            enqueued_at_ms: now_ms,
        });
        self.queued_ids.insert(id);
        Ok(())
    }

    /// At most max_lanes_per_poll lanes and max_batch_size entries per lane are
    /// visited. Calling poll repeatedly advances the round-robin cursor.
    /// Expired intents never enter a returned batch.
    pub fn poll(&mut self, now_ms: u64) -> Result<MicrobatchPollV1, SchedulerErrorV1> {
        self.clock(now_ms)?;
        let mut expired = Vec::new();
        let mut selected = None;
        let scans = self.round_robin.len().min(self.limits.max_lanes_per_poll);
        let mut scanned = 0;
        for _ in 0..scans {
            let Some(key) = self.round_robin.pop_front() else {
                break;
            };
            let Some(mut lane) = self.lanes.remove(&key) else {
                // Coalescing may leave a retired round-robin slot. It must not
                // consume the active-lane scan budget of the next poll.
                continue;
            };
            scanned += 1;
            // A lane cannot exceed one batch: expiry is bounded without a
            // global queue scan, including out-of-order deadlines.
            lane.retain(|queued| {
                if queued.intent.deadline_ms <= now_ms {
                    expired.push(queued.intent.request_id.clone());
                    self.queued_ids.remove(&queued.intent.request_id);
                    false
                } else {
                    true
                }
            });
            if lane.is_empty() {
                self.remove_physical_lane(&key);
                continue;
            }
            let oldest = lane.front().map_or(now_ms, |entry| entry.enqueued_at_ms);
            let deadline_due = lane.iter().any(|entry| {
                entry.intent.deadline_ms <= now_ms.saturating_add(self.limits.max_wait_ms)
            });
            let ready = lane.len() == self.limits.max_batch_size
                || now_ms.saturating_sub(oldest) >= self.limits.max_wait_ms
                || deadline_due;
            if ready {
                let mut requests = Vec::with_capacity(lane.len());
                for entry in lane {
                    self.queued_ids.remove(&entry.intent.request_id);
                    requests.push(entry.intent);
                }
                self.remove_physical_lane(&key);
                selected = Some(MicrobatchPlanV1 {
                    key,
                    requests,
                    oldest_queue_age_ms: now_ms.saturating_sub(oldest),
                    authority: AuthorityPosture::DENY_ALL,
                });
                break;
            }
            self.round_robin.push_back(key.clone());
            self.lanes.insert(key, lane);
        }
        Ok(MicrobatchPollV1 {
            batch: selected,
            expired_request_ids: expired,
            scanned_lanes: scanned,
            pending: self.pending(),
        })
    }

    /// Drain a ready batch and coalesce compatible work from other scope lanes
    /// without changing any per-request authorization/fence key. The scan is
    /// bounded by max_lanes_per_poll, and the native batch by max_batch_size.
    /// The worker must separately verify each original scope binding.
    pub fn poll_physically_compatible(
        &mut self,
        now_ms: u64,
    ) -> Result<MicrobatchPollV1, SchedulerErrorV1> {
        let mut observed = self.poll(now_ms)?;
        let Some(batch) = observed.batch.as_mut() else {
            self.compact_round_robin_if_needed();
            return Ok(observed);
        };
        if batch.requests.len() >= self.limits.max_batch_size {
            self.compact_round_robin_if_needed();
            return Ok(observed);
        }
        let group_key = batch.key.physical_key();
        let remaining_scans = self
            .limits
            .max_lanes_per_poll
            .saturating_sub(observed.scanned_lanes);
        // Scan only physically compatible lanes, with a rotating cursor so
        // cold scopes are not starved by frequently replenished low IDs.
        let mut candidates = Vec::new();
        if let Some(group) = self.physical_lanes.get(&group_key) {
            if let Some(cursor) = self.physical_cursor.get(&group_key) {
                candidates.extend(
                    group
                        .range((
                            std::ops::Bound::Excluded(cursor.clone()),
                            std::ops::Bound::Unbounded,
                        ))
                        .take(remaining_scans)
                        .cloned(),
                );
                if candidates.len() < remaining_scans {
                    candidates.extend(
                        group
                            .range(..=cursor.clone())
                            .take(remaining_scans - candidates.len())
                            .cloned(),
                    );
                }
            } else {
                candidates.extend(group.iter().take(remaining_scans).cloned());
            }
        }
        let mut last_scanned = None;
        for key in candidates {
            observed.scanned_lanes += 1;
            last_scanned = Some(key.clone());
            let Some(mut lane) = self.lanes.remove(&key) else {
                self.remove_physical_lane(&key);
                continue;
            };
            lane.retain(|queued| {
                if queued.intent.deadline_ms <= now_ms {
                    observed
                        .expired_request_ids
                        .push(queued.intent.request_id.clone());
                    self.queued_ids.remove(&queued.intent.request_id);
                    false
                } else {
                    true
                }
            });
            // The group index is a planning optimization, never authority.
            if key.physical_compatible_with(&batch.key) {
                let oldest = lane.front().map(|entry| entry.enqueued_at_ms);
                let slots = self.limits.max_batch_size - batch.requests.len();
                for _ in 0..slots.min(lane.len()) {
                    if let Some(entry) = lane.pop_front() {
                        self.queued_ids.remove(&entry.intent.request_id);
                        batch.requests.push(entry.intent);
                    }
                }
                if let Some(oldest) = oldest {
                    batch.oldest_queue_age_ms =
                        batch.oldest_queue_age_ms.max(now_ms.saturating_sub(oldest));
                }
            }
            if lane.is_empty() {
                self.remove_physical_lane(&key);
            } else {
                self.lanes.insert(key, lane);
            }
            if batch.requests.len() >= self.limits.max_batch_size {
                break;
            }
        }
        if let Some(key) = last_scanned {
            if self.physical_lanes.contains_key(&group_key) {
                self.physical_cursor.insert(group_key, key);
            }
        }
        observed.pending = self.pending();
        self.compact_round_robin_if_needed();
        Ok(observed)
    }

    /// Explicit fence cutover: drop queued work for a scope whose binding no
    /// longer matches the independently admitted generation/fence/epoch.
    /// Call outside global control locks. No stale work is requeued.
    pub fn retain_scope_binding(
        &mut self,
        scope: &StableId,
        generation: Generation,
        route_fence: u64,
        authority_epoch: u64,
    ) -> Vec<StableId> {
        let mut dropped = Vec::new();
        let mut retired_lanes = Vec::new();
        self.lanes.retain(|key, lane| {
            if &key.scope_id == scope
                && (key.generation != generation
                    || key.route_fence != route_fence
                    || key.authority_epoch != authority_epoch)
            {
                for entry in lane {
                    self.queued_ids.remove(&entry.intent.request_id);
                    dropped.push(entry.intent.request_id.clone());
                }
                retired_lanes.push(key.clone());
                false
            } else {
                true
            }
        });
        for key in &retired_lanes {
            self.remove_physical_lane(key);
        }
        self.round_robin.retain(|key| self.lanes.contains_key(key));
        dropped
    }
}

#[cfg(test)]
#[path = "microbatch_tests.rs"]
mod tests;
