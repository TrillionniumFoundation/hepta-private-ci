//! Register only under the same original issuer and writer mutex boundary.

use super::*;
use crate::HostAuthorityWriterRegistration;
use crate::worker_root_registration::refused;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::authority_lease::AuthorityLease;

/// Read-only values sampled while the original issuer+writer fence is held.
/// This is not an issuer, a peer-provided clock or a FinalUse capability.
pub(crate) struct WorkerRootOwnerView {
    pub(crate) owner_id: String,
    pub(crate) issuer_key: crate::HostAuthorityPublicIssuerKeyV1,
    pub(crate) registered_agent_id: codex_hepta_contracts::AgentId,
    pub(crate) head: FinalUseRevocations,
    pub(crate) clock: Arc<HostAuthorityClock>,
    pub(crate) clock_projection: HostAuthorityClockProjection,
    pub(crate) observed_unix_ms: u64,
    pub(crate) expires_at_unix_ms: u64,
    pub(crate) writer_proof: crate::HostSignedWriterAuthorizationV1,
}

impl HostAuthorityService {
    pub(crate) fn with_worker_floor_fence<T>(
        &self,
        expected: Option<&crate::worker_root_registration::WorkerRootRegistrationV1>,
        operation: impl FnOnce(&WorkerRootOwnerView) -> io::Result<T>,
    ) -> io::Result<T> {
        self.with_worker_registration_fence(|issuer, writer, proof_hash, _now| {
            if let Some(expected) = expected {
                expected.validate()?;
                if expected.issuer_lease != *issuer
                    || expected.writer != *writer
                    || expected.writer_proof_sha256 != proof_hash
                    || expected.registered_agent_id != self.identity.agent_id
                    || expected.spawn_generation != self.identity.spawn_generation
                {
                    return Err(refused(
                        "Worker original issuer, writer or generation pins changed",
                    ));
                }
            }
            let writer_proof = self.issuer.retained_writer_authorization(writer)?;
            if writer_proof.sha256().map_err(io::Error::other)? != proof_hash {
                return Err(refused("Worker canonical writer proof changed"));
            }
            let head = self.issuer.revocations()?;
            let projection = self.clock.refresh_projection().map_err(io::Error::other)?;
            validate_observation_lease(issuer, &head, projection.observed_unix_ms)?;
            validate_observation_lease(
                &writer.authority_lease,
                &head,
                projection.observed_unix_ms,
            )?;
            let issuer_key: crate::HostAuthorityPublicIssuerKeyV1 = self.issuer.trust_key()?.into();
            let view = WorkerRootOwnerView {
                owner_id: issuer_key.key_id.clone(),
                issuer_key,
                registered_agent_id: self.identity.agent_id.clone(),
                head,
                clock: Arc::clone(&self.clock),
                clock_projection: projection.projection,
                observed_unix_ms: projection.observed_unix_ms,
                expires_at_unix_ms: issuer
                    .expires_at_unix_ms
                    .min(writer.authority_lease.expires_at_unix_ms),
                writer_proof,
            };
            // The enclosing boundary still owns the original Registry mutex
            // and repeats its post-I/O clock/head/proof checks. No callback
            // reacquires an issuer/lease token or creates an independent owner.
            operation(&view)
        })
    }

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
