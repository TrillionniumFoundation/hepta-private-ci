//! Original Root Current plus actual kernel retirement, never a manager image.

use super::*;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::InstalledRootCheckpointImage;

/// Only the actual existing protected head, actual retired old lifetime and
/// actual live successor can construct this retained recovery preparation.
pub(crate) struct PreparedMaterialRecovery {
    previous: CognitiveCheckpointReceipt,
    predecessor: RetiredCheckpointPublisher,
    successor: RetainedCheckpointPublisher,
    registration: HostCognitiveCheckpointRegistration,
    profile: RootMaterialProfile,
    clock: Arc<dyn AuthorityClock>,
    directory: Arc<RootAuthorityDirectory>,
    material: RootCheckpointMaterial,
}

impl PreparedMaterialRecovery {
    pub(crate) fn observe(
        directory: Arc<RootAuthorityDirectory>,
        profile: RootMaterialProfile,
        registration: HostCognitiveCheckpointRegistration,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, AuthorityTrustError> {
        let store = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
            Arc::clone(&directory),
            STORE_OWNER.into(),
        )?;
        let head = store.load(STORE_OWNER)?;
        if head.phase != CognitiveCheckpointPhase::Current || head.proposal.is_some() {
            return Err(AuthorityTrustError::Invalid);
        }
        let previous = CognitiveCheckpointReceipt {
            token: token_for(&head)?,
            head,
        };
        let predecessor = RetiredCheckpointPublisher::observe(previous.head.peer_lifetime.clone())?;
        let successor = RetainedCheckpointPublisher::capture(registration.peer_lifetime.clone())?;
        adoption::validate_adoption(
            &previous,
            &adoption::Predecessor::Retired(&predecessor),
            &registration,
            &successor,
        )?;
        let material =
            RootCheckpointMaterial::open(profile.clone(), registration.peer_lifetime.clone())?;
        let result = Self {
            previous,
            predecessor,
            successor,
            registration,
            profile,
            clock,
            directory,
            material,
        };
        result.require_retirement_window()?;
        // No filesystem mutation, live DB capture or Current adoption here.
        result.material.verify(result.previous.clone())?;
        result.require_retirement_window()?;
        Ok(result)
    }

    pub(crate) fn install(&self) -> Result<InstalledRootCheckpointImage, AuthorityTrustError> {
        self.require_retirement_window()?;
        let installed = self.material.install(self.previous.clone())?;
        self.require_retirement_window()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        Ok(installed)
    }

    pub(crate) fn adopt(self) -> Result<HostCognitiveCheckpoint, AuthorityTrustError> {
        self.require_retirement_window()?;
        HostCognitiveCheckpoint::adopt_current_after_root_restart_with_material(
            self.directory,
            &self.previous,
            &self.predecessor,
            self.registration,
            &self.successor,
            self.clock,
            self.profile,
        )
    }

    fn require_retirement_window(&self) -> Result<(), AuthorityTrustError> {
        self.predecessor.require_retired()?;
        self.successor.require_alive()?;
        let now = self.clock.now_unix_ms()?;
        let old_expiry = self
            .previous
            .head
            .writer_binding
            .expires_at_unix_seconds
            .checked_mul(1_000)
            .ok_or(AuthorityTrustError::Invalid)?;
        let new_expiry = self
            .registration
            .writer_binding
            .expires_at_unix_seconds
            .checked_mul(1_000)
            .ok_or(AuthorityTrustError::Invalid)?;
        if now < old_expiry || now >= new_expiry {
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(())
    }
}
