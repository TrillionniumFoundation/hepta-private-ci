//! Physical batching across independently fenced Cell scopes.
//!
//! Compatibility is a *compute* constraint, not an authority grant. Every
//! retained intent still carries its exact original scope/route-fence and
//! must receive an independently signed final-use grant at the worker.

use super::*;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PhysicalBatchCompatibilityV1 {
    pub model_digest: Digest32,
    pub encoder_digest: Digest32,
    pub generation: Generation,
    pub authority_epoch: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PhysicalMicrobatchPlanV1 {
    pub compatibility: PhysicalBatchCompatibilityV1,
    pub requests: Vec<InferenceIntentV1>,
    pub oldest_queue_age_ms: u64,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PhysicalMicrobatchPollV1 {
    pub batch: Option<PhysicalMicrobatchPlanV1>,
    pub expired_request_ids: Vec<StableId>,
    pub scanned_lanes: usize,
    pub pending: usize,
}

impl BoundedMicrobatchSchedulerV1 {
    /// Collect up to one bounded physical batch across compatible scopes.
    ///
    /// At most max_lanes_per_poll per-scope lanes are inspected. The scheduler
    /// never coalesces different model/encoder/generation/authority epochs, and
    /// never erases per-request scope/fence identity. No input can bypass
    /// worker-side signed final-use and payload identity verification.
    pub fn poll_physical_compatible(
        &mut self,
        now_ms: u64,
    ) -> Result<PhysicalMicrobatchPollV1, SchedulerErrorV1> {
        self.clock(now_ms)?;
        let scans = self.round_robin.len().min(self.limits.max_lanes_per_poll);
        let mut scanned = 0_usize;
        let mut expired = Vec::new();
        let mut selected: Option<PhysicalBatchCompatibilityV1> = None;
        let mut requests = Vec::new();
        let mut oldest_queue_age_ms = 0_u64;

        for _ in 0..scans {
            let Some(key) = self.round_robin.pop_front() else {
                break;
            };
            scanned += 1;
            let Some(mut lane) = self.lanes.remove(&key) else {
                continue;
            };
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
            let ready = lane.len() == self.limits.max_batch_size
                || now_ms.saturating_sub(oldest) >= self.limits.max_wait_ms
                || lane.iter().any(|entry| {
                    entry.intent.deadline_ms <= now_ms.saturating_add(self.limits.max_wait_ms)
                });
            let encoder = lane.front().and_then(|entry| entry.intent.encoder_digest);
            if ready && let Some(encoder_digest) = encoder {
                let compatible = PhysicalBatchCompatibilityV1 {
                    model_digest: key.model_digest,
                    encoder_digest,
                    generation: key.generation,
                    authority_epoch: key.authority_epoch,
                };
                if selected.is_none_or(|current| current == compatible) {
                    let space = self.limits.max_batch_size.saturating_sub(requests.len());
                    if space != 0 {
                        selected = Some(compatible);
                        let taken = space.min(lane.len());
                        for _ in 0..taken {
                            if let Some(entry) = lane.pop_front() {
                                oldest_queue_age_ms = oldest_queue_age_ms
                                    .max(now_ms.saturating_sub(entry.enqueued_at_ms));
                                self.queued_ids.remove(&entry.intent.request_id);
                                requests.push(entry.intent);
                            }
                        }
                    }
                }
            }
            if !lane.is_empty() {
                self.round_robin.push_back(key.clone());
                self.lanes.insert(key, lane);
            }
            if requests.len() >= self.limits.max_batch_size {
                break;
            }
        }

        Ok(PhysicalMicrobatchPollV1 {
            batch: selected.map(|compatibility| PhysicalMicrobatchPlanV1 {
                compatibility,
                requests,
                oldest_queue_age_ms,
                authority: AuthorityPosture::DENY_ALL,
            }),
            expired_request_ids: expired,
            scanned_lanes: scanned,
            pending: self.pending(),
        })
    }
}

#[cfg(test)]
#[path = "microbatch_compatible_tests.rs"]
mod tests;
