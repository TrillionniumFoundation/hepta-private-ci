//! Read-only validation of an already consumed, retained final-use operation.
//! This returns no token, does not dispatch, and cannot refund a nonce. A
//! caller still needs its authenticated effect-owner record to prove what was
//! applied; a caller-supplied witness alone does not prove effect completion.

use ed25519_dalek::Signature;

use super::FinalUseAuthority;
use super::FinalUseBinding;
use super::FinalUseError;
use super::FinalUseFrontier;
use super::FinalUseRevocations;
use super::PinnedIssuerKey;
use super::SignedFinalUseGrant;
use super::State;
use super::final_use_binding_witness_sha256;
use super::frontier_for_state;
use crate::VerifiedUseAuthorityRefV1;
use crate::VerifiedUseBoundaryV1;
use crate::VerifiedUseTokenWitnessV1;

impl FinalUseAuthority {
    /// Require the existing independent frontier and compare it with this
    /// exact live owner. Compatibility owners without that frontier fail.
    pub fn current_external_frontier(&self) -> Result<FinalUseFrontier, FinalUseError> {
        let _diagnostic = super::diagnostic::RefusalScope::new("current-external-frontier");
        if self.0.frontier_store.is_none() {
            return Err(FinalUseError::InvalidTrust);
        }
        let state = self
            .0
            .state
            .lock()
            .inspect_err(|_| {
                super::diagnostic::record(
                    "retained.state-lock",
                    FinalUseError::Unavailable,
                    None,
                );
            })
            .map_err(|_| FinalUseError::Unavailable)?;
        let state = self.0.ensure_current_effect_state(state)?;
        Ok(frontier_for_state(&state))
    }

    /// Verify the exact original signature, consumed nonce, retained dispatch
    /// witness and current independent frontier. The old grant's time window
    /// is checked at its recorded entry, not reused as a new dispatch lease.
    /// Later epoch change or revocation denies continued use. This method
    /// never claims, renews, refunds or reissues authority.
    pub fn verify_retained_use(
        &self,
        signed: &SignedFinalUseGrant,
        expected: &FinalUseBinding,
        witness: &VerifiedUseTokenWitnessV1,
    ) -> Result<FinalUseRevocations, FinalUseError> {
        let _diagnostic = super::diagnostic::RefusalScope::new("verify-retained-use");
        if self.0.frontier_store.is_none() {
            return Err(FinalUseError::InvalidTrust);
        }
        let retained: RetainedUse<'_> = RetainedUse::authenticate(
            &self.0.signer_id,
            &self.0.issuer_keys,
            signed,
            expected,
            witness,
        )?;
        let state = self
            .0
            .state
            .lock()
            .inspect_err(|_| {
                super::diagnostic::record(
                    "retained.state-lock",
                    FinalUseError::Unavailable,
                    None,
                );
            })
            .map_err(|_| FinalUseError::Unavailable)?;
        let state = self.0.ensure_current_effect_state(state)?;
        retained.verify_state(&state)
    }
}

/// Authentication shared by the original live owner and Root's read-only
/// observer. Construction does not assert a consumed nonce or effect completion.
pub(super) struct RetainedUse<'a> {
    signed: &'a SignedFinalUseGrant,
    witness: &'a VerifiedUseTokenWitnessV1,
    revocation_revision: u64,
}

impl<'a> RetainedUse<'a> {
    pub(super) fn authenticate(
        signer_id: &str,
        issuer_keys: &[PinnedIssuerKey],
        signed: &'a SignedFinalUseGrant,
        expected: &FinalUseBinding,
        witness: &'a VerifiedUseTokenWitnessV1,
    ) -> Result<Self, FinalUseError> {
        let input = signed.grant.signing_bytes()?;
        if signed.grant.signer_id != signer_id || &signed.grant.binding != expected {
            return Err(FinalUseError::BindingMismatch);
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| FinalUseError::InvalidSignature)?;
        if !issuer_keys.iter().any(|key| {
            signed.grant.authority_epoch >= key.not_before_authority_epoch
                && signed.grant.authority_epoch <= key.not_after_authority_epoch
                && key.key.verify_strict(&input, &signature).is_ok()
        }) {
            return Err(FinalUseError::InvalidSignature);
        }
        witness
            .validate()
            .map_err(|_| FinalUseError::InvalidGrant)?;
        let VerifiedUseAuthorityRefV1::FinalUse(reference) = &witness.authority_ref else {
            return Err(FinalUseError::BindingMismatch);
        };
        if witness.boundary != VerifiedUseBoundaryV1::DispatchEntry
            || witness.authority_epoch != signed.grant.authority_epoch
            || reference.signer_id != signed.grant.signer_id
            || reference.grant_id != signed.grant.grant_id
            || reference.binding_sha256 != final_use_binding_witness_sha256(expected)?
            || witness.verified_at_unix_ms < signed.grant.not_before_unix_ms
            || witness.verified_at_unix_ms >= signed.grant.expires_at_unix_ms
        {
            return Err(FinalUseError::BindingMismatch);
        }
        Ok(Self {
            signed,
            witness,
            revocation_revision: reference.revocation_revision,
        })
    }

    pub(super) fn verify_state(&self, state: &State) -> Result<FinalUseRevocations, FinalUseError> {
        if state.head.authority_epoch != self.witness.authority_epoch {
            return Err(FinalUseError::EpochMismatch);
        }
        if state.head.revision < self.revocation_revision {
            return Err(FinalUseError::StaleRevocationHead);
        }
        if state
            .head
            .revoked_grant_ids
            .contains(&self.signed.grant.grant_id)
        {
            return Err(FinalUseError::Revoked);
        }
        if !state.used_nonces.contains(&self.signed.grant.nonce) {
            return Err(FinalUseError::InvalidGrant);
        }
        Ok(state.head.clone())
    }
}

#[cfg(all(test, unix))]
#[path = "final_use_retained_tests.rs"]
mod tests;
