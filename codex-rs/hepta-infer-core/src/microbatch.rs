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
    /// Ticket order makes a single lane removal independent of other scopes.
    round_robin: BTreeSet<(u128, MicrobatchKeyV1)>,
    lane_order: BTreeMap<MicrobatchKeyV1, u128>,
    scope_lanes: BTreeMap<StableId, BTreeSet<MicrobatchKeyV1>>,
    next_order: u128,
    queued_ids: BTreeSet<StableId>,
    last_now_ms: Option<u64>,
}

impl BoundedMicrobatchSchedulerV1 {
    pub fn new(limits: MicrobatchLimitsV1) -> Result<Self, SchedulerErrorV1> {
        Ok(Self {
            limits: limits.validate()?,
            lanes: BTreeMap::new(),
            round_robin: BTreeSet::new(),
            lane_order: BTreeMap::new(),
            scope_lanes: BTreeMap::new(),
            next_order: 0,
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

    /// Each active lane has exactly one ticket. The extremely rare u128
    /// rollover renumbers only live lanes, in original fairness order.
    fn next_lane_order(&mut self) -> u128 {
        if self.next_order == u128::MAX {
            let ordered = self
                .round_robin
                .iter()
                .map(|(_, key)| key.clone())
                .collect::<Vec<_>>();
            self.round_robin.clear();
            self.lane_order.clear();
            self.next_order = 0;
            for key in ordered {
                self.next_order += 1;
                self.round_robin.insert((self.next_order, key.clone()));
                self.lane_order.insert(key, self.next_order);
            }
        }
        self.next_order += 1;
        self.next_order
    }

    fn remove_scope_key(&mut self, key: &MicrobatchKeyV1) {
        let empty = self.scope_lanes.get_mut(&key.scope_id).is_some_and(|keys| {
            keys.remove(key);
            keys.is_empty()
        });
        if empty {
            self.scope_lanes.remove(&key.scope_id);
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
            let order = self.next_lane_order();
            self.round_robin.insert((order, key.clone()));
            self.lane_order.insert(key.clone(), order);
            self.scope_lanes
                .entry(key.scope_id.clone())
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
            let Some((_, key)) = self.round_robin.pop_first() else {
                break;
            };
            scanned += 1;
            self.lane_order.remove(&key);
            let Some(mut lane) = self.lanes.remove(&key) else {
                self.remove_scope_key(&key);
                continue;
            };
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
                self.remove_scope_key(&key);
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
                self.remove_scope_key(&key);
                selected = Some(MicrobatchPlanV1 {
                    key,
                    requests,
                    oldest_queue_age_ms: now_ms.saturating_sub(oldest),
                    authority: AuthorityPosture::DENY_ALL,
                });
                break;
            }
            let order = self.next_lane_order();
            self.round_robin.insert((order, key.clone()));
            self.lane_order.insert(key.clone(), order);
            self.lanes.insert(key, lane);
        }
        Ok(MicrobatchPollV1 {
            batch: selected,
            expired_request_ids: expired,
            scanned_lanes: scanned,
            pending: self.pending(),
        })
    }

    /// Explicit fence cutover: visit only indexed lanes belonging to this
    /// scope, never scan other scopes or the global scheduling queue.
    /// Call outside global control locks. No stale work is requeued.
    pub fn retain_scope_binding(
        &mut self,
        scope: &StableId,
        generation: Generation,
        route_fence: u64,
        authority_epoch: u64,
    ) -> Vec<StableId> {
        let mut dropped = Vec::new();
        let keys = self
            .scope_lanes
            .get(scope)
            .into_iter()
            .flat_map(|keys| keys.iter().cloned())
            .collect::<Vec<_>>();
        for key in keys {
            if key.generation == generation
                && key.route_fence == route_fence
                && key.authority_epoch == authority_epoch
            {
                continue;
            }
            if let Some(lane) = self.lanes.remove(&key) {
                for entry in lane {
                    self.queued_ids.remove(&entry.intent.request_id);
                    dropped.push(entry.intent.request_id);
                }
            }
            if let Some(order) = self.lane_order.remove(&key) {
                self.round_robin.remove(&(order, key.clone()));
            }
            self.remove_scope_key(&key);
        }
        dropped
    }
}

#[cfg(test)]
#[path = "microbatch_tests.rs"]
mod tests;
