use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;

use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::RegisteredRelease;
use crate::ReleaseId;
use crate::ReleaseMetadata;
use crate::release_authority::CurrentPublication;
use crate::release_authority::FleetReleaseTrustConfig;
use crate::release_authority::ReleaseAuthority;
use crate::release_authority::ReleaseUse;
#[path = "release_registry_intents.rs"]
mod intents;
use crate::release_authority::invalid;

#[derive(Clone, Debug, Default)]
pub(crate) enum ReleaseMode {
    #[default]
    StateOnly,
    Pq(Arc<ReleaseAuthority>),
    #[cfg(any(test, feature = "qualification"))]
    Qualification,
}

/// A freshly checked release plus its local publication-owner lock. This is
/// neither serializable nor cloneable. Keep it alive through process dispatch;
/// every later start or adoption must obtain a new current admission.
pub struct CurrentReleaseAdmission {
    pub(crate) release: RegisteredRelease,
    pub(crate) catalog: crate::release::CatalogReleaseBinding,
    pub(crate) authority: Option<(Arc<ReleaseAuthority>, ReleaseUse)>,
}

impl CurrentReleaseAdmission {
    pub fn release(&self) -> &RegisteredRelease {
        &self.release
    }

    /// Required at the actual process entry, after any earlier resolve/hash or
    /// queue work. Recheck the actual immutable catalog, then the fresh frontier
    /// and clock. The retained lock prevents local publication-owner mutations;
    /// it is not an atomic execution lock against arbitrary filesystem mutation.
    pub fn revalidate(&self) -> Result<(), FleetRegistryError> {
        crate::release::revalidate_catalog_release(&self.catalog, &self.release)?;
        match &self.authority {
            Some((owner, admission)) => owner.recheck(&admission.publication).map(|_| ()),
            None => Ok(()),
        }
    }

    /// Checks both the process release and an exact signed protocol policy
    /// under this one owner lock and the same fresh trusted clock observation.
    /// This avoids taking a second non-reentrant publication-owner lock during
    /// a policy-controlled launch. Qualification-only releases cannot use it.
    pub fn revalidate_with_protocol_configuration(
        &self,
        content_sha256: [u8; 32],
    ) -> Result<u64, FleetRegistryError> {
        crate::release::revalidate_catalog_release(&self.catalog, &self.release)?;
        match &self.authority {
            Some((owner, admission)) => {
                owner.recheck_with_protocol_configuration(&admission.publication, content_sha256)
            }
            None => Err(FleetRegistryError::ReleaseAuthorityRequired),
        }
    }
}

/// Current M15 ProtocolConfiguration permission. Keep this guard through the
/// actual policy-controlled effect and revalidate immediately at that entry.
pub struct CurrentProtocolConfigurationAdmission {
    owner: Arc<ReleaseAuthority>,
    publication: CurrentPublication,
}

impl CurrentProtocolConfigurationAdmission {
    /// Returns the trusted Unix milliseconds used by this exact fresh check.
    /// It does not advance a durable clock floor merely by observing the time.
    pub fn revalidate(&self) -> Result<u64, FleetRegistryError> {
        self.owner.recheck(&self.publication)
    }
}

impl FleetRegistry {
    pub fn initialize_with_release_authority(
        root: HeptaFleetRoot,
        trust: FleetReleaseTrustConfig,
        initial_root_json: &[u8],
    ) -> Result<Self, FleetRegistryError> {
        let mut registry = Self::initialize(root)?;
        registry.release_authority = ReleaseMode::Pq(Arc::new(ReleaseAuthority::initialize(
            registry.layout().state_root(),
            trust,
            initial_root_json,
        )?));
        Ok(registry)
    }

    pub fn open_existing_with_release_authority(
        root: HeptaFleetRoot,
        trust: FleetReleaseTrustConfig,
    ) -> Result<Self, FleetRegistryError> {
        let mut registry = Self::open_existing(root)?;
        registry.release_authority = ReleaseMode::Pq(Arc::new(ReleaseAuthority::open(
            registry.layout().state_root(),
            trust,
        )?));
        Ok(registry)
    }

    /// Explicit recovery of a retained proposal whose complete fresh external
    /// frontier already proves commitment. It never retries an uncertain CAS.
    pub fn recover_completed_release_update(
        root: HeptaFleetRoot,
        trust: FleetReleaseTrustConfig,
    ) -> Result<Self, FleetRegistryError> {
        let mut registry = Self::open_existing(root)?;
        registry.release_authority = ReleaseMode::Pq(Arc::new(
            ReleaseAuthority::recover_completed(registry.layout().state_root(), trust)?,
        ));
        Ok(registry)
    }

    pub fn publish_release_set(&self, signed_set_json: &[u8]) -> Result<(), FleetRegistryError> {
        self.pq_release_authority()?.publish_set(signed_set_json)
    }

