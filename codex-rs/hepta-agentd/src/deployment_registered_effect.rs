//! Shared exact-effect lease admission for the original canonical issuer.
//! Both typed Root installations use the SAME original registry and joint
//! dispatch boundary. This module stores no state and creates no owner.
use super::writer::WriterRegistrationExt;
use super::*;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;

fn denied(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}

#[allow(clippy::too_many_arguments)]
pub(super) fn issue(
    issuer: &DeploymentFinalUseIssuer,
    registry: &AuthorityLeaseRegistry,
    registration: &HostAuthorityWriterRegistration,
    proof: &crate::HostSignedWriterAuthorizationV1,
    policy: &DeploymentGrantPolicy,
    lease_id: String,
    binding: &FinalUseBinding,
) -> io::Result<Option<SignedFinalUseGrant>> {
    if binding.subject_id != policy.subject_id
        || binding.destination_id != policy.destination_id
        || binding.scope_sha256 != policy.scope_sha256
        || binding.request_sha256 == [0; 32]
        || binding.payload_sha256 == [0; 32]
    {
        return Ok(None);
    }
    let canonical = &issuer
        .lease
        .as_ref()
        .ok_or_else(|| denied("protected canonical issuer required"))?
        .verifier;
    registration.with_live(canonical, |_| {
        if issuer.retained_writer_authorization(registration)? != *proof {
            return Err(denied("registered writer proof changed"));
        }
        Ok(())
    })?;
    let expected = AuthorityLeaseBinding {
        principal_id: binding.subject_id.clone(),
        operation_class: "runtime.agentd.production_operation".into(),
        destination_id: binding.destination_id.clone(),
        scope_sha256: binding.scope_sha256,
        payload_sha256: binding.payload_sha256,
    };
    // Mutation is outside the joint owner lock. Its completion may consume
    // the writer lifetime, so fresh opaque tokens are checked afterward.
    let read = match registry.read_lease(&lease_id).map_err(root::lease_error)? {
        Some(read) => read,
        None => {
            let now = issuer.clock.now_unix_ms().map_err(io::Error::other)?;
            let lease = AuthorityLease {
                schema_version: 1,
                lease_id: lease_id.clone(),
                revision: 1,
                authority_epoch: registration.authority_lease.authority_epoch,
                binding: expected.clone(),
                issued_at_unix_ms: now,
                expires_at_unix_ms: now
                    .checked_add(policy.lifetime_ms)
                    .ok_or_else(|| io::Error::other("registered effect lease clock overflow"))?
                    .min(registration.authority_lease.expires_at_unix_ms),
            };
            match registry.put_lease(lease, 0) {
                Ok(read) => read,
                // Another concurrent exact request may have won CAS. Read
                // that original full record; a pruned ID stays refused.
                Err(AuthorityLeaseError::RevisionMismatch) => registry
                    .read_lease(&lease_id)
                    .map_err(root::lease_error)?
                    .ok_or_else(|| denied("retired registered effect lease cannot be recreated"))?,
                Err(error) => return Err(root::lease_error(error)),
            }
        }
    };
    let effect = read.lease;
    if effect.schema_version != 1
        || effect.lease_id != lease_id
        || effect.revision != 1
        || effect.authority_epoch != registration.authority_lease.authority_epoch
        || effect.binding != expected
        || effect.issued_at_unix_ms < registration.authority_lease.issued_at_unix_ms
        || effect.expires_at_unix_ms > registration.authority_lease.expires_at_unix_ms
        || effect
            .expires_at_unix_ms
            .checked_sub(effect.issued_at_unix_ms)
            .is_none_or(|duration| duration == 0 || duration > policy.lifetime_ms)
    {
        return Err(denied(
            "retained registered effect lease differs from its registration",
        ));
    }
    let writer = &registration.authority_lease;
    let writer_token = canonical
        .verify_use(&writer.lease_id, writer.revision, &writer.binding)
        .map_err(root::lease_error)?;
    let effect_token = registry
        .verifier()
        .verify_use(&effect.lease_id, effect.revision, &expected)
        .map_err(root::lease_error)?;
    canonical
        .with_joint_dispatch_boundary(
            writer_token,
            &writer.binding,
            effect_token,
            &expected,
            |actual_writer, actual_effect, _| {
                if actual_writer != writer || actual_effect != &effect {
                    return Err(denied("registered effect signing boundary changed"));
                }
                issuer.issue_registered_final_use(
                    binding,
                    registration,
                    proof,
                    writer.expires_at_unix_ms.min(effect.expires_at_unix_ms),
                )
            },
        )
        .map_err(root::lease_error)?
}
