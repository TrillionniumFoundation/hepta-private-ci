//! Existing exact Notes lease/grant revocation; no signing or replacement.
use super::*;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::authority_lease::RevocationReceipt;

#[path = "deployment_notes_revoke_observation.rs"]
mod observation;

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
        if input.expected_effect_revision != 1
            || input.expected_issuer_revision == 0
            || input.reason_sha256 == [0; 32]
        {
            return Err(denied("original Notes revoke policy/CAS mismatch"));
        }
        self.writer.with_live(&self.registry.verifier(), |_| {
            if issuer.retained_writer_authorization(&self.writer)? != self.proof {
                return Err(denied("original Notes revoke writer proof changed"));
            }
            Ok(())
        })?;
        let observed = self.observe_original_grant_state(issuer, input.signed, input.before)?;
        // Read-only retained artifacts never authorize mutation: repeat STRICT
        // current-time verification on the same actual issuer before preparing.
        let head = issuer.verify_original_signed_grant(input.signed, input.before)?;
        if head != observed.head
            || head.revision != input.expected_issuer_revision
            || observed
                .revocation
                .as_ref()
                .is_some_and(|record| record.revocation.reason_sha256 != input.reason_sha256)
        {
            return Err(denied("original Notes revoke issuer/CAS mismatch"));
        }
        // Clamp the cumulative deadline conservatively from BEFORE the actual
        // trusted-clock read. This never adds time to the original request or
        // permits either CAS after the signed grant's own time window.
        let sampled = Instant::now();
        let now = issuer.clock.now_unix_ms().map_err(io::Error::other)?;
        let remaining = input
            .signed
            .grant
            .expires_at_unix_ms
            .checked_sub(now)
            .filter(|remaining| *remaining > 0)
            .ok_or_else(|| denied("original signed grant expired"))?;
        let before = input.before.min(
            sampled
                .checked_add(Duration::from_millis(remaining))
                .ok_or_else(|| denied("original grant deadline range"))?,
        );
        actual_root_before(before)?;
        Ok(PreparedNotesGrantRevocation {
            notes: self,
            issuer,
            signed: input.signed,
            head,
            lease_id: observed.lease.lease.lease_id,
            expected_revision: input.expected_effect_revision,
            reason: input.reason_sha256,
            before,
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
            .revoke_before(
                &self.lease_id,
                self.expected_revision,
                self.reason,
                self.before,
            )
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