    pub fn rotate_release_root(
        &self,
        signed_rotation_json: &[u8],
    ) -> Result<(), FleetRegistryError> {
        self.pq_release_authority()?
            .rotate_root(signed_rotation_json)
    }

    pub fn publish_protocol_configuration(
        &self,
        signed_metadata_json: &[u8],
    ) -> Result<(), FleetRegistryError> {
        self.pq_release_authority()?
            .publish_protocol_configuration(signed_metadata_json)
    }

    pub fn admit_protocol_configuration(
        &self,
        content_sha256: [u8; 32],
    ) -> Result<CurrentProtocolConfigurationAdmission, FleetRegistryError> {
        match &self.release_authority {
            ReleaseMode::Pq(owner) => Ok(CurrentProtocolConfigurationAdmission {
                owner: Arc::clone(owner),
                publication: owner.protocol_configuration(content_sha256)?,
            }),
            _ => Err(FleetRegistryError::ReleaseAuthorityRequired),
        }
    }

    /// Compatibility fixtures only. Normal constructors and the daemon's
    /// configuration path never select this owner, even in a feature-unified
    /// development build.
    #[cfg(any(test, feature = "qualification"))]
    pub fn initialize_for_qualification(root: HeptaFleetRoot) -> Result<Self, FleetRegistryError> {
        let mut registry = Self::initialize(root)?;
        registry.release_authority = ReleaseMode::Qualification;
        Ok(registry)
    }

    #[cfg(any(test, feature = "qualification"))]
    pub fn open_existing_for_qualification(
        root: HeptaFleetRoot,
    ) -> Result<Self, FleetRegistryError> {
        let mut registry = Self::open_existing(root)?;
        registry.release_authority = ReleaseMode::Qualification;
        Ok(registry)
    }

    pub fn is_release_qualification(&self) -> bool {
        #[cfg(any(test, feature = "qualification"))]
        if matches!(self.release_authority, ReleaseMode::Qualification) {
            return true;
        }
        false
    }

    pub(crate) fn require_release_authority(&self) -> Result<(), FleetRegistryError> {
        if matches!(self.release_authority, ReleaseMode::StateOnly) {
            Err(FleetRegistryError::ReleaseAuthorityRequired)
        } else {
            Ok(())
        }
    }

    fn pq_release_authority(&self) -> Result<&ReleaseAuthority, FleetRegistryError> {
        match &self.release_authority {
            ReleaseMode::Pq(owner) => Ok(owner),
            _ => Err(FleetRegistryError::ReleaseAuthorityRequired),
        }
    }

    pub(crate) fn authorize_release_install(
        &self,
        metadata: &ReleaseMetadata,
    ) -> Result<Option<ReleaseUse>, FleetRegistryError> {
        self.require_release_authority()?;
        if self.is_release_qualification() {
            return Ok(None);
        }
        let current = self.pq_release_authority()?.member(&metadata.release_id)?;
        if current.metadata != *metadata {
            return Err(invalid(
                "copied release binaries, sizes or arguments differ from current publisher authorization",
            ));
        }
        Ok(Some(current))
    }

    pub(crate) fn revalidate_release_install(
        &self,
        current: &Option<ReleaseUse>,
    ) -> Result<(), FleetRegistryError> {
        match current {
            Some(current) => self
                .pq_release_authority()?
                .recheck(&current.publication)
                .map(|_| ()),
            None if self.is_release_qualification() => Ok(()),
            None => Err(FleetRegistryError::ReleaseAuthorityRequired),
        }
    }

    pub(crate) fn authorize_release_allowance(
        &self,
        agent: &AgentId,
        release: &ReleaseId,
        manifest: [u8; 32],
    ) -> Result<(), FleetRegistryError> {
        self.require_release_authority()?;
        if self.is_release_qualification() {
            return Ok(());
        }
        self.pq_release_authority()?.allow(agent, release, manifest)
    }

    pub(crate) fn authorize_release_revocation(
        &self,
        agent: &AgentId,
        release: &ReleaseId,
    ) -> Result<(), FleetRegistryError> {
        self.require_release_authority()?;
        if self.is_release_qualification() {
            return Ok(());
        }
        self.pq_release_authority()?.revoke(agent, release)
    }

    pub(crate) fn current_release_use(
        &self,
        agent: &AgentId,
        release: &ReleaseId,
    ) -> Result<Option<(Arc<ReleaseAuthority>, ReleaseUse)>, FleetRegistryError> {
        self.require_release_authority()?;
        if self.is_release_qualification() {
            return Ok(None);
        }
        match &self.release_authority {
            ReleaseMode::Pq(owner) => Ok(Some((Arc::clone(owner), owner.admit(agent, release)?))),
            _ => Err(FleetRegistryError::ReleaseAuthorityRequired),
        }
    }
}
