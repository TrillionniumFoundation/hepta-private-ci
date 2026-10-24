//! Root-only handoff of the original full head and retained Current material.

use super::*;
use codex_hepta_memory::CognitiveCheckpointReceipt;

enum Predecessor<'a> {
    Retained(&'a RetainedCheckpointPublisher),
    Retired(&'a RetiredCheckpointPublisher),
}

enum RetainedCut<'a> {
    CleanCurrent,
    Physical(&'a codex_hepta_memory::VerifiedCognitiveMaterial),
}

impl RetainedCut<'_> {
    fn validate(&self, head: &CognitiveCheckpointHead) -> Result<(), AuthorityTrustError> {
        match self {
            Self::CleanCurrent if head.phase == CognitiveCheckpointPhase::Current => Ok(()),
            Self::CleanCurrent => Err(AuthorityTrustError::Invalid),
            Self::Physical(material) => {
                if material.anchor() != &head.last_current {
                    return Err(AuthorityTrustError::Invalid);
                }
                material
                    .verify_unchanged()
                    .map_err(|_| AuthorityTrustError::Unavailable)
            }
        }
    }
}

impl Predecessor<'_> {
    fn lifetime(&self) -> &CognitiveCheckpointPeerLifetime {
        match self {
            Self::Retained(publisher) => &publisher.lifetime,
            Self::Retired(publisher) => &publisher.lifetime,
        }
    }

    fn require_retired(&self) -> Result<(), AuthorityTrustError> {
        match self {
            Self::Retained(publisher) => publisher.require_exited(),
            Self::Retired(publisher) => publisher.require_retired(),
        }
    }

    fn validate_boot_transition(
        &self,
        previous: &CognitiveCheckpointReceipt,
        successor: &CognitiveCheckpointPeerLifetime,
        material: &RetainedCut<'_>,
    ) -> Result<(), AuthorityTrustError> {
        match (self, material) {
            (Self::Retained(publisher), _) => {
                if publisher.lifetime.boot_id != successor.boot_id {
                    return Err(AuthorityTrustError::Invalid);
                }
                Ok(())
            }
            (Self::Retired(publisher), RetainedCut::CleanCurrent) => {
                publisher.require_same_boot_successor(successor)
            }
            (Self::Retired(publisher), RetainedCut::Physical(_)) => {
                publisher.require_physical_successor(previous, successor)
            }
        }
    }
}

