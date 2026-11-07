//! Local FinalUse journal held only after the actual Root/Child handoff.
//! No authority, token, raw lane, signer or arbitrary request adapter escapes.

use super::WorkerRootLaneReceipt;
use crate::worker_root_registration::journal_path::WorkerJournalDirectory;
use crate::worker_root_registration::journal_wire::WORKER_ROOT_JOURNAL_V1;
use crate::worker_root_registration::journal_wire::WorkerJournalDirectoryPinV1;
use crate::worker_root_registration::lanes_wire::WorkerRootObservationV1;
use crate::worker_root_registration::refused;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;
use std::io;
use std::sync::Arc;
use std::sync::Mutex;

#[path = "worker_root_journal_clock.rs"]
mod clock;
use clock::WorkerRootJournalClock;

/// A successful read observes one current local journal and its actual Root
/// floor. It does not attest a provider effect or confer any authority.
#[derive(Clone, Debug, Serialize)]
pub struct WorkerRootJournalObservationV1 {
    pub schema_version: u32,
    pub purpose: String,
    pub registration_sha256: Sha256Digest,
    pub slot_sequence: u64,
    pub journal: WorkerJournalDirectoryPinV1,
    pub revocations: FinalUseRevocations,
    pub frontier: FinalUseFrontier,
    pub used_nonces: usize,
    pub observed_unix_ms: u64,
    pub effect_authorization_available: bool,
}

/// Non-cloneable concrete custody. There is no public path/clock/key/frontier
/// constructor, Deserialize, authority accessor, claim or Sign operation.
/// A new process cannot reopen this object; successor admission is a later
/// Root recovery protocol. This layer only supports same-custody strict reopen.
pub struct WorkerRootJournal {
    lanes: Arc<Mutex<WorkerRootLaneReceipt>>,
    directory: WorkerJournalDirectory,
    clock: Arc<WorkerRootJournalClock>,
    floor: Arc<WorkerJournalFrontier>,
    authority: Option<FinalUseAuthority>,
    signer_id: String,
    issuer_keys: Vec<FinalUseIssuerTrustKey>,
    closed: bool,
}

struct WorkerJournalFrontier {
    lanes: Arc<Mutex<WorkerRootLaneReceipt>>,
    clock: Arc<WorkerRootJournalClock>,
    owner_id: String,
}

impl WorkerRootJournal {
    pub(super) fn from_confirmed_lanes(
        lanes: WorkerRootLaneReceipt,
        directory: WorkerJournalDirectory,
    ) -> io::Result<Self> {
        let bundle = &lanes.bootstrap;
        directory.check()?;
        let pin = directory.observation();
        if pin.registration_sha256 != bundle.registration_sha256()?
            || pin.slot_sequence != bundle.slot_sequence
            || pin.worker_uid != rustix::process::getuid().as_raw()
            || pin.worker_uid != rustix::process::geteuid().as_raw()
            || pin.worker_gid != rustix::process::getgid().as_raw()
            || pin.worker_gid != rustix::process::getegid().as_raw()
            || pin.initial_frontier != bundle.frontier
        {
            return Err(refused(
                "actual Worker UID/GID and sealed journal registration must match",
            ));
        }
        let clock = Arc::new(WorkerRootJournalClock::from_original_handoff(
            bundle,
            lanes.root_pidfd.try_clone()?,
        )?);
        let signer_id = bundle.owner_id.clone();
        let issuer_keys = vec![FinalUseIssuerTrustKey {
            key_id: bundle.issuer_key.key_id.clone(),
            verifying_key: bundle.issuer_key.verifying_key,
            not_before_authority_epoch: bundle.issuer_key.not_before_authority_epoch,
            not_after_authority_epoch: bundle.issuer_key.not_after_authority_epoch,
        }];
        let lanes = Arc::new(Mutex::new(lanes));
        let floor = Arc::new(WorkerJournalFrontier {
            lanes: Arc::clone(&lanes),
            clock: Arc::clone(&clock),
            owner_id: signer_id.clone(),
        });
        let mut value = Self {
            lanes,
            directory,
            clock,
            floor,
            authority: None,
            signer_id,
            issuer_keys,
            closed: false,
        };
        let result = (|| {
            let observation = value.refresh_root_observation()?;
            let authority = FinalUseAuthority::initialize_fresh_state_dir_with_issuer_keys(
                &value.directory.observation().directory,
                value.signer_id.clone(),
                value.issuer_keys.clone(),
                observation.revocations,
                value.clock.clone(),
                value.floor.clone(),
            )
            .map_err(io::Error::other)?;
            value.authority = Some(authority);
            value.verify_current_journal()?;
            Ok(())
        })();
        if let Err(error) = result {
            value.fence();
            return Err(error);
        }
        Ok(value)
    }

