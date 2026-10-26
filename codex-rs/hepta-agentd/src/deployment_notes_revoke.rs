//! Existing exact Notes lease/grant revocation; no signing or replacement.
use super::*;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::authority_lease::RevocationReceipt;

pub(crate) struct OriginalNotesRevokeInput<'a> {
    pub(crate) signed: &'a SignedFinalUseGrant,
    pub(crate) expected_effect_revision: u64,
    pub(crate) expected_issuer_revision: u64,
    pub(crate) reason_sha256: [u8; 32],
    pub(crate) before: Instant,
}

/// Only the original fixed Notes admission can construct this checked stage.
pub(crate) struct PreparedNotesGrantRevocation<'a> {
    notes: &'a RootNotesGrantAdmission,
    issuer: &'a DeploymentFinalUseIssuer,
    signed: &'a SignedFinalUseGrant,
    head: FinalUseRevocations,
    lease_id: String,
    expected_revision: u64,
    reason: [u8; 32],
    before: Instant,
}

pub(crate) struct EffectLeaseRevoked<'a> {
    issuer: &'a DeploymentFinalUseIssuer,
    signed: &'a SignedFinalUseGrant,
    head: FinalUseRevocations,
    receipt: RevocationReceipt,
    before: Instant,
}

impl RootNotesGrantAdmission {
    pub(crate) fn prepare_original_grant_revocation<'a>(
        &'a self,
        issuer: &'a DeploymentFinalUseIssuer,
        input: OriginalNotesRevokeInput<'a>,
    ) -> io::Result<PreparedNotesGrantRevocation<'a>> {
        actual_root_before(input.before)?;
        let signed = input.signed;
        let binding = &signed.grant.binding;
        if input.expected_effect_revision != 1
            || input.expected_issuer_revision == 0
            || input.reason_sha256 == [0; 32]
            || binding.subject_id != self.policy.subject_id
            || binding.destination_id != self.policy.destination_id
            || binding.scope_sha256 != self.policy.scope_sha256
        {
            return Err(denied("original Notes revoke policy/CAS mismatch"));
        }
        self.writer.with_live(&self.registry.verifier(), |_| {
            if issuer.retained_writer_authorization(&self.writer)? != self.proof {
                return Err(denied("original Notes revoke writer proof changed"));
            }
            Ok(())
        })?;
        let head = issuer.verify_original_signed_grant(signed, input.before)?;
        if head.revision != input.expected_issuer_revision {
            return Err(denied("original Notes revoke issuer revision mismatch"));
        }
        let lease_id = self.lease_id(binding)?;
        let current = self
            .registry
            .read_lease(&lease_id)
            .map_err(root::lease_error)?
            .ok_or_else(|| denied("original Notes effect lease missing; never create one"))?
            .lease;
        let revoked = self
            .registry
            .read_revocation(&lease_id)
            .map_err(root::lease_error)?;
        let expected = AuthorityLeaseBinding {
            principal_id: binding.subject_id.clone(),
            operation_class: "runtime.agentd.production_operation".into(),
            destination_id: binding.destination_id.clone(),
            scope_sha256: binding.scope_sha256,
            payload_sha256: binding.payload_sha256,
        };
        if current.schema_version != 1
            || current.lease_id != lease_id
            || current.authority_epoch != self.writer.authority_lease.authority_epoch
            || current.binding != expected
            || current.issued_at_unix_ms < self.writer.authority_lease.issued_at_unix_ms
            || current.expires_at_unix_ms > self.writer.authority_lease.expires_at_unix_ms
            || current
                .expires_at_unix_ms
                .checked_sub(current.issued_at_unix_ms)
                .is_none_or(|duration| duration == 0 || duration > self.policy.lifetime_ms)
            || signed.grant.not_before_unix_ms < current.issued_at_unix_ms
            || signed.grant.expires_at_unix_ms > current.expires_at_unix_ms
            || match &revoked {
                None => current.revision != input.expected_effect_revision,
                Some(record) => {
                    current.revision != input.expected_effect_revision + 1
                        || record.revocation.lease_id != lease_id
                        || record.revocation.authority_epoch != current.authority_epoch
                        || record.revocation.lease_revision != current.revision
                        || record.revocation.reason_sha256 != input.reason_sha256
                }
            }
        {
            return Err(denied(
                "original signed Notes grant and existing lease differ",
            ));
        }
        actual_root_before(input.before)?;
        Ok(PreparedNotesGrantRevocation {
            notes: self,
            issuer,
            signed,
            head,
            lease_id,
            expected_revision: input.expected_effect_revision,
            reason: input.reason_sha256,
            before: input.before,
        })
    }
}

impl<'a> PreparedNotesGrantRevocation<'a> {
    /// Caller must repeat the original borrowed service/owner checks immediately
    /// before this exact original CAS. This stage cannot create/reset a lease.
    pub(crate) fn revoke_effect_lease(self) -> io::Result<EffectLeaseRevoked<'a>> {
        actual_root_before(self.before)?;
        let receipt = self
            .notes
            .registry
            .revoke(&self.lease_id, self.expected_revision, self.reason)
            .map_err(root::lease_error)?;
        actual_root_before(self.before)?;
        Ok(EffectLeaseRevoked {
            issuer: self.issuer,
            signed: self.signed,
            head: self.head,
            receipt,
            before: self.before,
        })
    }
}

impl EffectLeaseRevoked<'_> {
    pub(crate) fn receipt(&self) -> &RevocationReceipt {
        &self.receipt
    }

    /// A second-store failure is not compensated or replaced by a fresh grant.
    /// The caller must report partial/unknown and observe the original state.
    pub(crate) fn revoke_original_grant(
        self,
    ) -> io::Result<(RevocationReceipt, FinalUseRevocations)> {
        actual_root_before(self.before)?;
        let head = self.issuer.revoke_at_observed_head(
            &self.signed.grant.grant_id,
            &self.head,
            self.before,
        )?;
        actual_root_before(self.before)?;
        Ok((self.receipt, head))
    }
}

fn actual_root_before(before: Instant) -> io::Result<()> {
    // SAFETY: these functions only sample actual scalar credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(denied("actual original Root required for Notes revocation"));
    }
    super::super::original_grant::require_before(before)
}