impl HostCognitiveCheckpoint {
    /// Adopt only an exact retained Current after the captured old process has
    /// exited. The trusted launcher must hold the new writer's original live
    /// registry dispatch fence around this call; registration is not authority.
    /// No local database path, replacement cut or peer RPC can invoke recovery.
    pub fn adopt_current(
        directory: Arc<RootAuthorityDirectory>,
        previous: &CognitiveCheckpointReceipt,
        predecessor: &RetainedCheckpointPublisher,
        registration: HostCognitiveCheckpointRegistration,
        successor: &RetainedCheckpointPublisher,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, AuthorityTrustError> {
        Self::adopt_current_with_predecessor(
            directory,
            previous,
            Predecessor::Retained(predecessor),
            registration,
            successor,
            clock,
            RetainedCut::CleanCurrent,
        )
    }

    /// Same clean-Current CAS after Root lost its retained old pidfd. The
    /// replacement evidence must come from actual same-boot kernel observation,
    /// not a PID/exit flag read from disk or supplied by the successor. All
    /// original local lease retirement and live canonical authority fences are
    /// still enforced by the trusted launcher before this administrative call.
    pub fn adopt_current_after_root_restart(
        directory: Arc<RootAuthorityDirectory>,
        previous: &CognitiveCheckpointReceipt,
        predecessor: &RetiredCheckpointPublisher,
        registration: HostCognitiveCheckpointRegistration,
        successor: &RetainedCheckpointPublisher,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, AuthorityTrustError> {
        Self::adopt_current_with_predecessor(
            directory,
            previous,
            Predecessor::Retired(predecessor),
            registration,
            successor,
            clock,
            RetainedCut::CleanCurrent,
        )
    }

    /// Root-only administrative recovery from the independently retained last
    /// Current physical image after the old publisher's actual retirement.
    /// Prior-boot retirement must come from the original checkpoint owner's
    /// separate actual-Root/clock/full-head observation. Ordinary pidfd
    /// retirement retains its original same-boot requirement.
    /// Dirty/proposal bytes are never a recovery source. The trusted caller
    /// holds the new original canonical writer dispatch fence throughout.
    /// This does not install owner files, open a writer or release Session.
    pub fn adopt_retained_material_after_root_restart(
        directory: Arc<RootAuthorityDirectory>,
        previous: &CognitiveCheckpointReceipt,
        predecessor: &RetiredCheckpointPublisher,
        registration: HostCognitiveCheckpointRegistration,
        successor: &RetainedCheckpointPublisher,
        clock: Arc<dyn AuthorityClock>,
        material: &codex_hepta_memory::VerifiedCognitiveMaterial,
    ) -> Result<Self, AuthorityTrustError> {
        Self::adopt_current_with_predecessor(
            directory,
            previous,
            Predecessor::Retired(predecessor),
            registration,
            successor,
            clock,
            RetainedCut::Physical(material),
        )
    }

    fn adopt_current_with_predecessor(
        directory: Arc<RootAuthorityDirectory>,
        previous: &CognitiveCheckpointReceipt,
        predecessor: Predecessor<'_>,
        registration: HostCognitiveCheckpointRegistration,
        successor: &RetainedCheckpointPublisher,
        clock: Arc<dyn AuthorityClock>,
        material: RetainedCut<'_>,
    ) -> Result<Self, AuthorityTrustError> {
        let next =
            Self::successor_head(previous, &predecessor, &registration, successor, &material)?;
        let old = &previous.head;
        let new_writer = &registration.writer_binding;
        let store = HostAuthorityFrontierStore::open(directory, STORE_OWNER.into())?;
        material.validate(old)?;
        let before = clock.now_unix_ms()?;
        let expiry = new_writer.expires_at_unix_seconds * 1000;
        if before >= expiry {
            return Err(AuthorityTrustError::Unavailable);
        }
        // Exact old head CAS, original file/directory sync and exact readback.
        // The original last_current cut is carried byte-for-byte, never rehashed
        // from a possibly modified database. A lost result must be reconciled
        // by opening the actual new registration, never by minting another one.
        store
            .compare_and_set(STORE_OWNER, old, &next)
            .map_err(|error| match error {
                AuthorityTrustError::Conflict => AuthorityTrustError::Conflict,
                AuthorityTrustError::Invalid | AuthorityTrustError::Unavailable => {
                    AuthorityTrustError::Unavailable
                }
            })?;
        // A durable CAS may already have committed. Every later failure is
        // uncertain, even when an underlying clock or pidfd reports Conflict.
        predecessor
            .require_retired()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        material
            .validate(old)
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        // All blocking metadata and retirement I/O precedes this final clock.
        // Only the original nonblocking successor pidfd poll follows it.
        let after = clock
            .now_unix_ms()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if after < before || after >= expiry {
            return Err(AuthorityTrustError::Unavailable);
        }
        successor
            .require_alive()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        Ok(Self {
            registration,
            store,
            clock,
            closed: AtomicBool::new(false),
            exchange_lock: Mutex::new(()),
        })
    }
    // One original complete transition definition for both adoption and later
    // fixed-owner installation. Installation may only recheck this exact head;
    // it does not synthesize another token, CAS, epoch or counter.
    fn successor_head(
        previous: &CognitiveCheckpointReceipt,
        predecessor: &Predecessor<'_>,
        registration: &HostCognitiveCheckpointRegistration,
        successor: &RetainedCheckpointPublisher,
        material: &RetainedCut<'_>,
    ) -> Result<CognitiveCheckpointHead, AuthorityTrustError> {
        validate_registration(registration)?;
        let old = &previous.head;
        let old_registration = HostCognitiveCheckpointRegistration {
            owner_agent_id: old.owner_agent_id.clone(),
            publisher_epoch: old.publisher_epoch,
            writer_binding: old.writer_binding.clone(),
            peer_lifetime: old.peer_lifetime.clone(),
        };
        validate_registration(&old_registration)?;
        validate_head(&old_registration, old)?;
        let old_writer = &old.writer_binding;
        let new_writer = &registration.writer_binding;
        material.validate(old)?;
        if token_for(old)? != previous.token
            || old.owner_agent_id != registration.owner_agent_id
            || old.publisher_epoch.checked_add(1) != Some(registration.publisher_epoch)
            || predecessor.lifetime() != &old.peer_lifetime
            || successor.lifetime != registration.peer_lifetime
            || old.peer_lifetime == registration.peer_lifetime
            || old.peer_lifetime.uid != registration.peer_lifetime.uid
            || old_writer.lease_id != new_writer.lease_id
            || old_writer.generation.checked_add(1) != Some(new_writer.generation)
            || (old_writer.authority_epoch, old_writer.owner_epoch)
                >= (new_writer.authority_epoch, new_writer.owner_epoch)
            || old_writer.authority_grant_digest == new_writer.authority_grant_digest
            || old_writer.fencing_token_digest == new_writer.fencing_token_digest
        {
            return Err(AuthorityTrustError::Invalid);
        }
        // The ordinary retained/same-boot paths keep their original boot
        // equality. Only a separate Root observation of the actual prior boot
        // and its exact protected head can admit a physical cross-boot cut.
        predecessor.validate_boot_transition(previous, &registration.peer_lifetime, material)?;
        predecessor.require_retired()?;
        successor.require_alive()?;
        let mut next = old.clone();
        next.publisher_epoch = registration.publisher_epoch;
        next.counter = old
            .counter
            .checked_add(1)
            .ok_or(AuthorityTrustError::Invalid)?;
        next.last_mutation_sequence = 0;
        next.last_request = None;
        next.writer_binding = new_writer.clone();
        next.peer_lifetime = registration.peer_lifetime.clone();
        // The full old head remains the CAS predecessor. Only a separately
        // validated protected image can promote its exact last_current; no
        // dirty database or uncommitted proposal supplies replacement bytes.
        next.phase = CognitiveCheckpointPhase::Current;
        next.proposal = None;
        validate_head(registration, &next)?;
        Ok(next)
    }

    /// Keep the original exchange lock through physical publication and the
    /// caller's final canonical/lifetime/time checks. The caller already holds
    /// the original Registry fence and must not re-enter either lock from the
    /// finalizer. No wire exposes this operation.
    pub(crate) fn install_recovered_material_for_root(
        &self,
        previous: &CognitiveCheckpointReceipt,
        predecessor: &RetiredCheckpointPublisher,
        successor: &RetainedCheckpointPublisher,
        material: codex_hepta_memory::VerifiedCognitiveMaterial,
        layout: &codex_hepta_paths::HeptaAgentLayout,
        validate_after: impl FnOnce(
            &codex_hepta_memory::InstalledCognitiveMaterial,
            u64,
            u64,
        ) -> Result<(), AuthorityTrustError>,
    ) -> Result<codex_hepta_memory::InstalledCognitiveMaterial, AuthorityTrustError> {
        let _guard = self.exchange_lock.lock().map_err(|_| self.close())?;
        let result = (|| {
            if self.closed.load(Ordering::Acquire) {
                return Err(AuthorityTrustError::Unavailable);
            }
            let expected = Self::successor_head(
                previous,
                &Predecessor::Retired(predecessor),
                &self.registration,
                successor,
                &RetainedCut::Physical(&material),
            )?;
            if self.load()? != expected || layout.agent_id() != &expected.owner_agent_id {
                return Err(AuthorityTrustError::Invalid);
            }
            let before = self.clock.now_unix_ms()?;
            let expiry = self.registration.writer_binding.expires_at_unix_seconds * 1000;
            if before >= expiry {
                return Err(AuthorityTrustError::Unavailable);
            }
            let installed = material
                .install_for_registered_owner(layout, &expected.last_current)
                .map_err(|_| AuthorityTrustError::Unavailable)?;
            // Publication may already be durable. Later uncertainty is always
            // Unknown; never delete or retry the new image or changed pointer.
            if self.load()? != expected {
                return Err(AuthorityTrustError::Unavailable);
            }
            predecessor.require_retired()?;
            installed
                .verify_unchanged()
                .map_err(|_| AuthorityTrustError::Unavailable)?;
            validate_after(&installed, before, expiry)?;
            // Only this nonblocking held-pidfd poll follows the finalizer's
            // protected clock, while both original locks remain held.
            successor.require_alive()?;
            Ok(installed)
        })();
        result.map_err(|_| self.close())
    }
}

#[cfg(test)]
#[path = "authority_host_checkpoint_adoption_tests.rs"]
mod tests;
