//! Explicit late admission for one pre-enrolled, fixed native training plan.
//! No enrollment, policy, writer, issuer, epoch or material is created here.

use super::*;
use crate::authority_host_service::OriginalHumanLifetime;
use crate::paired_preparation::material_protocol::PairedTrainingReadRequest;
use codex_hepta_contracts::HostAuthorityPeerResponse;
use codex_hepta_contracts::authority_lease::AuthorityLeaseError;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RootPairedTrainingPlanV1 {
    pub training: crate::PairedTrainingPlanV1,
    pub enrollment_revision: u64,
    pub effect_lifetime_ms: u64,
}

/// These borrowed original owners cannot extend the response or human lifetime.
pub(crate) struct OriginalPairedTrainingAdmission<'a, 'h, 'p> {
    pub(crate) identity: &'a AgentdIdentity,
    pub(crate) request: &'a PairedTrainingReadRequest,
    pub(crate) held: &'a OriginalHumanLifetime<'h>,
    pub(crate) response: &'a HostAuthorityPeerResponse<'p>,
}

impl RootPairedTrainingPlanV1 {
    pub fn validate(&self) -> io::Result<()> {
        self.training.validate().map_err(io::Error::other)?;
        if self.enrollment_revision == 0 || !(1..=10_000).contains(&self.effect_lifetime_ms) {
            return Err(denied(
                "invalid original training enrollment revision or effect lifetime",
            ));
        }
        Ok(())
    }

