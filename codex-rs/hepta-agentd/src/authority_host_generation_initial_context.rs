//! Original Root writer/lease/process fence for the independent initial
//! purpose. It has no learning profile and cannot create a writer or lease.

use super::*;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityServiceConfig;
use crate::authority_host_runtime::verify_pinned_process;
use codex_hepta_contracts::RootAuthorityDirectory;
use std::time::Duration;
use std::time::Instant;

impl HostAuthorityService {
    pub(crate) fn with_initial_publication_context(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner_pidfd: &OwnedFd,
        action: impl FnOnce(String) -> io::Result<()>,
    ) -> io::Result<()> {
        config.required_bind.verify()?;
        RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?;
        if config.schema_version != 1
            || registration.schema_version != 1
            || config.peer_uid == 0
            || config.peer_gid == 0
            || !(1..=500).contains(&config.timeout_ms)
            || !(1..=300_000).contains(&config.lifetime_ms)
            || !config
                .state_dir
                .starts_with(&config.required_bind.mountpoint)
            || registration.registered_identity.identity()? != self.identity
        {
            return Err(io::Error::other(
                "original bounded Root initial publication registration required",
            ));
        }
        let end = Instant::now() + Duration::from_millis(config.timeout_ms);
        verify_pinned_process(
            registration,
            config.peer_uid,
            config.peer_gid,
            owner_pidfd,
            end,
        )?;
        self.check_logind_lifetime()?;
        let writer: &RegisteredWriter = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("registered writer required"))?;
        if config.writer.as_ref() != Some(&writer.registration) {
            return Err(io::Error::other(
                "Root initial publication writer differs from retained config",
            ));
        }
        writer.registration.with_live(&writer.leases, |_| {
            if self
                .issuer
                .retained_writer_authorization(&writer.registration)?
                != writer.proof
            {
                return Err(io::Error::other("original initial writer proof changed"));
            }
            let proof = writer
                .proof
                .sha256()
                .map_err(io::Error::other)?
                .as_str()
                .to_owned();
            let before = self.issuer.revocations()?;
            validate_observation_lease(
                &writer.registration.authority_lease,
                &before,
                self.clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms,
            )?;
            action(proof)?;
            if self.issuer.revocations()? != before
                || self
                    .issuer
                    .retained_writer_authorization(&writer.registration)?
                    != writer.proof
            {
                return Err(io::Error::other(
                    "initial registration outcome uncertain; original authority changed",
                ));
            }
            validate_observation_lease(
                &writer.registration.authority_lease,
                &before,
                self.clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms,
            )?;
            self.check_logind_lifetime()?;
            verify_pinned_process(
                registration,
                config.peer_uid,
                config.peer_gid,
                owner_pidfd,
                end,
            )?;
            Ok(())
        })
    }
}
