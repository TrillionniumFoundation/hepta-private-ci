//! Read the SAME existing effect owner. Retained observations grant no use.
use super::*;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseReadV1;
use codex_hepta_contracts::authority_lease::CapabilityRevocationReadV1;

pub(crate) struct OriginalGrantState {
    pub(crate) lease: AuthorityLeaseReadV1,
    pub(crate) revocation: Option<CapabilityRevocationReadV1>,
    pub(crate) frontier: AuthorityLeaseFrontier,
    pub(crate) head: FinalUseRevocations,
    pub(crate) grant_expired: bool,
}

impl RootNotesGrantAdmission {
    pub(crate) fn observe_original_grant_state(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        signed: &SignedFinalUseGrant,
        before: Instant,
    ) -> io::Result<OriginalGrantState> {
        actual_root_before(before)?;
        let binding = &signed.grant.binding;
        if binding.subject_id != self.policy.subject_id
            || binding.destination_id != self.policy.destination_id
            || binding.scope_sha256 != self.policy.scope_sha256
            || issuer.retained_writer_authorization(&self.writer)? != self.proof
        {
            return Err(denied("original Notes observation policy/proof mismatch"));
        }
        // An expired artifact can identify a read-only result. Mutation MUST
        // independently recheck current signed-grant time and live writer.
        let head = issuer.observe_original_signed_grant(signed, before)?;
        let lease_id = self.lease_id(binding)?;
        let frontier = self.registry.frontier().map_err(root::lease_error)?;
        let lease = self
            .registry
            .read_lease(&lease_id)
            .map_err(root::lease_error)?
            .ok_or_else(|| denied("original Notes effect lease absent; never create"))?;
        let revocation = self
            .registry
            .read_revocation(&lease_id)
            .map_err(root::lease_error)?;
        if self.registry.frontier().map_err(root::lease_error)? != frontier {
            return Err(denied("original Notes lease observation changed"));
        }
        let current = &lease.lease;
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
            || match &revocation {
                None => current.revision != 1,
                Some(record) => {
                    current.revision != 2
                        || record.revocation.lease_id != lease_id
                        || record.revocation.authority_epoch != current.authority_epoch
                        || record.revocation.lease_revision != current.revision
                        || record.revocation.reason_sha256 == [0; 32]
                }
            }
        {
            return Err(denied(
                "original signed Notes artifact and existing lease differ",
            ));
        }
        let grant_expired = issuer.clock.now_unix_ms().map_err(io::Error::other)?
            >= signed.grant.expires_at_unix_ms;
        actual_root_before(before)?;
        Ok(OriginalGrantState {
            lease,
            revocation,
            frontier,
            head,
            grant_expired,
        })
    }
}
