//! Register only under the same original issuer and writer mutex boundary.

use super::*;
use crate::HostAuthorityWriterRegistration;
use crate::worker_root_registration::refused;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::authority_lease::AuthorityLease;

impl HostAuthorityService {
    pub(crate) fn with_worker_registration_fence<T>(
        &self,
        publish: impl FnOnce(
            &AuthorityLease,
            &HostAuthorityWriterRegistration,
            Sha256Digest,
            u64,
        ) -> io::Result<T>,
    ) -> io::Result<T> {
        // SAFETY: these calls only read this process's actual credentials.
        if unsafe { libc::getuid() } != 0
            || unsafe { libc::geteuid() } != 0
            || self.root_registry.is_none()
        {
            return Err(refused("retained original Root registry required"));
        }
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| refused("original registered writer required"))?;
        if writer.registration.registered_agent_id != self.identity.agent_id
            || writer.registration.spawn_generation != self.identity.spawn_generation
        {
            return Err(refused("retained original writer identity differs"));
        }
        self.issuer
            .with_live_issuer_and_writer(&writer.registration, |issuer_lease| {
                let proof = self
                    .issuer
                    .retained_writer_authorization(&writer.registration)?;
                if proof != writer.proof {
                    return Err(refused("retained original writer proof changed"));
                }
                let head = self.issuer.revocations()?;
                let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
                validate_observation_lease(issuer_lease, &head, now)?;
                validate_observation_lease(&writer.registration.authority_lease, &head, now)?;
                let result = publish(
                    issuer_lease,
                    &writer.registration,
                    proof.sha256().map_err(io::Error::other)?,
                    now,
                )?;
                // This is still the same original Registry mutex; no nested live
                // token acquisition occurs inside the callback. Expiry after I/O
                // discards the retained object, closes its channel and never retries.
                if self.issuer.revocations()? != head
                    || self
                        .issuer
                        .retained_writer_authorization(&writer.registration)?
                        != proof
                {
                    return Err(refused(
                        "original issuer state changed during Worker registration",
                    ));
                }
                let after = self.clock.now_unix_ms().map_err(io::Error::other)?;
                validate_observation_lease(issuer_lease, &head, after)?;
                validate_observation_lease(&writer.registration.authority_lease, &head, after)?;
                Ok(result)
            })
    }
}
