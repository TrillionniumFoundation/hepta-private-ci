//! Bounded read-only cache. Authority callbacks sample BOOTTIME and retained
//! memory only; no filesystem, network or durable owner callback occurs here.
//! First memory-lock admission may wait only within the same original
//! observation's remaining request-age budget. Returned failures are never retried.
use crate::AgentdRootAuthorityError;
use crate::HOST_AUTHORITY_OBSERVATION_V2;
use crate::HostAuthorityObservationResponseV2;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::TryLockError;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

pub(crate) const MAX_AGE_NS: u64 = 500_000_000;
struct Retained {
    observation: Arc<HostAuthorityObservationResponseV2>,
    request_started_ns: u64,
    last_checked_ns: u64,
}
pub(crate) struct RootObservationCache {
    boot_id: String,
    retained: Mutex<Option<Retained>>,
    fenced: AtomicBool,
    // This mirror only bounds first read admission. The retained response is
    // still the sole evidence, and its original request start is revalidated.
    read_deadline_ns: AtomicU64,
    // Even means stable; odd means the original consumer update is active.
    // A read keeps one generation, so a complete update cannot pass as ABA.
    update_generation: AtomicU64,
    #[cfg(test)]
    admission_waits: std::sync::atomic::AtomicUsize,
    #[cfg(test)]
    expired_admission_deadline: AtomicU64,
    #[cfg(test)]
    expired_admission_sample: AtomicU64,
}

