//! First registration in the same original registry. This creates no effect.

use super::*;
use crate::authority_host_admin::deadline::require_before;
use std::time::Instant;

impl DeploymentFinalUseIssuer {
    pub(super) fn register_paired_enrollment_checked(
        &self,
        plan: &RootPairedTrainingPlanV1,
        registry: &AuthorityLeaseRegistry,
        writer: &HostAuthorityWriterRegistration,
        proof: &crate::HostSignedWriterAuthorizationV1,
        lifetime_ms: u64,
        end: Instant,
    ) -> io::Result<()> {
        require_before(end)?;
        plan.validate()?;
        if plan.enrollment_revision != 1 || !(1..=300_000).contains(&lifetime_ms) {
            return Err(denied(
                "only bounded first enrollment registration is supported",
            ));
        }
        let preparation = &plan.training.preparation;
        let id = HostAuthorityPairedRegistration::enrollment_id_for(preparation)?;
        let binding = HostAuthorityPairedRegistration::enrollment_binding_for(preparation)?;
        let policy = DeploymentGrantPolicy {
            subject_id: writer.registered_agent_id.as_str().into(),
            destination_id: binding.destination_id.clone(),
            scope_sha256: binding.scope_sha256,
            lifetime_ms: plan.effect_lifetime_ms,
        };
        let verifier = registry.verifier();
        let check = |parent: &AuthorityLease| -> io::Result<(u64, u64)> {
            require_before(end)?;
            let _guard = self
                .request_lock
                .try_lock()
                .map_err(|_| denied("issuer busy or fenced"))?;
            let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
            if state
                .policies
                .iter()
                .filter(|value| value.destination_id == policy.destination_id)
                .collect::<Vec<_>>()
                != vec![&policy]
                || self.retained_writer_authorization(writer)? != *proof
                || state.head.authority_epoch != writer.authority_lease.authority_epoch
            {
                return Err(denied("original enrollment policy, proof or epoch changed"));
            }
            let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
            let expiry = parent
                .expires_at_unix_ms
                .min(writer.authority_lease.expires_at_unix_ms);
            if now < parent.issued_at_unix_ms
                || now < writer.authority_lease.issued_at_unix_ms
                || now >= expiry
            {
                return Err(denied("original enrollment parents are not live"));
            }
            require_before(end)?;
            Ok((now, expiry))
        };
        let (now, parent_expiry) =
            self.with_live_issuer_writer_registration(writer, &verifier, &check)?;
        if registry
            .read_lease(&id)
            .map_err(root::lease_error)?
            .is_some()
        {
            return Err(denied(
                "original enrollment already exists; no replacement or renewal",
            ));
        }
        let lease = AuthorityLease {
            schema_version: 1,
            lease_id: id,
            revision: 1,
            authority_epoch: writer.authority_lease.authority_epoch,
            binding,
            issued_at_unix_ms: now,
            expires_at_unix_ms: now
                .checked_add(lifetime_ms)
                .ok_or_else(|| denied("enrollment clock overflow"))?
                .min(parent_expiry),
        };
        require_before(end)?;
        let observed = registry.put_lease(lease.clone(), /*expected_revision*/ 0)
            .map_err(|error| io::Error::other(format!(
                "enrollment CAS outcome unavailable; observe original registry; do not retry: {error}"
            )))?;
        if observed.lease != lease {
            return Err(denied(
                "enrollment outcome uncertain: CAS postimage differs",
            ));
        }
        // This original generic third-record fence now checks the enrollment
        // lease. It creates no material effect and returns no use capability.
        self.with_live_issuer_writer_effect(writer, &lease, &verifier, |parent| {
            check(parent)?;
            require_before(end)
        })
        .map_err(|error| {
            io::Error::other(format!(
                "enrollment outcome uncertain after CAS; observe original registry: {error}"
            ))
        })
    }
}