    /// Refresh the actual original Root projection before any local FinalUse
    /// lock. A newer valid Root head may advance the independent floor and
    /// local revocation journal through the original no-refund CAS protocol.
    pub fn refresh_and_observe(&mut self) -> io::Result<WorkerRootJournalObservationV1> {
        let result = (|| {
            let observation = self.refresh_root_observation()?;
            let authority = self
                .authority
                .as_ref()
                .ok_or_else(|| refused("Worker journal unavailable"))?;
            if authority.revocation_head().map_err(io::Error::other)? != observation.revocations {
                authority
                    .update_revocations(observation.revocations)
                    .map_err(io::Error::other)?;
            }
            self.verify_current_journal()
        })();
        if result.is_err() {
            self.fence();
        }
        result
    }

    /// Close and strictly reopen only this same live Root/Worker custody.
    /// No directory, key, clock, head, fresh flag or replacement lane is taken
    /// from the caller. An error consumes the owner; it never retries fresh.
    pub fn reopen_existing(mut self) -> io::Result<Self> {
        let result = (|| {
            let observation = self.refresh_root_observation()?;
            self.verify_current_journal()?;
            drop(self.authority.take());
            let authority = FinalUseAuthority::open_existing_state_dir_with_issuer_keys(
                &self.directory.observation().directory,
                self.signer_id.clone(),
                self.issuer_keys.clone(),
                observation.revocations,
                self.clock.clone(),
                self.floor.clone(),
            )
            .map_err(io::Error::other)?;
            self.authority = Some(authority);
            self.verify_current_journal()?;
            Ok(())
        })();
        if let Err(error) = result {
            self.fence();
            return Err(error);
        }
        Ok(self)
    }

    fn refresh_root_observation(&self) -> io::Result<WorkerRootObservationV1> {
        if self.closed {
            return Err(refused("Worker journal owner permanently fenced"));
        }
        self.directory.check()?;
        let started = clock::boottime_ns()?;
        // End the lane guard before touching the clock cache. This method is
        // never called from AuthorityClock/AuthorityFrontierStore callbacks
        // or while the local FinalUse state/store lock is held.
        let observation = {
            let mut lanes = self
                .lanes
                .lock()
                .map_err(|_| refused("Worker lanes poisoned"))?;
            lanes.read_observation()?
        };
        let ended = clock::boottime_ns()?;
        self.clock.accept(observation.clone(), started, ended)?;
        self.directory.check()?;
        Ok(observation)
    }

    fn verify_current_journal(&self) -> io::Result<WorkerRootJournalObservationV1> {
        if self.closed {
            return Err(refused("Worker journal owner permanently fenced"));
        }
        self.directory.check()?;
        let authority = self
            .authority
            .as_ref()
            .ok_or_else(|| refused("Worker journal has not initialized"))?;
        let frontier = authority.frontier().map_err(io::Error::other)?;
        if self.floor.load(&self.signer_id).map_err(io::Error::other)? != frontier {
            return Err(refused(
                "Worker local journal differs from the original Root frontier",
            ));
        }
        let head = authority.revocation_head().map_err(io::Error::other)?;
        let capacity = authority.capacity().map_err(io::Error::other)?;
        let now = self.clock.current()?;
        self.directory.check()?;
        let pin = self.directory.observation();
        Ok(WorkerRootJournalObservationV1 {
            schema_version: 1,
            purpose: WORKER_ROOT_JOURNAL_V1.into(),
            registration_sha256: pin.registration_sha256.clone(),
            slot_sequence: pin.slot_sequence,
            journal: pin.clone(),
            revocations: head,
            frontier,
            used_nonces: capacity.used_nonces,
            observed_unix_ms: now,
            effect_authorization_available: false,
        })
    }

    fn fence(&mut self) {
        self.closed = true;
        self.clock.fence();
        if let Ok(mut lanes) = self.lanes.lock() {
            lanes.close();
        }
    }
}

impl Drop for WorkerRootJournal {
    fn drop(&mut self) {
        self.fence();
    }
}

impl AuthorityFrontierStore<FinalUseFrontier> for WorkerJournalFrontier {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        let result = (|| {
            if owner_id != self.owner_id {
                return Err(AuthorityTrustError::Invalid);
            }
            self.clock.now_unix_ms()?;
            let value = self
                .lanes
                .lock()
                .map_err(|_| AuthorityTrustError::Unavailable)?
                .load_frontier()?;
            self.clock.now_unix_ms()?;
            Ok(value)
        })();
        if result.is_err() {
            self.clock.fence();
        }
        result
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        let result = (|| {
            if owner_id != self.owner_id {
                return Err(AuthorityTrustError::Invalid);
            }
            self.clock.now_unix_ms()?;
            self.lanes
                .lock()
                .map_err(|_| AuthorityTrustError::Unavailable)?
                .compare_and_set_frontier(expected, next)?;
            // A post-I/O clock failure can follow durable Root persistence.
            // Report unavailable and fence; never refund or retry this CAS.
            self.clock.now_unix_ms()?;
            Ok(())
        })();
        if result.is_err() {
            self.clock.fence();
        }
        result
    }
}