    pub(crate) fn admit_original_training(
        &self,
        issuer: Arc<DeploymentFinalUseIssuer>,
        registry: Arc<AuthorityLeaseRegistry>,
        writer: HostAuthorityWriterRegistration,
        original: OriginalPairedTrainingAdmission<'_, '_, '_>,
    ) -> io::Result<RegisteredRootPaired> {
        // SAFETY: observes existing kernel credentials; it changes no identity.
        if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
            return Err(denied(
                "late paired admission requires the original Root owner",
            ));
        }
        self.admit_checked(issuer, registry, writer, original)
    }

    pub(super) fn admit_checked(
        &self,
        issuer: Arc<DeploymentFinalUseIssuer>,
        registry: Arc<AuthorityLeaseRegistry>,
        writer: HostAuthorityWriterRegistration,
        original: OriginalPairedTrainingAdmission<'_, '_, '_>,
    ) -> io::Result<RegisteredRootPaired> {
        self.validate()?;
        let human = original.held.binding();
        original.held.recheck_original_human_lifetime(&human)?;
        original
            .response
            .current()
            .recheck_original_exchange()
            .map_err(io::Error::other)?;
        if original.identity.agent_id != writer.registered_agent_id
            || original.identity.spawn_generation != writer.spawn_generation
            || human.principal_id != self.training.preparation.principal_id
            || human.route.agent_id != writer.registered_agent_id
            || human.route.spawn_generation != writer.spawn_generation
        {
            return Err(denied(
                "late paired admission differs from its original owners",
            ));
        }
        let ingress = original.request.ingress();
        let signed = codex_hepta_authbus::SignedMessage {
            claims: crate::authbus_text_claims(&original.identity.agent_id, ingress)
                .map_err(io::Error::other)?,
            signature: crate::authbus_trust::hex_bytes(&ingress.signature_hex)
                .map_err(io::Error::other)?,
        };
        let request = self
            .training
            .request_for_original(
                original.request.proposed_original_turn()?,
                signed.delivery_id(),
            )
            .map_err(io::Error::other)?;
        if ingress.body.text != self.training.consent_text().map_err(io::Error::other)? {
            return Err(denied(
                "original retained text differs from the frozen training purpose",
            ));
        }
        let registration = HostAuthorityPairedRegistration {
            preparation: self.training.preparation.clone(),
            request,
            original_route: human.route.clone(),
            permission_revision: human.permission_revision,
            human_expires_at_ms: human.expires_at_ms,
            enrollment_revision: self.enrollment_revision,
            effect_revision: 1,
            effect_lifetime_ms: self.effect_lifetime_ms,
        };
        self.training.manifest.matches(&registration)?;
        let (expected_enrollment, expected_effect, policy) = registration.bindings(&writer)?;
        let enrollment = registry
            .read_lease(&registration.enrollment_id()?)
            .map_err(root::lease_error)?
            .ok_or_else(|| denied("pre-enrolled training record is missing"))?
            .lease;
        if enrollment.binding != expected_enrollment
            || enrollment.revision != self.enrollment_revision
            || enrollment.authority_epoch != writer.authority_lease.authority_epoch
        {
            return Err(denied(
                "pre-enrolled training record differs from the frozen plan",
            ));
        }
        let proof = issuer.retained_writer_authorization(&writer)?;
        original
            .request
            .verify_registered(&registration, &writer, &proof)?;
        // The same original Registry locks issuer + writer + enrollment. The
        // loaded issuer-state human predicate never reacquires those locks.
        let check = || -> io::Result<(u64, u64)> {
            original
                .response
                .current()
                .recheck_original_exchange()
                .map_err(io::Error::other)?;
            issuer.with_live_issuer_writer_effect(
                &writer,
                &enrollment,
                &registry.verifier(),
                |issuer_lease| {
                    let _guard = issuer
                        .request_lock
                        .lock()
                        .map_err(|_| denied("issuer fenced"))?;
                    let state = issuer.store.load(STATE_OWNER).map_err(io::Error::other)?;
                    if state
                        .policies
                        .iter()
                        .filter(|value| value.destination_id == policy.destination_id)
                        .collect::<Vec<_>>()
                        != vec![&policy]
                        || issuer.retained_writer_authorization(&writer)? != proof
                    {
                        return Err(denied(
                            "original fixed training policy or writer proof changed",
                        ));
                    }
                    let now = issuer.clock.now_unix_ms().map_err(io::Error::other)?;
                    let text_expiry = state.verify_retained_human_text_at(
                        original.identity,
                        ingress,
                        &human,
                        &original.held.namespace(),
                        now,
                    )?;
                    original.held.recheck_original_human_lifetime(&human)?;
                    original
                        .response
                        .current()
                        .recheck_original_exchange()
                        .map_err(io::Error::other)?;
                    let after = issuer.clock.now_unix_ms().map_err(io::Error::other)?;
                    let expiry = [
                        issuer_lease.expires_at_unix_ms,
                        writer.authority_lease.expires_at_unix_ms,
                        enrollment.expires_at_unix_ms,
                        human.expires_at_ms,
                        ingress.expires_at_ms,
                        text_expiry,
                    ]
                    .into_iter()
                    .min()
                    .ok_or_else(|| denied("original training lifetime missing"))?;
                    if after < now || after >= expiry {
                        return Err(denied("original training owners expired during admission"));
                    }
                    Ok((after, expiry))
                },
            )
        };
        let (now, expiry) = check()?;
        let effect_id = registration.effect_id();
        if registry
            .read_lease(&effect_id)
            .map_err(root::lease_error)?
            .is_none()
        {
            let effect = AuthorityLease {
                schema_version: 1,
                lease_id: effect_id.clone(),
                revision: 1,
                authority_epoch: writer.authority_lease.authority_epoch,
                binding: expected_effect,
                issued_at_unix_ms: now,
                expires_at_unix_ms: now
                    .checked_add(self.effect_lifetime_ms)
                    .ok_or_else(|| denied("paired effect clock overflow"))?
                    .min(expiry),
            };
            original
                .response
                .current()
                .recheck_original_exchange()
                .map_err(io::Error::other)?;
            // Outside the dispatch lock. Revision one / expected zero cannot
            // replace, renew or recreate an ID retained by registry pruning.
            match registry.put_lease(effect, /*expected_revision*/ 0) {
                Ok(_) => {}
                Err(AuthorityLeaseError::RevisionMismatch) => {
                    registry
                        .read_lease(&effect_id)
                        .map_err(root::lease_error)?
                        .ok_or_else(|| denied("retired paired effect cannot be recreated"))?;
                }
                Err(error) => return Err(root::lease_error(error)),
            }
        }
        check()?;
        let owner = RegisteredRootPaired::open(issuer, registry, writer, registration)?;
        original
            .response
            .current()
            .recheck_original_exchange()
            .map_err(io::Error::other)?;
        Ok(owner)
    }
}
