//! Explicit same-boot recovery under the original Root factories. No CLI,
//! authority creation, data-directory handoff or alternate owner is provided.
use super::notes_startup::ReservedNotesStartup;
use super::*;
use crate::HostNotesRecoveryPredecessor;
use crate::authority_host_service::RetainedNotesRecovery;
use std::os::unix::net::UnixDatagram;

/// Non-serializable, single original Root recovery attempt. Keep this object
/// after an uncertain CAS and retry `advance` with its retained exact inputs.
/// Reopening after this object is lost is deliberately refused once the old
/// protected Current changed; this is not a new persistent recovery ledger.
pub struct PreparedHostNotesRecovery {
    config: HostAuthorityServiceConfig,
    registration: HostAuthorityRegistration,
    owner_pidfd: OwnedFd,
    recovery: RetainedNotesRecovery,
    startup: Option<ReservedNotesStartup>,
    ready: bool,
}

impl PreparedHostNotesRecovery {
    /// Admission from existing Root-owned configuration, canonical
    /// issuer/Registry, expired protected Current and actual retired process.
    /// The successor Registry lease must already be authorized by the original
    /// administrator. Missing production inputs never create fixture defaults.
    pub fn open(
        config_file: &Path,
        registration_file: &Path,
        owner_pidfd: OwnedFd,
        previous: HostNotesRecoveryPredecessor,
    ) -> io::Result<Self> {
        let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
        let registration: HostAuthorityRegistration = read_root_json(registration_file)?;
        validate_registered_process(&config, &registration, &owner_pidfd)?;
        let (clock, leases, issuer) = open_registered_issuer(&config)?;
        let service = HostAuthorityService::from_registered_owner(
            issuer,
            clock,
            registration.registered_identity.identity()?,
        )?
        .retain_original_root_registry(Arc::new(leases));
        let recovery = RetainedNotesRecovery::capture(service, &config, &registration, previous)?;
        validate_registered_process(&config, &registration, &owner_pidfd)?;
        Ok(Self {
            config,
            registration,
            owner_pidfd,
            recovery,
            startup: None,
            ready: false,
        })
    }

    /// Receive exactly one actual Session Reserved target before any writer,
    /// Current or policy mutation. A retry cannot supply another target/nonce.
    pub fn reserve_session(
        &mut self,
        profile_file: &Path,
        bootstrap: UnixDatagram,
        session_pidfd: OwnedFd,
        deployment: File,
    ) -> io::Result<()> {
        if self.startup.is_some() {
            return Err(io::Error::other(
                "actual Notes reservation is already retained",
            ));
        }
        let startup = ReservedNotesStartup::receive(
            &self.config,
            profile_file,
            bootstrap,
            session_pidfd,
            deployment,
        )?;
        startup.require_previous_target(self.recovery.previous_target())?;
        self.startup = Some(startup);
        Ok(())
    }

    /// Run or exactly reconcile the original three administrative boundaries.
    /// An error can follow durable mutation. Retain this object; no fresh path,
    /// replacement generation or different policy is an admissible retry.
    pub fn advance(&mut self) -> io::Result<()> {
        self.ready = false;
        let startup = self
            .startup
            .as_ref()
            .ok_or_else(|| io::Error::other("actual Notes reservation required before recovery"))?;
        validate_registered_process(&self.config, &self.registration, &self.owner_pidfd)?;
        startup.require_alive()?;
        self.recovery
            .advance(startup.target(), startup.lifetime_ms())?;
        startup.require_alive()?;
        validate_registered_process(&self.config, &self.registration, &self.owner_pidfd)?;
        self.ready = true;
        Ok(())
    }

    /// Seal only a reconciled result. This does not Activate Session or send
    /// Root handoff. The caller must still seal the original five-lane bootstrap
    /// against the existing consumer directories and use the original late
    /// handoff. OriginalAgentd remains the sole factory/FinalUse owner.
    /// Sealing or post-seal process-check failure is terminal for this attempt:
    /// the three CAS may already be durable, but a partial memfd is never reset
    /// or blindly rewritten. Only `advance` supports retained-context retries.
    pub fn finish(self) -> io::Result<PreparedHostAuthoritySession> {
        if !self.ready {
            return Err(io::Error::other(
                "a successful exact recovery result is required before sealing",
            ));
        }
        validate_registered_process(&self.config, &self.registration, &self.owner_pidfd)?;
        let startup = self
            .startup
            .ok_or_else(|| io::Error::other("actual Notes reservation required before sealing"))?;
        startup.require_alive()?;
        let prepared = PreparedHostAuthoritySession {
            config: self.config,
            registration: self.registration,
            owner_pidfd: self.owner_pidfd,
            service: self.recovery.into_service()?,
            fresh_filesystem: false,
        };
        startup.seal(&prepared)?;
        validate_registered_process(
            &prepared.config,
            &prepared.registration,
            &prepared.owner_pidfd,
        )?;
        Ok(prepared)
    }
}
