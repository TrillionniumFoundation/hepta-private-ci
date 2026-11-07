//! Same retained Root issuer revocation and a fact-only terminal receipt.
//! The typed result is minted only after the original registry's durable CAS.
use super::*;
use crate::authority_host_admin::LiveRootAdminRequest;
use crate::authority_host_admin::RootAdminInstance;
use crate::authority_host_admin::RootAdminResponse;
use crate::authority_host_admin::checked_step;
use crate::authority_host_admin::deadline;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_contracts::authority_lease::CapabilityRevocation;
use codex_hepta_contracts::authority_lease::RevocationReceipt;
use std::time::Instant;

/// A borrowed, non-cloneable terminal fact. It contains no use token and cannot
/// outlive or substitute another original service or registry.
pub(crate) struct CommittedIssuerRevocation<'a> {
    service: &'a HostAuthorityService,
    registry: &'a AuthorityLeaseRegistry,
    original: AuthorityLease,
    receipt: RevocationReceipt,
}

impl HostAuthorityService {
    pub(crate) fn revoke_original_issuer(
        &self,
        context: &LiveRootAdminRequest<'_>,
        expected_lease_id: &str,
        expected_revision: u64,
        reason_sha256: [u8; 32],
    ) -> io::Result<CommittedIssuerRevocation<'_>> {
        context.require_original_issuer_selector(self, expected_lease_id, expected_revision)?;
        if reason_sha256 == [0; 32] {
            return Err(io::Error::other("original issuer revoke reason required"));
        }
        self.validate_admin_registration()?;
        // Release the original live verifier lock before the registry CAS.
        // Holding with_live_lease across a mutation would deadlock that owner.
        let original = self.issuer.with_live_lease(|lease| Ok(lease.clone()))?;
        if original.lease_id != expected_lease_id || original.revision != expected_revision {
            return Err(io::Error::other("original issuer lease selector changed"));
        }
        let registry = self
            .root_registry
            .as_deref()
            .ok_or_else(|| io::Error::other("original retained Root registry required"))?;
        let receipt = checked_step(
            context.before(),
            || context.check_for(self),
            || {
                registry
                    .revoke_exact_before(&original, reason_sha256, context.before())
                    .map_err(io::Error::other)
            },
        )?;
        Ok(CommittedIssuerRevocation {
            service: self,
            registry,
            original,
            receipt,
        })
    }

    /// Keep the original actual hosts, login and finite windows checked after
    /// issuer self-revocation. Only the private terminal receipt route calls it.
    /// Ordinary administration still calls check_admin_lifetime unchanged.
    pub(crate) fn check_issuer_revocation_reply_hosts(&self, end: Instant) -> io::Result<()> {
        deadline::require_before(end)?;
        self.check_logind_lifetime()?;
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("original registered writer required"))?;
        let (human, ui) = self
            .human_text
            .as_ref()
            .ok_or_else(|| io::Error::other("original live native UI required"))?;
        crate::authority_host_runtime::owner_alive(ui, end)?;
        self.check_logind_binding(&crate::deployment_issuer::TextHumanBinding {
            principal_id: human.principal_id.clone(),
            session_id: human.session_id.clone(),
            permission_revision: human.permission_revision,
            expires_at_ms: human.expires_at_ms,
            route: human.route.clone(),
        })?;
        let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
        if now >= writer.registration.authority_lease.expires_at_unix_ms
            || now >= human.expires_at_ms
        {
            return Err(io::Error::other(
                "original revocation reply host window ended",
            ));
        }
        deadline::require_before(end)
    }
}

impl CommittedIssuerRevocation<'_> {
    pub(crate) fn confirm_original_issuer_revocation_response(
        self,
        service: &HostAuthorityService,
        instance: &RootAdminInstance,
        end: Instant,
    ) -> io::Result<RootAdminResponse> {
        if !std::ptr::eq(self.service, service)
            || service
                .root_registry
                .as_deref()
                .is_none_or(|registry| !std::ptr::eq(registry, self.registry))
        {
            return Err(io::Error::other("original revocation owner changed"));
        }
        let lease_frontier = confirm_committed(self.registry, &self.original, &self.receipt, end)?;
        Ok(RootAdminResponse::IssuerRevoked {
            instance: instance.clone(),
            receipt: self.receipt,
            lease_frontier,
        })
    }
}

/// Read only the same original registry. A late/mismatched response is unknown;
/// it neither cancels the committed revoke nor resends any mutation.
fn confirm_committed(
    registry: &AuthorityLeaseRegistry,
    original: &AuthorityLease,
    receipt: &RevocationReceipt,
    end: Instant,
) -> io::Result<AuthorityLeaseFrontier> {
    deadline::require_before(end)?;
    let mut postimage = original.clone();
    postimage.revision = original
        .revision
        .checked_add(1)
        .ok_or_else(|| io::Error::other("original issuer revision overflow"))?;
    if receipt.lease_id != original.lease_id
        || receipt.authority_epoch != original.authority_epoch
        || receipt.previous_lease_revision != original.revision
        || receipt.lease_revision != postimage.revision
        || receipt.reason_sha256 == [0; 32]
        || receipt.revoked_at_unix_ms == 0
    {
        return Err(io::Error::other("original issuer terminal receipt differs"));
    }
    let before = registry.frontier().map_err(io::Error::other)?;
    let canonical = registry
        .read_lease(&original.lease_id)
        .map_err(io::Error::other)?
        .ok_or_else(|| io::Error::other("original revoked issuer lease absent"))?;
    deadline::require_before(end)?;
    let retained = registry
        .read_revocation(&original.lease_id)
        .map_err(io::Error::other)?
        .ok_or_else(|| io::Error::other("original issuer revocation absent"))?;
    let after = registry.frontier().map_err(io::Error::other)?;
    let expected = CapabilityRevocation {
        schema_version: original.schema_version,
        lease_id: original.lease_id.clone(),
        authority_epoch: original.authority_epoch,
        lease_revision: receipt.lease_revision,
        store_revision: receipt.store_revision,
        reason_sha256: receipt.reason_sha256,
        revoked_at_unix_ms: receipt.revoked_at_unix_ms,
    };
    if before != after
        || after.authority_epoch != original.authority_epoch
        || canonical.store_revision != after.store_revision
        || receipt.store_revision > after.store_revision
        || canonical.lease != postimage
        || retained.revocation != expected
    {
        return Err(io::Error::other(
            "original issuer revocation confirmation unknown",
        ));
    }
    deadline::require_before(end)?;
    Ok(after)
}

#[cfg(test)]
#[path = "authority_host_admin_issuer_tests.rs"]
mod tests;
