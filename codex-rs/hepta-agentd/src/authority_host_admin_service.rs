//! Checked same-object Root administration. No factory, path open or new lease.
use super::*;
use crate::authority_host_admin::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use std::time::Duration;
use std::time::Instant;

impl HostAuthorityService {
    pub(crate) fn validate_admin_registration(&self) -> io::Result<()> {
        if self.logind_session.is_none() {
            return Err(io::Error::other(
                "original physical login required for Root admin",
            ));
        }
        self.check_logind_lifetime()?;
        let registry = self.admin_registry()?;
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("registered writer required"))?;
        writer.registration.with_live(&registry.verifier(), |_| {
            if self
                .issuer
                .retained_writer_authorization(&writer.registration)?
                != writer.proof
            {
                return Err(io::Error::other("original Root admin writer proof changed"));
            }
            Ok(())
        })
    }

    pub(crate) fn check_admin_lifetime(&self) -> io::Result<()> {
        self.check_logind_lifetime()?;
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("registered writer required"))?;
        let (human, ui) = self
            .human_text
            .as_ref()
            .ok_or_else(|| io::Error::other("original live native UI required"))?;
        crate::authority_host_runtime::owner_alive(ui, Instant::now() + Duration::from_secs(1))?;
        self.check_logind_binding(&crate::deployment_issuer::TextHumanBinding {
            principal_id: human.principal_id.clone(),
            session_id: human.session_id.clone(),
            permission_revision: human.permission_revision,
            expires_at_ms: human.expires_at_ms,
            route: human.route.clone(),
        })?;
        self.issuer.with_live_lease(|issuer_lease| {
            let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
            if now >= issuer_lease.expires_at_unix_ms
                || now >= writer.registration.authority_lease.expires_at_unix_ms
                || now >= human.expires_at_ms
                || self
                    .issuer
                    .retained_writer_authorization(&writer.registration)?
                    != writer.proof
            {
                return Err(io::Error::other(
                    "original Root admin authority expired or changed",
                ));
            }
            Ok(())
        })
    }

    fn admin_registry(&self) -> io::Result<&AuthorityLeaseRegistry> {
        self.root_registry
            .as_deref()
            .ok_or_else(|| io::Error::other("original retained Root registry required"))
    }

    pub(crate) fn admin_request(
        &self,
        instance: &RootAdminInstance,
        action: &RootAdminAction,
    ) -> io::Result<RootAdminResponse> {
        let registry = self.admin_registry()?;
        let writer = self
            .writer
            .as_ref()
            .ok_or_else(|| io::Error::other("registered writer required"))?;
        let original = &writer.registration.authority_lease;
        match action {
            RootAdminAction::Observe => {
                let before = registry.frontier().map_err(io::Error::other)?;
                let head = self.issuer.revocations()?;
                let lease = registry
                    .read_lease(&original.lease_id)
                    .map_err(io::Error::other)?
                    .ok_or_else(|| io::Error::other("original writer lease missing"))?;
                let revoked = registry
                    .read_revocation(&original.lease_id)
                    .map_err(io::Error::other)?;
                let mut shape = lease.lease.clone();
                shape.revision = original.revision;
                if shape != *original
                    || (lease.lease != *original
                        && revoked.as_ref().is_none_or(|record| {
                            record.revocation.lease_revision != lease.lease.revision
                                || record.revocation.lease_revision
                                    != original.revision.checked_add(1).unwrap_or(0)
                        }))
                {
                    return Err(io::Error::other("original writer binding changed"));
                }
                let physical_current = if revoked.is_none() {
                    Some(self.observe_registered_physical_current()?)
                } else {
                    None
                };
                let after = registry.frontier().map_err(io::Error::other)?;
                if before != after
                    || lease.store_revision != before.store_revision
                    || self.issuer.revocations()? != head
                {
                    return Err(io::Error::other(
                        "original Root control frontier changed during observation",
                    ));
                }
                Ok(RootAdminResponse::Observed {
                    observation: RootAdminObservation {
                        instance: instance.clone(),
                        writer: lease,
                        writer_revocation: revoked,
                        lease_frontier: after,
                        final_use_head: head,
                        physical_current,
                    },
                })
            }
            RootAdminAction::RevokeWriter {
                expected_revision,
                reason_sha256,
            } => {
                if *expected_revision != original.revision || *reason_sha256 == [0; 32] {
                    return Err(io::Error::other(
                        "original writer revoke CAS or reason mismatch",
                    ));
                }
                let lease = registry
                    .read_lease(&original.lease_id)
                    .map_err(io::Error::other)?
                    .ok_or_else(|| io::Error::other("original writer lease missing"))?;
                if lease.lease != *original {
                    // Only exact idempotence is permitted, never a new CAS or
                    // permission after this original writer has been revoked.
                    let revoked = registry
                        .read_revocation(&original.lease_id)
                        .map_err(io::Error::other)?
                        .ok_or_else(|| io::Error::other("original writer lease changed"))?;
                    let mut shape = lease.lease.clone();
                    shape.revision = original.revision;
                    if shape != *original || revoked.revocation.reason_sha256 != *reason_sha256 {
                        return Err(io::Error::other("original writer revoke differs"));
                    }
                } else {
                    self.validate_admin_registration()?;
                }
                let receipt = registry
                    .revoke(&original.lease_id, *expected_revision, *reason_sha256)
                    .map_err(io::Error::other)?;
                Ok(RootAdminResponse::WriterRevoked {
                    instance: instance.clone(),
                    receipt,
                    lease_frontier: registry.frontier().map_err(io::Error::other)?,
                })
            }
        }
    }
}
