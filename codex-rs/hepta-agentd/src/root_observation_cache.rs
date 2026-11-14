//! Bounded read-only cache. Authority callbacks sample BOOTTIME and retained
//! memory only; no filesystem, network or durable owner callback occurs here.
use crate::AgentdRootAuthorityError;
use crate::HOST_AUTHORITY_OBSERVATION_V2;
use crate::HostAuthorityObservationResponseV2;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
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
    updating: AtomicBool,
}
impl RootObservationCache {
    pub(crate) fn new(boot_id: String) -> Self {
        Self {
            boot_id,
            retained: Mutex::new(None),
            fenced: AtomicBool::new(false),
            updating: AtomicBool::new(false),
        }
    }
    pub(crate) fn fence(&self) {
        self.fenced.store(true, Ordering::Release);
    }
    pub(crate) fn begin_update(&self) {
        self.updating.store(true, Ordering::Release);
    }
    pub(crate) fn end_update(&self) {
        self.updating.store(false, Ordering::Release);
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
        self.accept_at(
            observation,
            started,
            ended,
            boottime_ns().inspect_err(|_error| {
                #[cfg(test)]
                eprintln!("ROOT_OBSERVATION_CACHE phase=accept reason=boottime-sample-failed");
            })?,
        )
    }
    fn accept_at(
        &self,
        observation: HostAuthorityObservationResponseV2,
        started: u64,
        ended: u64,
        now: u64,
    ) -> Result<(), AgentdRootAuthorityError> {
        if self.fenced.load(Ordering::Acquire) {
            #[cfg(test)]
            eprintln!(
                "ROOT_OBSERVATION_CACHE phase=accept reason=already-fenced now={now} started={started} ended={ended}"
            );
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        let result = (|| {
            let mut slot = self.retained.lock().map_err(|_| {
                #[cfg(test)]
                eprintln!("ROOT_OBSERVATION_CACHE phase=accept reason=retained-lock-poisoned");
                AgentdRootAuthorityError::Unavailable
            })?;
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
                    || observation.writer.authority_lease_sha256
                        != old.writer.authority_lease_sha256
                    || observation.writer.writer_authorization_sha256
                        != old.writer.writer_authorization_sha256
                    || observation.writer.owner_epoch != old.writer.owner_epoch
                    || observation.writer.local_lease_id != old.writer.local_lease_id
                    || observation.writer.local_lease_generation
                        != old.writer.local_lease_generation
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
                        observation.writer.authority_lease_sha256
                            != old.writer.authority_lease_sha256,
                        observation.writer.writer_authorization_sha256
                            != old.writer.writer_authorization_sha256,
                        observation.writer.owner_epoch != old.writer.owner_epoch,
                        observation.writer.local_lease_id != old.writer.local_lease_id,
                        observation.writer.local_lease_generation
                            != old.writer.local_lease_generation,
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
            *slot = Some(Retained {
                observation: Arc::new(observation),
                request_started_ns: started,
                last_checked_ns: now,
            });
            Ok(())
        })();
        if result.is_err() {
            #[cfg(test)]
            eprintln!(
                "ROOT_OBSERVATION_CACHE phase=accept reason=original-error-fence now={now} started={started} ended={ended}"
            );
            self.fence();
        }
        result
    }
    pub(crate) fn current(
        &self,
    ) -> Result<(Arc<HostAuthorityObservationResponseV2>, u64), AgentdRootAuthorityError> {
        let now = boottime_ns().inspect_err(|_| {
            #[cfg(test)]
            eprintln!("ROOT_OBSERVATION_CACHE phase=current reason=boottime-sample-failed");
            self.fence();
        })?;
        self.current_at(now)
    }
    fn current_at(
        &self,
        now: u64,
    ) -> Result<(Arc<HostAuthorityObservationResponseV2>, u64), AgentdRootAuthorityError> {
        if self.fenced.load(Ordering::Acquire) || self.updating.load(Ordering::Acquire) {
            #[cfg(test)]
            eprintln!(
                "ROOT_OBSERVATION_CACHE phase=current reason=already-fenced-or-updating now={now}"
            );
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        // Contention is a local unavailable read, never a wait behind a writer.
        // Unlike invalid evidence, contention alone does not destroy the feed.
        let mut slot = self.retained.try_lock().map_err(|_error| {
            #[cfg(test)]
            match _error {
                std::sync::TryLockError::WouldBlock => eprintln!(
                    "ROOT_OBSERVATION_CACHE phase=current reason=retained-lock-contention now={now}"
                ),
                std::sync::TryLockError::Poisoned(_) => eprintln!(
                    "ROOT_OBSERVATION_CACHE phase=current reason=retained-lock-poisoned now={now}"
                ),
            }
            AgentdRootAuthorityError::Unavailable
        })?;
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
            if self.fenced.load(Ordering::Acquire) || self.updating.load(Ordering::Acquire) {
                #[cfg(test)]
                eprintln!(
                    "ROOT_OBSERVATION_CACHE phase=current reason=fenced-or-updating-after-projection now={now}"
                );
                return Err(AgentdRootAuthorityError::Unavailable);
            }
            Ok((Arc::clone(&retained.observation), projected))
        })();
        if result.is_err() && !self.updating.load(Ordering::Acquire) {
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
mod tests;
