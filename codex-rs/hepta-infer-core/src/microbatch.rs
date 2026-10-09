//! Bounded, authority-free admission and fair microbatch planning for inference intents.
//!
//! The control owner must validate leases, reservations and revocation before
//! enqueue and again at final use. Grouping never issues a grant or dispatches
//! a worker. Each lane has at most one batch of work in memory.

use std::collections::{BTreeMap, BTreeSet, VecDeque};

use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};
use crate::SharedFeatureBufferV1;

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
    round_robin: VecDeque<MicrobatchKeyV1>,
    queued_ids: BTreeSet<StableId>,
    last_now_ms: Option<u64>,
}

impl BoundedMicrobatchSchedulerV1 {
    pub fn new(limits: MicrobatchLimitsV1) -> Result<Self, SchedulerErrorV1> {
        Ok(Self {
            limits: limits.validate()?,
            lanes: BTreeMap::new(),
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
        if intent.shared_features.as_ref().is_some_and(|buffer| buffer.digest() != intent.feature_digest) {
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
        if self.lanes.get(&intent.key).is_some_and(|lane| lane.len() >= self.limits.max_batch_size) {
            return Err(SchedulerErrorV1::LaneCapacity);
        }
        let key = intent.key.clone();
        let id = intent.request_id.clone();
        if !self.lanes.contains_key(&key) {
            self.round_robin.push_back(key.clone());
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
            scanned += 1;
            let Some(mut lane) = self.lanes.remove(&key) else {
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
                false
            } else {
                true
            }
        });
        self.round_robin.retain(|key| self.lanes.contains_key(key));
        dropped
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Instant;

    fn id(s: &str) -> StableId { StableId::new(s).unwrap() }
    fn digest(s: &str) -> Digest32 { Digest32::of_bytes(s.as_bytes()) }
    fn limits() -> MicrobatchLimitsV1 {
        MicrobatchLimitsV1 { max_pending: 16_384, max_batch_size: 4, max_lanes_per_poll: 64, max_wait_ms: 10 }
    }
    fn intent(request: &str, scope: &str, generation: u64, fence: u64, deadline: u64) -> InferenceIntentV1 {
        InferenceIntentV1 {
            request_id: id(request),
            key: MicrobatchKeyV1 {
                scope_id: id(scope),
                model_digest: digest("model"),
                generation: Generation::new(generation).unwrap(),
                route_fence: fence,
                authority_epoch: 1,
            },
            feature_digest: digest("feature"),
            shared_features: None,
            deadline_ms: deadline,
        }
    }

    #[test]
    fn never_mix_scope_generation_or_fence() {
        let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
        q.enqueue(1, intent("a", "scopeA", 1, 1, 100)).unwrap();
        q.enqueue(1, intent("b", "scopeA", 1, 2, 100)).unwrap();
        q.enqueue(1, intent("c", "scopeB", 1, 1, 100)).unwrap();
        q.enqueue(1, intent("d", "scopeA", 2, 1, 100)).unwrap();
        let mut got = BTreeSet::new();
        for _ in 0..4 {
            let batch = q.poll(11).unwrap().batch.unwrap();
            assert_eq!(batch.requests.len(), 1);
            assert_eq!(batch.requests[0].key, batch.key);
            assert_eq!(batch.authority, AuthorityPosture::DENY_ALL);
            got.insert(batch.requests[0].request_id.clone());
        }
        assert_eq!(got.len(), 4);
        assert_eq!(q.pending(), 0);
    }

    #[test]
    fn immutable_payload_is_shared_without_vector_copy() {
        let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
        let buffer = SharedFeatureBufferV1::from_vec(vec![0, 1 << 24]).unwrap();
        let mut request = intent("payload", "scope", 1, 1, 100);
        request.feature_digest = buffer.digest();
        request.shared_features = Some(buffer.clone());
        q.enqueue(1, request).unwrap();
        let plan = q.poll(11).unwrap().batch.unwrap();
        assert!(plan.requests[0].shared_features.as_ref().unwrap().shares_allocation_with(&buffer));
    }

    #[test]
    fn capacity_duplicate_and_expired_fail_closed() {
        let mut conf = limits();
        conf.max_pending = 1;
        let mut q = BoundedMicrobatchSchedulerV1::new(conf).unwrap();
        q.enqueue(1, intent("a", "one", 1, 1, 50)).unwrap();
        assert_eq!(q.enqueue(1, intent("a", "one", 1, 1, 50)), Err(SchedulerErrorV1::DuplicateRequest));
        assert_eq!(q.enqueue(1, intent("b", "two", 1, 1, 50)), Err(SchedulerErrorV1::Capacity));
        let p = q.poll(51).unwrap();
        assert_eq!(p.expired_request_ids, vec![id("a")]);
        assert!(p.batch.is_none());
        assert_eq!(q.pending(), 0);
        assert_eq!(q.enqueue(50, intent("x", "s", 1, 1, 100)), Err(SchedulerErrorV1::ClockRegressed));
    }

    #[test]
    fn cutover_drops_only_stale_scope() {
        let mut q = BoundedMicrobatchSchedulerV1::new(limits()).unwrap();
        q.enqueue(1, intent("old", "scope", 1, 1, 100)).unwrap();
        q.enqueue(1, intent("new", "scope", 2, 2, 100)).unwrap();
        q.enqueue(1, intent("other", "another", 1, 1, 100)).unwrap();
        assert_eq!(q.retain_scope_binding(&id("scope"), Generation::new(2).unwrap(), 2, 1), vec![id("old")]);
        assert_eq!(q.pending(), 2);
        assert_eq!(q.active_lanes(), 2);
    }

    // Opt-in source benchmark: not hardware acceptance, report raw durations.
    #[test]
    #[ignore = "run with --ignored --nocapture on deployment hardware"]
    fn benchmark_64_256_1024_4096_scopes() {
        for scopes in [64, 256, 1024, 4096] {
            let conf = MicrobatchLimitsV1 {
                max_pending: 16_384, max_batch_size: 4,
                max_lanes_per_poll: 64, max_wait_ms: 10,
            };
            let mut q = BoundedMicrobatchSchedulerV1::new(conf).unwrap();
            let start = Instant::now();
            for i in 0..scopes {
                let name = format!("scope{i}");
                q.enqueue(1, intent(&format!("req{i}"), &name, 1, 1, 1000)).unwrap();
            }
            let admission = start.elapsed();
            let start = Instant::now();
            let mut count = 0;
            while q.pending() != 0 {
                if let Some(batch) = q.poll(20).unwrap().batch {
                    count += batch.requests.len();
                }
            }
            assert_eq!(count, scopes);
            eprintln!("scopes={scopes} admission_us={} drain_us={}", admission.as_micros(), start.elapsed().as_micros());
        }
    }
}
