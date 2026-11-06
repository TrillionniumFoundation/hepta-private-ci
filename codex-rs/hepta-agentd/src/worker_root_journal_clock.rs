//! Worker-specific bounded Root projection. Refresh is performed by the
//! journal owner before entering any FinalUse state/store/frontier callback.
//! Clock reads use retained memory, CLOCK_BOOTTIME and the original pidfd only.

use crate::worker_root_registration::lanes_wire::WORKER_OBSERVATION_V1;
use crate::worker_root_registration::lanes_wire::WorkerRootLaneBootstrapV1;
use crate::worker_root_registration::lanes_wire::WorkerRootObservationV1;
use crate::worker_root_registration::refused;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::Sha256Digest;
use std::io;
use std::os::fd::OwnedFd;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

const MAX_AGE_NS: u64 = crate::root_observation_cache::MAX_AGE_NS;

struct Retained {
    observation: WorkerRootObservationV1,
    request_started_ns: u64,
    last_checked_ns: u64,
}

pub(super) struct WorkerRootJournalClock {
    root_pidfd: OwnedFd,
    boot_id: String,
    registration_sha256: Sha256Digest,
    owner_id: String,
    namespace: String,
    slot_sequence: u64,
    authority_epoch: u64,
    expires_at_unix_ms: u64,
    retained: Mutex<Option<Retained>>,
    fenced: AtomicBool,
}

impl WorkerRootJournalClock {
    pub(super) fn from_original_handoff(bundle: &WorkerRootLaneBootstrapV1, root_pidfd: OwnedFd) -> io::Result<Self> {
        bundle.validate()?;
        crate::root_observation_stream::check_lifetime(&root_pidfd).map_err(io::Error::other)?;
        Ok(Self {
            root_pidfd, boot_id: bundle.registration.root.boot_id.clone(), registration_sha256: bundle.registration_sha256()?,
            owner_id: bundle.owner_id.clone(), namespace: bundle.consumer_namespace.clone(), slot_sequence: bundle.slot_sequence,
            authority_epoch: bundle.registration.issuer_lease.authority_epoch, expires_at_unix_ms: bundle.expires_at_unix_ms,
            retained: Mutex::new(None), fenced: AtomicBool::new(false),
        })
    }

    pub(super) fn fence(&self) { self.fenced.store(true, Ordering::Release); }

    pub(super) fn accept(&self, value: WorkerRootObservationV1, started: u64, ended: u64) -> io::Result<()> {
        let now = boottime_ns()?;
        let result = self.accept_at(value, started, ended, now);
        if result.is_err() { self.fence(); }
        result
    }

    fn accept_at(&self, value: WorkerRootObservationV1, started: u64, ended: u64, now: u64) -> io::Result<()> {
        self.check_root()?;
        let mut slot = self.retained.try_lock().map_err(|_| refused("Worker Root clock refresh contended"))?;
        let clock = &value.clock;
        let head = &value.revocations;
        if value.schema_version != 1 || value.operation != WORKER_OBSERVATION_V1
            || value.registration_sha256 != self.registration_sha256 || value.owner_id != self.owner_id
            || value.consumer_namespace != self.namespace || value.slot_sequence != self.slot_sequence
            || value.expires_at_unix_ms != self.expires_at_unix_ms || value.effect_authorization_available
            || head.authority_epoch != self.authority_epoch || head.revision == 0 || head.revoked_grant_ids.len() > 16_384
            || head.revoked_grant_ids.iter().any(|id| id.is_empty() || id.len() > 128 || !id.bytes().all(|c| c.is_ascii_alphanumeric() || b"_-.:/".contains(&c)))
            || clock.schema_version != 1 || clock.boot_id != self.boot_id || clock.anchor_unix_ms == 0
            || clock.ceiling_unix_ms < clock.anchor_unix_ms || clock.anchor_boottime_ns > ended
            || started > ended || ended > now || now.checked_sub(started).is_none_or(|age| age > MAX_AGE_NS)
            || value.observed_unix_ms < clock.anchor_unix_ms
            || value.observed_unix_ms < clock.anchor_unix_ms.checked_add(started.saturating_sub(clock.anchor_boottime_ns) / 1_000_000).ok_or_else(|| refused("Worker Root time overflow"))?
            || value.observed_unix_ms > project(&value, ended)? || value.observed_unix_ms >= self.expires_at_unix_ms
        {
            return Err(refused("Worker Root projection, purpose, deadline or original head differs"));
        }
        let projected = project(&value, now)?;
        if let Some(prior) = slot.as_ref() {
            let old = &prior.observation;
            if now.checked_sub(prior.request_started_ns).is_none_or(|age| age > MAX_AGE_NS)
                || now < prior.last_checked_ns || head.revision < old.revocations.revision
                || (head.revision == old.revocations.revision && *head != old.revocations)
                || !head.revoked_grant_ids.is_superset(&old.revocations.revoked_grant_ids)
                || value.observed_unix_ms < old.observed_unix_ms
                || value.clock.ceiling_unix_ms < old.clock.ceiling_unix_ms
                || projected < project_unbounded(old, now)?
            {
                return Err(refused("Worker Root clock or revocation history went backwards or became stale"));
            }
        }
        self.check_root()?;
        *slot = Some(Retained { observation: value, request_started_ns: started, last_checked_ns: now });
        Ok(())
    }

    pub(super) fn current(&self) -> io::Result<u64> {
        let now = boottime_ns().inspect_err(|_| self.fence())?;
        let result = (|| {
            self.check_root()?;
            let mut slot = self.retained.try_lock().map_err(|_| refused("Worker Root clock sample contended"))?;
            let retained = slot.as_mut().ok_or_else(|| refused("Worker Root projection has not been observed"))?;
            if now < retained.last_checked_ns || now.checked_sub(retained.request_started_ns).is_none_or(|age| age > MAX_AGE_NS) {
                return Err(refused("Worker Root clock observation expired"));
            }
            let value = project(&retained.observation, now)?;
            retained.last_checked_ns = now;
            self.check_root()?;
            Ok(value)
        })();
        if result.is_err() { self.fence(); }
        result
    }

    fn check_root(&self) -> io::Result<()> {
        if self.fenced.load(Ordering::Acquire) { return Err(refused("Worker Root clock permanently fenced")); }
        crate::root_observation_stream::check_lifetime(&self.root_pidfd).map_err(io::Error::other)
    }
}

impl AuthorityClock for WorkerRootJournalClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        self.current().map_err(|_| AuthorityTrustError::Unavailable)
    }
}

pub(super) fn boottime_ns() -> io::Result<u64> {
    crate::root_observation_cache::boottime_ns().map_err(io::Error::other)
}

fn project(value: &WorkerRootObservationV1, now: u64) -> io::Result<u64> {
    let projected = project_unbounded(value, now)?;
    if projected > value.clock.ceiling_unix_ms || projected >= value.expires_at_unix_ms {
        return Err(refused("Worker Root projection exceeded its original ceiling or lease deadline"));
    }
    Ok(projected)
}

fn project_unbounded(value: &WorkerRootObservationV1, now: u64) -> io::Result<u64> {
    let elapsed = now.checked_sub(value.clock.anchor_boottime_ns).ok_or_else(|| refused("Worker BOOTTIME moved backwards"))?;
    value.clock.anchor_unix_ms.checked_add(elapsed.div_ceil(1_000_000)).ok_or_else(|| refused("Worker Root time overflow"))
}