#[derive(Clone, Copy)]
struct ReadAdmission {
    deadline_ns: u64,
    generation: u64,
}
impl RootObservationCache {
    pub(crate) fn new(boot_id: String) -> Self {
        Self {
            boot_id,
            retained: Mutex::new(None),
            fenced: AtomicBool::new(false),
            read_deadline_ns: AtomicU64::new(0),
            update_generation: AtomicU64::new(0),
            #[cfg(test)]
            admission_waits: std::sync::atomic::AtomicUsize::new(0),
            #[cfg(test)]
            expired_admission_deadline: AtomicU64::new(0),
            #[cfg(test)]
            expired_admission_sample: AtomicU64::new(0),
        }
    }
    pub(crate) fn fence(&self) {
        self.fenced.store(true, Ordering::Release);
    }
    pub(crate) fn begin_update(&self) {
        if self
            .update_generation
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |generation| {
                if generation & 1 == 0 {
                    generation.checked_add(1)
                } else {
                    None
                }
            })
            .is_err()
        {
            self.fence();
        }
    }
    pub(crate) fn end_update(&self) {
        if self
            .update_generation
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |generation| {
                if generation & 1 != 0 {
                    generation.checked_add(1)
                } else {
                    None
                }
            })
            .is_err()
        {
            self.fence();
        }
    }
    pub(crate) fn revocations_match(
        &self,
        head: &codex_hepta_contracts::FinalUseRevocations,
    ) -> bool {
        self.retained
            .lock()
            .ok()
            .and_then(|slot| {
                slot.as_ref()
                    .map(|value| value.observation.revocations == *head)
            })
            .unwrap_or(false)
    }
    pub(crate) fn accept(
        &self,
        observation: HostAuthorityObservationResponseV2,
        started: u64,
        ended: u64,
    ) -> Result<(), AgentdRootAuthorityError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        let mut sampled = None;
        let result = (|| {
            let mut slot = self.lock_retained_for_accept()?;
            // Sample only after the original guard is held. A reader which
            // finished while this writer waited must not look like rollback.
            let now = boottime_ns().inspect_err(|_error| {
                #[cfg(test)]
                eprintln!("ROOT_OBSERVATION_CACHE phase=accept reason=boottime-sample-failed");
            })?;
            sampled = Some(now);
            self.accept_locked(&mut slot, observation, started, ended, now)
        })();
        self.finish_accept(result, started, ended, sampled)
    }

    #[cfg(test)]
    fn accept_at(
        &self,
        observation: HostAuthorityObservationResponseV2,
        started: u64,
        ended: u64,
        now: u64,
    ) -> Result<(), AgentdRootAuthorityError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        let result = (|| {
            let mut slot = self.lock_retained_for_accept()?;
            self.accept_locked(&mut slot, observation, started, ended, now)
        })();
        self.finish_accept(result, started, ended, Some(now))
    }

    fn lock_retained_for_accept(
        &self,
    ) -> Result<MutexGuard<'_, Option<Retained>>, AgentdRootAuthorityError> {
        self.retained.lock().map_err(|_| {
            #[cfg(test)]
            eprintln!("ROOT_OBSERVATION_CACHE phase=accept reason=retained-lock-poisoned");
            AgentdRootAuthorityError::Unavailable
        })
    }

    fn accept_locked(
        &self,
        slot: &mut Option<Retained>,
        observation: HostAuthorityObservationResponseV2,
        started: u64,
        ended: u64,
        now: u64,
    ) -> Result<(), AgentdRootAuthorityError> {
        let clock = &observation.clock;
        let head = &observation.revocations;
        if observation.schema_version != 2
            || observation.operation != HOST_AUTHORITY_OBSERVATION_V2
            || observation.authority_epoch == 0
            || head.authority_epoch != observation.authority_epoch
            || head.revision == 0
            || head.revoked_grant_ids.len() > 16_384
            || head.revoked_grant_ids.iter().any(|id| {
                id.is_empty()
                    || id.len() > 128
                    || !id
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || b"_-.:/".contains(&c))
            })
            || clock.schema_version != 1
            || clock.boot_id != self.boot_id
            || clock.anchor_unix_ms == 0
            || clock.ceiling_unix_ms < clock.anchor_unix_ms
            || started > ended
            || ended > now
            || now.checked_sub(started).is_none_or(|age| age > MAX_AGE_NS)
            || clock.anchor_boottime_ns > ended
            || observation.observed_unix_ms < clock.anchor_unix_ms
            || observation.observed_unix_ms
                < clock
                    .anchor_unix_ms
                    .checked_add(started.saturating_sub(clock.anchor_boottime_ns) / 1_000_000)
                    .ok_or(AgentdRootAuthorityError::Unavailable)?
            || observation.observed_unix_ms > project(&observation, ended)?
            || observation.observed_unix_ms > clock.ceiling_unix_ms
        {
            #[cfg(test)]
            eprintln!(
                "ROOT_OBSERVATION_CACHE phase=accept reason=sample-validation now={now} started={started} ended={ended} age_ns={:?} schema={} purpose_valid={} epoch={} head_epoch={} head_revision={} clock_schema={} boot_matches={} anchor_unix_ms={} ceiling_unix_ms={} anchor_boottime_ns={} observed_unix_ms={}",
                now.checked_sub(started),
                observation.schema_version,
                observation.operation == HOST_AUTHORITY_OBSERVATION_V2,
                observation.authority_epoch,
                head.authority_epoch,
                head.revision,
                clock.schema_version,
                clock.boot_id == self.boot_id,
                clock.anchor_unix_ms,
                clock.ceiling_unix_ms,
                clock.anchor_boottime_ns,
                observation.observed_unix_ms,
            );
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        let projected = project(&observation, now)?;
        if let Some(previous) = slot.as_ref() {
            let old = &previous.observation;
            if now
                .checked_sub(previous.request_started_ns)
                .is_none_or(|age| age > MAX_AGE_NS)
                || now < previous.last_checked_ns
                || observation.authority_epoch != old.authority_epoch
                || observation.registered_agent_id != old.registered_agent_id
                || observation.spawn_generation != old.spawn_generation
                || observation.writer.authority_lease != old.writer.authority_lease
                || observation.writer.authority_lease_sha256 != old.writer.authority_lease_sha256
                || observation.writer.writer_authorization_sha256
                    != old.writer.writer_authorization_sha256
                || observation.writer.owner_epoch != old.writer.owner_epoch
                || observation.writer.local_lease_id != old.writer.local_lease_id
                || observation.writer.local_lease_generation != old.writer.local_lease_generation
                || observation.writer.store_revision < old.writer.store_revision
                || head.revision < old.revocations.revision
                || (head.revision == old.revocations.revision && *head != old.revocations)
                || !head
                    .revoked_grant_ids
                    .is_superset(&old.revocations.revoked_grant_ids)
                || observation.observed_unix_ms < old.observed_unix_ms
                || projected < project_unbounded(old, now)?
            {
                #[cfg(test)]
                eprintln!(
                    "ROOT_OBSERVATION_CACHE phase=accept reason=retained-validation now={now} started={started} ended={ended} old_started={} old_last_checked={} old_age_ns={:?} time_regressed={} epoch_changed={} agent_changed={} spawn_changed={} lease_changed={} lease_digest_changed={} writer_digest_changed={} owner_changed={} local_lease_changed={} local_generation_changed={} old_store_revision={} new_store_revision={} old_head_revision={} new_head_revision={} equal_revision_changed_head={} revocations_shrunk={} old_observed_unix_ms={} new_observed_unix_ms={} projected_unix_ms={projected} old_anchor_boottime_ns={} old_anchor_unix_ms={}",
                    previous.request_started_ns,
                    previous.last_checked_ns,
                    now.checked_sub(previous.request_started_ns),
                    now < previous.last_checked_ns,
                    observation.authority_epoch != old.authority_epoch,
                    observation.registered_agent_id != old.registered_agent_id,
                    observation.spawn_generation != old.spawn_generation,
                    observation.writer.authority_lease != old.writer.authority_lease,
                    observation.writer.authority_lease_sha256 != old.writer.authority_lease_sha256,
                    observation.writer.writer_authorization_sha256
                        != old.writer.writer_authorization_sha256,
                    observation.writer.owner_epoch != old.writer.owner_epoch,
                    observation.writer.local_lease_id != old.writer.local_lease_id,
                    observation.writer.local_lease_generation != old.writer.local_lease_generation,
                    old.writer.store_revision,
                    observation.writer.store_revision,
                    old.revocations.revision,
                    head.revision,
                    head.revision == old.revocations.revision && *head != old.revocations,
                    !head
                        .revoked_grant_ids
                        .is_superset(&old.revocations.revoked_grant_ids),
                    old.observed_unix_ms,
                    observation.observed_unix_ms,
                    old.clock.anchor_boottime_ns,
                    old.clock.anchor_unix_ms,
                );
                return Err(AgentdRootAuthorityError::Unavailable);
            }
        }
        let deadline = started
            .checked_add(MAX_AGE_NS)
            .ok_or(AgentdRootAuthorityError::Unavailable)?;
        *slot = Some(Retained {
            observation: Arc::new(observation),
            request_started_ns: started,
            last_checked_ns: now,
        });
        // Publish only after the complete accepted response. The original
        // mutex remains held until after this release store.
        self.read_deadline_ns.store(deadline, Ordering::Release);
        Ok(())
    }

    fn finish_accept(
        &self,
        result: Result<(), AgentdRootAuthorityError>,
        _started: u64,
        _ended: u64,
        _sampled: Option<u64>,
    ) -> Result<(), AgentdRootAuthorityError> {
        if result.is_err() {
            #[cfg(test)]
            eprintln!(
                "ROOT_OBSERVATION_CACHE phase=accept reason=original-error-fence now={_sampled:?} started={_started} ended={_ended}"
            );
            self.fence();
        }
        result
    }
    pub(crate) fn current(
        &self,
    ) -> Result<(Arc<HostAuthorityObservationResponseV2>, u64), AgentdRootAuthorityError> {
        let admission = self.capture_read_admission()?;
        let (mut slot, now) = self.acquire_retained_read(admission)?;
        let value = self.current_locked(&mut slot, now, admission.generation)?;
        // A later accepted feed cannot renew this already-started read's
        // admission budget, even when its retained response is now newer.
        if admission.deadline_ns != 0 && now > admission.deadline_ns {
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        Ok(value)
    }

    #[cfg(test)]
    fn current_at(
        &self,
        now: u64,
    ) -> Result<(Arc<HostAuthorityObservationResponseV2>, u64), AgentdRootAuthorityError> {
        let admission = self.capture_read_admission()?;
        let mut slot = self
            .retained
            .try_lock()
            .map_err(|_| AgentdRootAuthorityError::Unavailable)?;
        self.current_locked(&mut slot, now, admission.generation)
    }

    fn capture_read_admission(&self) -> Result<ReadAdmission, AgentdRootAuthorityError> {
        let generation = self.update_generation.load(Ordering::Acquire);
        if self.fenced.load(Ordering::Acquire) || generation & 1 != 0 {
            #[cfg(test)]
            eprintln!(
                "ROOT_OBSERVATION_CACHE phase=current reason=already-fenced-or-updating generation={generation}"
            );
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        let deadline_ns = self.read_deadline_ns.load(Ordering::Acquire);
        self.require_read_generation(generation)?;
        Ok(ReadAdmission {
            deadline_ns,
            generation,
        })
    }

    fn require_read_generation(&self, generation: u64) -> Result<(), AgentdRootAuthorityError> {
        if self.fenced.load(Ordering::Acquire)
            || generation & 1 != 0
            || self.update_generation.load(Ordering::Acquire) != generation
        {
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        Ok(())
    }

    fn sample_current_time(&self) -> Result<u64, AgentdRootAuthorityError> {
        boottime_ns().inspect_err(|_| {
            #[cfg(test)]
            eprintln!("ROOT_OBSERVATION_CACHE phase=current reason=boottime-sample-failed");
            self.fence();
        })
    }

    fn acquire_retained_read(
        &self,
        admission: ReadAdmission,
    ) -> Result<(MutexGuard<'_, Option<Retained>>, u64), AgentdRootAuthorityError> {
        let mut last_wait_sample = None;
        #[cfg(test)]
        let mut reported_wait = false;
        loop {
            self.require_read_generation(admission.generation)?;
            match self.retained.try_lock() {
                Ok(slot) => {
                    // This is the first evidence-validation sample, taken
                    // while holding the original mutex, never before a wait.
                    let now = self.sample_current_time()?;
                    if last_wait_sample.is_some_and(|previous| now < previous) {
                        self.fence();
                        return Err(AgentdRootAuthorityError::Unavailable);
                    }
                    self.require_read_generation(admission.generation)?;
                    return Ok((slot, now));
                }
                Err(TryLockError::Poisoned(_)) => {
                    #[cfg(test)]
                    eprintln!("ROOT_OBSERVATION_CACHE phase=current reason=retained-lock-poisoned");
                    return Err(AgentdRootAuthorityError::Unavailable);
                }
                Err(TryLockError::WouldBlock) => {
                    // There is no waiting permission before a real original
                    // observation has published its deadline.
                    if admission.deadline_ns == 0 {
                        return Err(AgentdRootAuthorityError::Unavailable);
                    }
                    let now = self.sample_current_time()?;
                    let original_start = admission
                        .deadline_ns
                        .checked_sub(MAX_AGE_NS)
                        .ok_or(AgentdRootAuthorityError::Unavailable)?;
                    if now < original_start
                        || last_wait_sample.is_some_and(|previous| now < previous)
                    {
                        self.fence();
                        return Err(AgentdRootAuthorityError::Unavailable);
                    }
                    if now > admission.deadline_ns {
                        #[cfg(test)]
                        self.expired_admission_deadline
                            .store(admission.deadline_ns, Ordering::Release);
                        #[cfg(test)]
                        self.expired_admission_sample.store(now, Ordering::Release);
                        #[cfg(test)]
                        eprintln!(
                            "ROOT_OBSERVATION_CACHE phase=current reason=original-read-admission-expired now={now} deadline_ns={}",
                            admission.deadline_ns,
                        );
                        return Err(AgentdRootAuthorityError::Unavailable);
                    }
                    last_wait_sample = Some(now);
                    #[cfg(test)]
                    if !reported_wait {
                        self.admission_waits.fetch_add(1, Ordering::Release);
                        reported_wait = true;
                    }
                    // Only first acquisition of a bounded memory critical
                    // section waits. No authority result or effect is retried.
                    std::thread::yield_now();
                }
            }
        }
    }

    fn current_locked(
        &self,
        slot: &mut Option<Retained>,
        now: u64,
        generation: u64,
    ) -> Result<(Arc<HostAuthorityObservationResponseV2>, u64), AgentdRootAuthorityError> {
        self.require_read_generation(generation)?;
        let result = (|| {
            let retained = slot
                .as_mut()
                .ok_or(AgentdRootAuthorityError::Unavailable)
                .inspect_err(|_error| {
                    #[cfg(test)]
                    eprintln!("ROOT_OBSERVATION_CACHE phase=current reason=cache-absent now={now}");
                })?;
            if now < retained.last_checked_ns
                || now
                    .checked_sub(retained.request_started_ns)
                    .is_none_or(|age| age > MAX_AGE_NS)
            {
                #[cfg(test)]
                eprintln!(
                    "ROOT_OBSERVATION_CACHE phase=current reason=retained-time now={now} last_checked={} request_started={} age_ns={:?} time_regressed={}",
                    retained.last_checked_ns,
                    retained.request_started_ns,
                    now.checked_sub(retained.request_started_ns),
                    now < retained.last_checked_ns,
                );
                return Err(AgentdRootAuthorityError::Unavailable);
            }
            let projected = project(&retained.observation, now)?;
            retained.last_checked_ns = now;
            if self.fenced.load(Ordering::Acquire)
                || self.update_generation.load(Ordering::Acquire) != generation
            {
                #[cfg(test)]
                eprintln!(
                    "ROOT_OBSERVATION_CACHE phase=current reason=fenced-or-updating-after-projection now={now}"
                );
                return Err(AgentdRootAuthorityError::Unavailable);
            }
            Ok((Arc::clone(&retained.observation), projected))
        })();
        if result.is_err() && self.update_generation.load(Ordering::Acquire) == generation {
            #[cfg(test)]
            eprintln!("ROOT_OBSERVATION_CACHE phase=current reason=original-error-fence now={now}");
            self.fence();
        }
        result
    }
}
impl AuthorityClock for RootObservationCache {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        self.current()
            .map(|(_, now)| now)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }
}
fn project(
    value: &HostAuthorityObservationResponseV2,
    now: u64,
) -> Result<u64, AgentdRootAuthorityError> {
    let projected = project_unbounded(value, now)?;
    if projected > value.clock.ceiling_unix_ms {
        #[cfg(test)]
        eprintln!(
            "ROOT_OBSERVATION_CACHE phase=project reason=durable-ceiling now={now} projected_unix_ms={projected} ceiling_unix_ms={} anchor_boottime_ns={} anchor_unix_ms={}",
            value.clock.ceiling_unix_ms, value.clock.anchor_boottime_ns, value.clock.anchor_unix_ms,
        );
        return Err(AgentdRootAuthorityError::Unavailable);
    }
    Ok(projected)
}
fn project_unbounded(
    value: &HostAuthorityObservationResponseV2,
    now: u64,
) -> Result<u64, AgentdRootAuthorityError> {
    let elapsed = now
        .checked_sub(value.clock.anchor_boottime_ns)
        .ok_or(AgentdRootAuthorityError::Unavailable)
        .inspect_err(|_error| {
            #[cfg(test)]
            eprintln!(
                "ROOT_OBSERVATION_CACHE phase=project reason=boottime-before-anchor now={now} anchor_boottime_ns={}",
                value.clock.anchor_boottime_ns,
            );
        })?;
    value
        .clock
        .anchor_unix_ms
        .checked_add(elapsed.div_ceil(1_000_000))
        .ok_or(AgentdRootAuthorityError::Unavailable)
        .inspect_err(|_error| {
            #[cfg(test)]
            eprintln!(
                "ROOT_OBSERVATION_CACHE phase=project reason=unix-overflow now={now} elapsed_ns={elapsed} anchor_unix_ms={}",
                value.clock.anchor_unix_ms,
            );
        })
}
pub(crate) fn boottime_ns() -> Result<u64, AgentdRootAuthorityError> {
    let mut stamp = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: valid writable timespec and Linux monotonic-with-suspend clock.
    if unsafe { libc::clock_gettime(libc::CLOCK_BOOTTIME, &mut stamp) } != 0
        || stamp.tv_sec < 0
        || !(0..1_000_000_000).contains(&stamp.tv_nsec)
    {
        return Err(AgentdRootAuthorityError::Unavailable);
    }
    (stamp.tv_sec as u64)
        .checked_mul(1_000_000_000)
        .and_then(|s| s.checked_add(stamp.tv_nsec as u64))
        .ok_or(AgentdRootAuthorityError::Unavailable)
}
#[cfg(test)]
#[path = "root_observation_cache_tests.rs"]
pub(crate) mod tests;
