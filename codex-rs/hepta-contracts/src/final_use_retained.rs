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
use super::SignedFinalUseGrant;
use super::final_use_binding_witness_sha256;
use super::frontier_for_state;
use crate::VerifiedUseAuthorityRefV1;
use crate::VerifiedUseBoundaryV1;
use crate::VerifiedUseTokenWitnessV1;

impl FinalUseAuthority {
    /// Require the existing independent frontier and compare it with this
    /// exact live owner. Compatibility owners without that frontier fail.
    pub fn current_external_frontier(&self) -> Result<FinalUseFrontier, FinalUseError> {
        if self.0.frontier_store.is_none() {
            return Err(FinalUseError::InvalidTrust);
        }
        let state = self.0.state.lock().map_err(|_| FinalUseError::Unavailable)?;
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
        if self.0.frontier_store.is_none() {
            return Err(FinalUseError::InvalidTrust);
        }
        let input = signed.grant.signing_bytes()?;
        if signed.grant.signer_id != self.0.signer_id || &signed.grant.binding != expected {
            return Err(FinalUseError::BindingMismatch);
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| FinalUseError::InvalidSignature)?;
        if !self.0.issuer_keys.iter().any(|key| {
            signed.grant.authority_epoch >= key.not_before_authority_epoch
                && signed.grant.authority_epoch <= key.not_after_authority_epoch
                && key.key.verify_strict(&input, &signature).is_ok()
        }) {
            return Err(FinalUseError::InvalidSignature);
        }
        witness.validate().map_err(|_| FinalUseError::InvalidGrant)?;
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
        let state = self.0.state.lock().map_err(|_| FinalUseError::Unavailable)?;
        let state = self.0.ensure_current_effect_state(state)?;
        if state.head.authority_epoch != witness.authority_epoch {
            return Err(FinalUseError::EpochMismatch);
        }
        if state.head.revision < reference.revocation_revision {
            return Err(FinalUseError::StaleRevocationHead);
        }
        if state.head.revoked_grant_ids.contains(&signed.grant.grant_id) {
            return Err(FinalUseError::Revoked);
        }
        if !state.used_nonces.contains(&signed.grant.nonce) {
            return Err(FinalUseError::InvalidGrant);
        }
        Ok(state.head.clone())
    }
}

#[cfg(all(test, unix))]
#[path = "final_use_retained_tests.rs"]
mod tests;
