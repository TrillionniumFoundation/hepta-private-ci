//! Derived, owner-local indexes. Canonical snapshots contain only primary rows.
use std::collections::BTreeMap;

use super::AttemptIdentity;
use super::DurableFederationStateV1;
use super::FEDERATION_RECOVERY_CLEANUP_BATCH;
use super::FederationRecoveryError;

impl DurableFederationStateV1 {
    /// Stage trusted, owner-local state without a JSON encode/decode round trip.
    /// The caller still must store the complete canonical snapshot successfully
    /// before installing this staged state or exposing an admission/response.
    pub(crate) fn stage_at(&self, now_unix_ms: u64) -> Result<Self, FederationRecoveryError> {
        if now_unix_ms == 0 {
            return Err(FederationRecoveryError::ZeroObservationTime);
        }
        if now_unix_ms < self.last_observed_unix_ms {
            return Err(FederationRecoveryError::ClockRegression);
        }
        let mut next = self.clone();
        next.observe_time(now_unix_ms)?;
        next.purge_expired(now_unix_ms);
        Ok(next)
    }

    pub(super) fn purge_expired(&mut self, now_unix_ms: u64) {
        self.purge_expired_up_to(now_unix_ms, FEDERATION_RECOVERY_CLEANUP_BATCH);
    }

    /// Bound maintenance independently from live table size. Residual expired
    /// entries may cause conservative backpressure, never live-fence eviction.
    pub fn purge_expired_bounded(
        &mut self,
        now_unix_ms: u64,
        maximum_records: usize,
    ) -> Result<usize, FederationRecoveryError> {
        self.observe_time(now_unix_ms)?;
        Ok(self.purge_expired_up_to(now_unix_ms, maximum_records))
    }

    fn purge_expired_up_to(&mut self, now_unix_ms: u64, maximum_records: usize) -> usize {
        let mut removed = 0;
        while removed < maximum_records {
            let replay = self
                .replay_expiries
                .first()
                .copied()
                .filter(|(expiry, _)| *expiry <= now_unix_ms);
            let attempt = self
                .attempt_expiries
                .first()
                .filter(|(expiry, _)| *expiry <= now_unix_ms)
                .cloned();
            if let Some((expiry, key)) = replay
                && attempt.as_ref().is_none_or(|(at, _)| expiry <= *at)
            {
                self.replay_expiries.remove(&(expiry, key));
                if let Some(entry) = self.replay.remove(&key) {
                    decrement_count(&mut self.replay_counts, &entry.peer_id);
                }
            } else if let Some((_, identity)) = attempt {
                self.remove_attempt(&identity);
            } else {
                break;
            }
            removed += 1;
        }
        removed
    }

    pub(super) fn remove_attempt(&mut self, identity: &AttemptIdentity) {
        if let Some(entry) = self.attempts.remove(identity) {
            self.attempt_expiries
                .remove(&(entry.expires_unix_ms, identity.clone()));
            decrement_count(&mut self.attempt_counts, &identity.peer_id);
        }
    }

    pub(super) fn rebuild_indexes(&mut self) {
        self.replay_counts.clear();
        self.attempt_counts.clear();
        self.replay_expiries.clear();
        self.attempt_expiries.clear();
        for (key, entry) in &self.replay {
            self.replay_expiries.insert((entry.expires_unix_ms, *key));
            *self.replay_counts.entry(entry.peer_id.clone()).or_default() += 1;
        }
        for (identity, entry) in &self.attempts {
            self.attempt_expiries
                .insert((entry.expires_unix_ms, identity.clone()));
            *self
                .attempt_counts
                .entry(identity.peer_id.clone())
                .or_default() += 1;
        }
    }
}

fn decrement_count(counts: &mut BTreeMap<String, usize>, peer: &str) {
    if let Some(count) = counts.get_mut(peer) {
        *count -= 1;
        if *count == 0 {
            counts.remove(peer);
        }
    }
}
