//! Couple material to the original transition; never a second Current ledger.

use super::*;
use codex_hepta_memory::CognitiveCheckpointReceipt;

pub(super) enum FreshMaterial {
    LogicalOnly,
    Physical(RootMaterialProfile),
}

impl FreshMaterial {
    pub(super) fn prepare(
        self,
        head: &CognitiveCheckpointHead,
    ) -> Result<Option<RootCheckpointMaterial>, AuthorityTrustError> {
        match self {
            Self::LogicalOnly => Ok(None),
            Self::Physical(profile) => {
                let owner = RootCheckpointMaterial::open(profile, head.peer_lifetime.clone())?;
                owner.prepare(receipt(head)?, SourceCustody::FreshRoot)?;
                Ok(Some(owner))
            }
        }
    }
}

impl HostCognitiveCheckpoint {
    /// Called only by the original fresh service while its opaque fresh DB
    /// witness and original writer lock remain retained. No runtime wire entry.
    pub(crate) fn initialize_fresh_with_material(
        directory: Arc<RootAuthorityDirectory>,
        registration: HostCognitiveCheckpointRegistration,
        initial_cut: CognitiveRecoveryAnchor,
        clock: Arc<dyn AuthorityClock>,
        profile: RootMaterialProfile,
    ) -> Result<Self, AuthorityTrustError> {
        Self::initialize_fresh_inner(
            directory,
            registration,
            initial_cut,
            clock,
            FreshMaterial::Physical(profile),
        )
    }

    /// Existing-session open is verification only. It cannot capture material
    /// missing after a crash, promote Dirty/Publishing/Fenced, or reset expiry.
    pub(crate) fn require_existing_material(
        mut self,
        profile: RootMaterialProfile,
    ) -> Result<Self, AuthorityTrustError> {
        if self.material.is_some() || self.closed.load(Ordering::Acquire) {
            return Err(AuthorityTrustError::Invalid);
        }
        let head = self.current_for_handoff()?;
        let material = RootCheckpointMaterial::open(profile, head.peer_lifetime.clone())?;
        material.verify(receipt(&head)?)?;
        if !self.within_expiry()? {
            return Err(self.close());
        }
        self.material = Some(material);
        Ok(self)
    }

    fn prepare_material(&self, head: &CognitiveCheckpointHead) -> Result<(), AuthorityTrustError> {
        if head.phase == CognitiveCheckpointPhase::Current
            && let Some(material) = &self.material
        {
            material.prepare(receipt(head)?, SourceCustody::RegisteredPublisher)?;
        }
        Ok(())
    }

    fn verify_material(&self, head: &CognitiveCheckpointHead) -> Result<(), AuthorityTrustError> {
        if head.phase == CognitiveCheckpointPhase::Current
            && let Some(material) = &self.material
        {
            material.verify(receipt(head)?)?;
        }
        Ok(())
    }
}

fn receipt(
    head: &CognitiveCheckpointHead,
) -> Result<CognitiveCheckpointReceipt, AuthorityTrustError> {
    Ok(CognitiveCheckpointReceipt {
        head: head.clone(),
        token: token_for(head)?,
    })
}
