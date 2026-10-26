//! Explicit material-backed startup; no crash-time fresh-capture fallback.

use super::*;
use crate::authority_host_checkpoint::RootMaterialProfile;

impl PreparedHostAuthoritySession {
    /// Observe this same service's actual complete Current and independently
    /// verified physical image. The returned DTO has no authority or write FD.
    pub fn observe_physical_current(&self) -> io::Result<crate::HostPhysicalCurrentObservation> {
        let end = Instant::now() + std::time::Duration::from_secs(30);
        verify_pinned_process(
            &self.registration,
            self.config.peer_uid,
            self.config.peer_gid,
            &self.owner_pidfd,
            end,
        )?;
        let observed = self.service.observe_registered_physical_current()?;
        verify_pinned_process(
            &self.registration,
            self.config.peer_uid,
            self.config.peer_gid,
            &self.owner_pidfd,
            end,
        )?;
        Ok(observed)
    }

    /// Complete only an existing Current's interrupted filesystem release.
    /// Open this same live registration with `open_with_physical_material`
    /// first. Root verifies the independently retained image against the
    /// unreleased generation, without capture, pointer mutation or adoption.
    pub fn resume_physical_material_handoff(self) -> io::Result<Self> {
        self.service.resume_registered_material_handoff(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
        )?;
        Ok(self)
    }

    /// Recover only the actual protected predecessor Current into this already
    /// registered successor. Root reads the independent material itself; callers
    /// supply no Current, digest, image path, reset flag or replacement grant.
    /// Existing consumer journals and original fencing rules remain in force.
    pub fn recover_with_physical_material(
        config_file: &Path,
        registration_file: &Path,
        owner_pidfd: OwnedFd,
    ) -> io::Result<Self> {
        let config = read_root_json(config_file)?;
        let registration = read_root_json(registration_file)?;
        let service = open_registered_writer(&config, &registration, &owner_pidfd)?
            .recover_material_from_registered(&config, &registration, &owner_pidfd)?;
        Ok(Self {
            config,
            registration,
            owner_pidfd,
            service,
            fresh_filesystem: false,
        })
    }

    /// Publish the genuinely fresh original DB and its independent Root0600
    /// image before Current genesis. The same retained Root service then owns
    /// runtime Current images. The original fresh witness holds the original
    /// writer lock throughout; manager JSON supplies no image, digest or cut.
    pub async fn prepare_fresh_with_physical_material(
        config_file: &Path,
        registration_file: &Path,
        owner_pidfd: OwnedFd,
    ) -> io::Result<Self> {
        let config = read_root_json(config_file)?;
        let registration: HostAuthorityRegistration = read_root_json(registration_file)?;
        let service = open_registered_writer(&config, &registration, &owner_pidfd)?;
        let fresh =
            crate::FreshHostCognitiveState::prepare(&registration.registered_identity).await?;
        let service = service.initialize_fresh_heads_with_material(
            &config,
            &registration,
            &owner_pidfd,
            fresh,
        )?;
        Ok(Self {
            config,
            registration,
            owner_pidfd,
            service,
            fresh_filesystem: true,
        })
    }

    /// Existing live-session open verifies only the already retained material
    /// against the actual original Current. This creates no image, Current,
    /// writer, grant or successor generation and refuses partial material.
    pub fn open_with_physical_material(
        config_file: &Path,
        registration_file: &Path,
        owner_pidfd: OwnedFd,
    ) -> io::Result<Self> {
        let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
        let registration: HostAuthorityRegistration = read_root_json(registration_file)?;
        let service = open_registered_service(&config, &registration, &owner_pidfd)?;
        let service = service.require_existing_physical_material(RootMaterialProfile {
            layout: registration.registered_identity.identity()?.layout,
            root: config.state_dir.join("cognitive-material-v1"),
            deadline: std::time::Duration::from_millis(config.timeout_ms.min(5_000)),
        })?;
        Ok(Self {
            config,
            registration,
            owner_pidfd,
            service,
            fresh_filesystem: false,
        })
    }
}
