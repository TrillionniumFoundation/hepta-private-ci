//! Explicit material-backed startup; no crash-time fresh-capture fallback.

use super::*;
use crate::authority_host_checkpoint::RootMaterialProfile;

impl PreparedHostAuthoritySession {
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
