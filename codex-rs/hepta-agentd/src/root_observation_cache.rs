//! Bounded read-only cache. Authority callbacks sample BOOTTIME and retained
//! memory only; no filesystem, network or durable owner callback occurs here.
use crate::AgentdRootAuthorityError;
use crate::HOST_AUTHORITY_OBSERVATION_V2;
use crate::HostAuthorityObservationResponseV2;
use arc_swap::ArcSwapOption;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

pub(crate) const MAX_AGE_NS: u64 = 500_000_000;
struct Retained {
    observation: Arc<HostAuthorityObservationResponseV2>,
    request_started_ns: u64,
}
pub(crate) struct RootObservationCache {
    boot_id: String,
    retained: ArcSwapOption<Retained>,
    // Only refresh writers serialize; authority readers retain an immutable
    // snapshot without waiting for another reader or a validating refresh.
    publisher: Mutex<()>,
    last_checked_ns: AtomicU64,
    fenced: AtomicBool,
    // Odd while the new revocation head is being synchronized to consumers.
    // A generation also detects an entire begin/end update during one read.
    update_generation: AtomicU64,
}
impl RootObservationCache {
    pub(crate) fn new(boot_id: String) -> Self {
        Self {
            boot_id,
            retained: ArcSwapOption::empty(),
            publisher: Mutex::new(()),
            last_checked_ns: AtomicU64::new(0),
            fenced: AtomicBool::new(false),
            update_generation: AtomicU64::new(0),
        }
    }
    pub(crate) fn fence(&self) {
        self.fenced.store(true, Ordering::Release);
    }
    pub(crate) fn begin_update(&self) {
        let previous = self.update_generation.fetch_add(1, Ordering::AcqRel);
        if !previous.is_multiple_of(2) || previous == u64::MAX {
            self.fence();
        }
    }
    pub(crate) fn end_update(&self) {
        let previous = self.update_generation.fetch_add(1, Ordering::AcqRel);
        if previous % 2 != 1 || previous == u64::MAX {
            self.fence();
        }
    }
    pub(crate) fn revocations_match(
        &self,
        head: &codex_hepta_contracts::FinalUseRevocations,
    ) -> bool {
        self.retained
            .load()
            .as_ref()
            .is_some_and(|value| value.observation.revocations == *head)
    }
    pub(crate) fn accept(
        &self,
        observation: HostAuthorityObservationResponseV2,
        started: u64,
        ended: u64,
    ) -> Result<(), AgentdRootAuthorityError> {
        self.accept_with_clock(observation, started, ended, boottime_ns)
    }
    fn accept_with_clock(
        &self,
        observation: HostAuthorityObservationResponseV2,
        started: u64,
        ended: u64,
        read_clock: impl FnOnce() -> Result<u64, AgentdRootAuthorityError>,
    ) -> Result<(), AgentdRootAuthorityError> {
        let _publisher = self.publisher.lock().map_err(|_| {
            self.fence();
            AgentdRootAuthorityError::Unavailable
        })?;
        // Capture the prior watermark before sampling, so overlapping calls
        // cannot turn scheduling order into a false clock rollback.
        let checked_before_sample = self.last_checked_ns.load(Ordering::Acquire);
        let now = read_clock().inspect_err(|_error| {
            #[cfg(test)]
            eprintln!("ROOT_OBSERVATION_CACHE phase=accept reason=boottime-sample-failed");
            self.fence();
        })?;
        if self.fenced.load(Ordering::Acquire) {
            #[cfg(test)]
            eprintln!(
                "ROOT_OBSERVATION_CACHE phase=accept reason=already-fenced now={now} started={started} ended={ended}"
            );
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        let result = (|| {
            let slot = self.retained.load();
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
                || now < checked_before_sample
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
                        checked_before_sample,
                        now.checked_sub(previous.request_started_ns),
                        now < checked_before_sample,
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
            if self.fenced.load(Ordering::Acquire) {
                return Err(AgentdRootAuthorityError::Unavailable);
            }
            self.last_checked_ns.fetch_max(now, Ordering::AcqRel);
            self.retained.store(Some(Arc::new(Retained {
                observation: Arc::new(observation),
                request_started_ns: started,
            })));
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
        self.current_with_clock(boottime_ns)
    }
    fn current_with_clock(
        &self,
        read_clock: impl FnOnce() -> Result<u64, AgentdRootAuthorityError>,
    ) -> Result<(Arc<HostAuthorityObservationResponseV2>, u64), AgentdRootAuthorityError> {
        let generation = self.update_generation.load(Ordering::Acquire);
        if self.fenced.load(Ordering::Acquire) || !generation.is_multiple_of(2) {
            #[cfg(test)]
            eprintln!("ROOT_OBSERVATION_CACHE phase=current reason=already-fenced-or-updating");
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        let slot = self.retained.load();
        let checked_before_sample = self.last_checked_ns.load(Ordering::Acquire);
        let now = read_clock().inspect_err(|_| {
            #[cfg(test)]
            eprintln!("ROOT_OBSERVATION_CACHE phase=current reason=boottime-sample-failed");
            self.fence();
        })?;
        if now < checked_before_sample {
            self.fence();
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        let result = (|| {
            let retained = slot
                .as_ref()
                .ok_or(AgentdRootAuthorityError::Unavailable)
                .inspect_err(|_error| {
                    #[cfg(test)]
                    eprintln!("ROOT_OBSERVATION_CACHE phase=current reason=cache-absent now={now}");
                })?;
            if now
                .checked_sub(retained.request_started_ns)
                .is_none_or(|age| age > MAX_AGE_NS)
            {
                #[cfg(test)]
                eprintln!(
                    "ROOT_OBSERVATION_CACHE phase=current reason=retained-time now={now} last_checked={} request_started={} age_ns={:?} time_regressed={}",
                    checked_before_sample,
                    retained.request_started_ns,
                    now.checked_sub(retained.request_started_ns),
                    now < checked_before_sample,
                );
                return Err(AgentdRootAuthorityError::Unavailable);
            }
            let projected = project(&retained.observation, now)?;
            self.last_checked_ns.fetch_max(now, Ordering::AcqRel);
            Ok((Arc::clone(&retained.observation), projected))
        })();
        // Do not return a snapshot across a revocation synchronization, even
        // if both begin_update and end_update completed during this read.
        std::sync::atomic::fence(Ordering::Acquire);
        if self.update_generation.load(Ordering::Acquire) != generation {
            return Err(AgentdRootAuthorityError::Unavailable);
        }
        if result.is_err() {
            #[cfg(test)]
            eprintln!("ROOT_OBSERVATION_CACHE phase=current reason=original-error-fence now={now}");
            self.fence();
        }
        if self.fenced.load(Ordering::Acquire) {
            return Err(AgentdRootAuthorityError::Unavailable);
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
