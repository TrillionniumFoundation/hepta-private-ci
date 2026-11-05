//! Root-only handoff of an already authenticated clean Current head.

use super::*;
use codex_hepta_memory::CognitiveCheckpointReceipt;

pub(super) enum Predecessor<'a> {
    Retained(&'a RetainedCheckpointPublisher),
    Retired(&'a RetiredCheckpointPublisher),
}

impl Predecessor<'_> {
    pub(super) fn lifetime(&self) -> &CognitiveCheckpointPeerLifetime {
        match self {
            Self::Retained(publisher) => &publisher.lifetime,
            Self::Retired(publisher) => &publisher.lifetime,
        }
    }

    pub(super) fn require_retired(&self) -> Result<(), AuthorityTrustError> {
        match self {
            Self::Retained(publisher) => publisher.require_exited(),
            Self::Retired(publisher) => publisher.require_retired(),
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
            AdoptMaterial::LogicalOnly,
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
            AdoptMaterial::LogicalOnly,
        )
    }

    pub(crate) fn adopt_current_after_root_restart_with_material(
        directory: Arc<RootAuthorityDirectory>,
        previous: &CognitiveCheckpointReceipt,
        predecessor: &RetiredCheckpointPublisher,
        registration: HostCognitiveCheckpointRegistration,
        successor: &RetainedCheckpointPublisher,
        clock: Arc<dyn AuthorityClock>,
        profile: RootMaterialProfile,
    ) -> Result<Self, AuthorityTrustError> {
        Self::adopt_current_with_predecessor(
            directory,
            previous,
            Predecessor::Retired(predecessor),
            registration,
            successor,
            clock,
            AdoptMaterial::Physical(profile),
        )
    }

    fn adopt_current_with_predecessor(
        directory: Arc<RootAuthorityDirectory>,
        previous: &CognitiveCheckpointReceipt,
        predecessor: Predecessor<'_>,
        registration: HostCognitiveCheckpointRegistration,
        successor: &RetainedCheckpointPublisher,
        clock: Arc<dyn AuthorityClock>,
        material: AdoptMaterial,
    ) -> Result<Self, AuthorityTrustError> {
        validate_adoption(previous, &predecessor, &registration, successor)?;
        let old = &previous.head;
        let new_writer = &registration.writer_binding;
        let before = clock.now_unix_ms()?;
        let expiry = new_writer.expires_at_unix_seconds * 1000;
        if before >= expiry {
            return Err(AuthorityTrustError::Unavailable);
        }
        let store = HostAuthorityFrontierStore::open(directory, STORE_OWNER.into())?;
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
        validate_head(&registration, &next)?;
        let material = material.prepare(previous, &next)?;
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
        let after = clock
            .now_unix_ms()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if after < before || after >= expiry {
            return Err(AuthorityTrustError::Unavailable);
        }
        predecessor
            .require_retired()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        successor
            .require_alive()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        Ok(Self {
            registration,
            store,
            clock,
            closed: AtomicBool::new(false),
            exchange_lock: Mutex::new(()),
            material,
        })
    }
}

enum AdoptMaterial {
    LogicalOnly,
    Physical(RootMaterialProfile),
}

impl AdoptMaterial {
    fn prepare(
        self,
        previous: &CognitiveCheckpointReceipt,
        next: &CognitiveCheckpointHead,
    ) -> Result<Option<RootCheckpointMaterial>, AuthorityTrustError> {
        match self {
            Self::LogicalOnly => Ok(None),
            Self::Physical(profile) => {
                let material = RootCheckpointMaterial::open(profile, next.peer_lifetime.clone())?;
                material.rebind(
                    previous.clone(),
                    CognitiveCheckpointReceipt {
                        token: token_for(next)?,
                        head: next.clone(),
                    },
                )?;
                Ok(Some(material))
            }
        }
    }
}

pub(super) fn validate_adoption(
    previous: &CognitiveCheckpointReceipt,
    predecessor: &Predecessor<'_>,
    registration: &HostCognitiveCheckpointRegistration,
    successor: &RetainedCheckpointPublisher,
) -> Result<(), AuthorityTrustError> {
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
    if old.phase != CognitiveCheckpointPhase::Current
        || token_for(old)? != previous.token
        || old.owner_agent_id != registration.owner_agent_id
        || old.publisher_epoch.checked_add(1) != Some(registration.publisher_epoch)
        || predecessor.lifetime() != &old.peer_lifetime
        || successor.lifetime != registration.peer_lifetime
        || old.peer_lifetime == registration.peer_lifetime
        || old.peer_lifetime.uid != registration.peer_lifetime.uid
        || old.peer_lifetime.boot_id != registration.peer_lifetime.boot_id
        || old_writer.lease_id != new_writer.lease_id
        || old_writer.generation.checked_add(1) != Some(new_writer.generation)
        || (old_writer.authority_epoch, old_writer.owner_epoch)
            >= (new_writer.authority_epoch, new_writer.owner_epoch)
        || old_writer.authority_grant_digest == new_writer.authority_grant_digest
        || old_writer.fencing_token_digest == new_writer.fencing_token_digest
    {
        return Err(AuthorityTrustError::Invalid);
    }
    predecessor.require_retired()?;
    successor.require_alive()?;
    Ok(())
}

#[cfg(test)]
#[path = "authority_host_checkpoint_adoption_tests.rs"]
mod tests;
