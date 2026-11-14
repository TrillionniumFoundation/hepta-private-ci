//! The original issuer and writer are held in one canonical registry boundary.
//! This avoids recursively acquiring the writer boundary during C issuance.

use std::time::Instant;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;

use super::*;
use crate::HostAuthorityWriterRegistration;
use crate::HostSignedWriterAuthorizationV1;
use crate::authority_host_runtime::verify_pinned_process;

impl HostAuthorityService {
    pub(super) fn with_generation_grant_context<T>(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        learning: &RegisteredHostLearningCheckpointV1,
        end: Instant,
        action: impl FnOnce(
            LearningIterationSnapshotV1,
            String,
            &HostAuthorityWriterRegistration,
            &HostSignedWriterAuthorizationV1,
            u64,
        ) -> io::Result<T>,
    ) -> io::Result<T> {
        refusal::require_end(end)?;
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
                "original bounded Root grant context required",
            ));
        }
        verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
        self.check_logind_lifetime()?;
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("registered writer required"))?;
        if config.writer.as_ref() != Some(&writer.registration) {
            return Err(io::Error::other("original publication writer differs"));
        }
        self.issuer
            .with_live_issuer_and_writer(&writer.registration, |issuer_lease| {
                if self
                    .issuer
                    .retained_writer_authorization(&writer.registration)?
                    != writer.proof
                {
                    return Err(io::Error::other(
                        "original publication writer proof changed",
                    ));
                }
                let proof = writer
                    .proof
                    .sha256()
                    .map_err(io::Error::other)?
                    .as_str()
                    .to_owned();
                let initial = learning.profile.require_binding(&self.identity, &proof)?;
                let before = self.issuer.revocations()?;
                let now = self
                    .clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms;
                super::super::validate_observation_lease(issuer_lease, &before, now)?;
                super::super::validate_observation_lease(
                    &writer.registration.authority_lease,
                    &before,
                    now,
                )?;
                refusal::require_end(end)?;
                let expiry = issuer_lease
                    .expires_at_unix_ms
                    .min(writer.registration.authority_lease.expires_at_unix_ms);
                let result = action(initial, proof, &writer.registration, &writer.proof, expiry);
                // Keep both actual lease tokens through every postcheck, even when
                // signing or its physical publication checks already returned Err.
                if self.issuer.revocations()? != before
                    || self
                        .issuer
                        .retained_writer_authorization(&writer.registration)?
                        != writer.proof
                {
                    return Err(io::Error::other(
                        "original issuer or writer changed during C grant",
                    ));
                }
                let after = self
                    .clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms;
                super::super::validate_observation_lease(issuer_lease, &before, after)?;
                super::super::validate_observation_lease(
                    &writer.registration.authority_lease,
                    &before,
                    after,
                )?;
                self.check_logind_lifetime()?;
                verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
                refusal::require_end(end)?;
                result
            })
    }
}
