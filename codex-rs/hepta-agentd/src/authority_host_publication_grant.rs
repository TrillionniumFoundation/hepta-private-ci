//! C issuance is reachable only through the same original publication lane.
//! A peer supplies equality checks, never a binding, writer or grant policy.

use std::time::Instant;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;

use super::*;
use crate::HostAuthorityWriterRegistration;
use crate::HostSignedWriterAuthorizationV1;
use crate::NeuronGenerationPredecessorCompletionV1;
use crate::authority_host_runtime::verify_pinned_process;

/// Not cloneable or deserializable. Only this original-slot handler can create
/// it, after the durable attempt and all current Root publication checks.
pub(crate) struct RootPreparedPublicationGrantV1<'a> {
    binding: FinalUseBinding,
    registration: &'a HostAuthorityWriterRegistration,
    proof: &'a HostSignedWriterAuthorizationV1,
    expiry: u64,
}

impl<'a> RootPreparedPublicationGrantV1<'a> {
    pub(crate) fn into_original_parts(
        self,
    ) -> (
        FinalUseBinding,
        &'a HostAuthorityWriterRegistration,
        &'a HostSignedWriterAuthorizationV1,
        u64,
    ) {
        (self.binding, self.registration, self.proof, self.expiry)
    }
}

impl RegisteredGenerationPublication {
    fn require_grant_cut(
        &self,
        learning: &RegisteredHostLearningCheckpointV1,
        scope: &FrozenLearningScopeV2,
        now: u64,
    ) -> io::Result<CurrentHead> {
        if PublicationVersion::from_purpose(&self.profile.purpose)? != PublicationVersion::DurableV2
            || self.profile.intent.supersedes.is_some()
            || !matches!(
                self.profile.intent.completion,
                NeuronGenerationPredecessorCompletionV1::OwnerDrained
                    | NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel
            )
        {
            return Err(io::Error::other("original drained V2 publication required"));
        }
        self.require_profile()?;
        self.require_history(learning, scope)?;
        self.require_previous()?;
        self.require_genesis()?;
        self.require_selection(now)?;
        let head = self
            .current
            .original_broker_head()
            .map_err(io::Error::other)?;
        if head.current != self.profile.intent.previous
            || head.prepared.as_ref() != Some(&self.profile.intent)
        {
            return Err(io::Error::other(
                "exact prepared predecessor CURRENT required",
            ));
        }
        Ok(head)
    }
}

impl HostAuthorityService {
    /// Caller holds the original publication refusal arm for the entire frame,
    /// including this method's joint-context and post-effect physical checks.
    pub(super) fn issue_generation_publication_grant(
        &self,
        slot: &RegisteredGenerationPublication,
        learning: &RegisteredHostLearningCheckpointV1,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        request: &Request,
        sequence: &mut u64,
        end: Instant,
    ) -> io::Result<Vec<u8>> {
        refusal::require_end(end)?;
        let Command::IssueFinalUse { expected, intent } = &request.command else {
            return Err(io::Error::other("original FinalUse command required"));
        };
        let version = PublicationVersion::DurableV2;
        if request.schema != version.schema()
            || request.purpose != version.purpose()
            || request.profile != slot.profile.binding
            || request.request_id != *sequence
        {
            return Err(io::Error::other(
                "original FinalUse purpose/profile/sequence differs",
            ));
        }
        *sequence = sequence
            .checked_add(1)
            .ok_or_else(|| io::Error::other("publication sequence exhausted"))?;
        let grant = slot
            .grant
            .as_ref()
            .ok_or_else(|| io::Error::other("original FinalUse slot was not registered"))?;
        let initial_data = learning.profile.original_initial_data()?;
        let scope = learning.profile.require_cell_scope(&initial_data)?;
        let mut before = None;
        let issued = self.with_generation_grant_context(
            config,
            registration,
            owner,
            learning,
            end,
            |initial, proof, writer, writer_proof, lease_expiry| {
                if initial != initial_data
                    || slot.profile.initial != initial.head_digest.to_string()
                    || slot.profile.scope != scope.binding().to_string()
                    || slot.profile.writer != proof
                    || slot.profile.identity
                        != crate::neuron_generation_process_identity_digest_v1(&self.identity)
                            .map_err(io::Error::other)?
                            .to_string()
                {
                    return Err(io::Error::other("original Root C grant context changed"));
                }
                let now = self
                    .clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms;
                let head = slot.require_grant_cut(learning, &scope, now)?;
                let expiry = initial
                    .request
                    .envelope
                    .expiry_unix_seconds
                    .checked_mul(1000)
                    .ok_or_else(|| io::Error::other("publication request expiry overflow"))?
                    .min(lease_expiry);
                if *expected != head_digest(&head)?
                    || *intent
                        != slot
                            .profile
                            .intent
                            .digest()
                            .map_err(io::Error::other)?
                            .to_string()
                    || now >= expiry
                {
                    return Err(io::Error::other(
                        "original prepared grant cut or expiry differs",
                    ));
                }
                before = Some(head.clone());
                // A crash after this CAS can never produce a fresh nonce on retry.
                RegisteredPublicationGrant::begin(grant)?;
                let admitted = RootPreparedPublicationGrantV1 {
                    binding: slot.profile.intent.binding().map_err(io::Error::other)?,
                    registration: writer,
                    proof: writer_proof,
                    expiry,
                };
                let result = self.issuer.issue_original_publication_final_use(admitted);
                let after = slot.require_grant_cut(
                    learning,
                    &scope,
                    self.clock
                        .refresh_projection()
                        .map_err(io::Error::other)?
                        .observed_unix_ms,
                )?;
                if after != head {
                    return Err(io::Error::other(
                        "CURRENT changed during original C signing",
                    ));
                }
                refusal::require_end(end)?;
                result?.ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::PermissionDenied,
                        "original C policy is not provisioned",
                    )
                })
            },
        );
        // The real context has returned, including error-path authority checks.
        // Physical postchecks are still run if signing returned an error.
        let after = slot.require_grant_cut(
            learning,
            &scope,
            self.clock
                .refresh_projection()
                .map_err(io::Error::other)?
                .observed_unix_ms,
        )?;
        verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
        refusal::require_end(end)?;
        if before.as_ref() != Some(&after) {
            return Err(io::Error::other(
                "original C signing context was not completed",
            ));
        }
        let signed = issued?;
        if self
            .clock
            .refresh_projection()
            .map_err(io::Error::other)?
            .observed_unix_ms
            >= signed.grant.expires_at_unix_ms
        {
            return Err(io::Error::other(
                "original C grant expired during postchecks",
            ));
        }
        let response = Response {
            schema: version.schema(),
            purpose: version.purpose().into(),
            request_id: request.request_id,
            profile: slot.profile.clone(),
            head: after.clone(),
            successor: None,
            grant: Some(signed.clone()),
        };
        let raw = serde_json::to_vec(&response).map_err(io::Error::other)?;
        if raw.len() > 16 * 1024 {
            return Err(io::Error::other("publication reply bound"));
        }
        RegisteredPublicationGrant::finish(grant, &signed)?;
        let final_time = self
            .clock
            .refresh_projection()
            .map_err(io::Error::other)?
            .observed_unix_ms;
        if slot.require_grant_cut(learning, &scope, final_time)? != after
            || final_time >= signed.grant.expires_at_unix_ms
        {
            return Err(io::Error::other("original C grant completion uncertain"));
        }
        verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
        refusal::require_end(end)?;
        Ok(raw)
    }
}

#[cfg(test)]
#[path = "authority_host_publication_grant_wire_tests.rs"]
mod tests;
