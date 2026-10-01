//! Bounded projection of independently verified time; dispatch performs no IPC.
use crate::BaoAuthBusError;
use crate::BaoAuthBusEvidenceProvider;
use crate::ConsumerEvidenceClient;
use crate::ConsumerPortError;
use codex_hepta_authbus::QuotaReservation;
use codex_hepta_authbus::SettlementStatus;
use codex_hepta_authbus::SignedSettlementEvidence;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_types::Digest32;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

struct Sample {
    wall_ms: u64,
    revision: u64,
    sampled_at: Instant,
    projected_base_ms: u64,
}
pub(crate) struct RuntimeProtectedClock {
    maximum_age: Duration,
    sample: Mutex<Option<Sample>>,
    original_deadline: Mutex<Option<Instant>>,
    fenced: AtomicBool,
}
impl RuntimeProtectedClock {
    pub fn new(maximum_age: Duration) -> Self {
        Self {
            maximum_age,
            sample: Mutex::new(None),
            original_deadline: Mutex::new(None),
            fenced: AtomicBool::new(false),
        }
    }
    pub fn begin_original_deadline(
        self: &Arc<Self>,
        deadline: Instant,
    ) -> Result<RuntimeClockBudget, ConsumerPortError> {
        let mut active = self
            .original_deadline
            .lock()
            .map_err(|_| ConsumerPortError::Unavailable)?;
        if active.is_some() || Instant::now() >= deadline || self.fenced.load(Ordering::Acquire) {
            return Err(ConsumerPortError::Unavailable);
        }
        *active = Some(deadline);
        Ok(RuntimeClockBudget {
            clock: Arc::clone(self),
            deadline,
        })
    }
    fn observe(
        &self,
        time: &SignedTrustedTimeAttestation,
        started: Instant,
    ) -> Result<(), ConsumerPortError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(ConsumerPortError::Unavailable);
        }
        let mut sample = self
            .sample
            .lock()
            .map_err(|_| ConsumerPortError::Unavailable)?;
        if started.elapsed() >= self.maximum_age {
            *sample = None;
            return Err(ConsumerPortError::Unavailable);
        }
        let wall_ms = time.claims.wall_time_ms;
        let revision = time.claims.source_revision;
        let projected = wall_ms
            .checked_add(
                u64::try_from(started.elapsed().as_millis())
                    .map_err(|_| ConsumerPortError::Unavailable)?,
            )
            .ok_or(ConsumerPortError::Unavailable)?;
        let base = if let Some(previous) = sample.as_ref() {
            if wall_ms < previous.wall_ms || revision <= previous.revision {
                self.fenced.store(true, Ordering::Release);
                return Err(ConsumerPortError::Unavailable);
            }
            projected.max(
                previous
                    .projected_base_ms
                    .checked_add(
                        u64::try_from(previous.sampled_at.elapsed().as_millis())
                            .map_err(|_| ConsumerPortError::Unavailable)?,
                    )
                    .ok_or(ConsumerPortError::Unavailable)?,
            )
        } else {
            projected
        };
        *sample = Some(Sample {
            wall_ms,
            revision,
            sampled_at: Instant::now(),
            projected_base_ms: base,
        });
        Ok(())
    }
}
impl AuthorityClock for RuntimeProtectedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        if self.fenced.load(Ordering::Acquire)
            || self
                .original_deadline
                .lock()
                .map_err(|_| AuthorityTrustError::Unavailable)?
                .is_some_and(|deadline| Instant::now() >= deadline)
        {
            return Err(AuthorityTrustError::Unavailable);
        }
        let sample = self
            .sample
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let sample = sample.as_ref().ok_or(AuthorityTrustError::Unavailable)?;
        if sample.sampled_at.elapsed() >= self.maximum_age {
            return Err(AuthorityTrustError::Unavailable);
        }
        sample
            .projected_base_ms
            .checked_add(
                u64::try_from(sample.sampled_at.elapsed().as_millis())
                    .map_err(|_| AuthorityTrustError::Unavailable)?,
            )
            .ok_or(AuthorityTrustError::Unavailable)
    }
}

pub(crate) struct RuntimeClockBudget {
    clock: Arc<RuntimeProtectedClock>,
    deadline: Instant,
}
impl Drop for RuntimeClockBudget {
    fn drop(&mut self) {
        if let Ok(mut active) = self.clock.original_deadline.lock()
            && *active == Some(self.deadline)
        {
            *active = None;
        }
    }
}

pub(crate) struct RuntimeEvidence {
    pub client: ConsumerEvidenceClient,
    pub clock: Arc<RuntimeProtectedClock>,
}
impl BaoAuthBusEvidenceProvider for RuntimeEvidence {
    fn trusted_time(&mut self) -> Result<SignedTrustedTimeAttestation, BaoAuthBusError> {
        let started = Instant::now();
        let time = match self.client.trusted_time() {
            Ok(time) => time,
            Err(error) => {
                self.clock.fenced.store(true, Ordering::Release);
                return Err(error);
            }
        };
        self.clock.observe(&time, started).map_err(|_| {
            BaoAuthBusError::Evidence("protected runtime time unavailable or regressed")
        })?;
        Ok(time)
    }
    fn settlement_evidence(
        &mut self,
        reservation: &QuotaReservation,
        status: SettlementStatus,
        cost: u64,
        terminal: Digest32,
        observed_at_ms: u64,
    ) -> Result<SignedSettlementEvidence, BaoAuthBusError> {
        self.client
            .settlement_evidence(reservation, status, cost, terminal, observed_at_ms)
    }
}

#[cfg(test)]
#[path = "runtime_clock_tests.rs"]
mod tests;
