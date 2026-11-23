//! Per-entry validation of the retained final-use journal and trusted frontier.
//!
//! Unix retains journal identity/length fencing. Explicit held Windows owners
//! revalidate their original marker and namespace; ordinary-path Windows owners
//! retain their existing I/O checks without claiming the held-owner guarantee.
//!
//! The original state guard remains held across native ownership and external
//! frontier checks. Refusal fences the shared owner, not just one token or a
//! caller's cached view. These checks precede the existing clock and effect
//! callbacks; they do not revoke an effect that has already entered.

use super::FinalUseError;
use super::FinalUseRevocations;
use super::Inner;
use super::State;
use super::VerifiedUseToken;
use super::frontier_for_state_with_profile;
use super::map_trust_error;
use super::validate_live;
use std::sync::MutexGuard;

impl Inner {
    pub(super) fn ensure_live_state<'state>(
        &self,
        state: MutexGuard<'state, State>,
    ) -> Result<MutexGuard<'state, State>, FinalUseError> {
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        #[cfg(any(unix, windows))]
        {
            let mut state = state;
            if crate::q24_owner_watch!("finaluse.store_revalidate", self.store.revalidate_owner(), |q24_err: &crate::FinalUseError| match q24_err {crate::FinalUseError::InvalidGrant=>"InvalidGrant",crate::FinalUseError::InvalidTrust=>"InvalidTrust",crate::FinalUseError::AntiRollbackViolation=>"AntiRollbackViolation",crate::FinalUseError::InvalidSignature=>"InvalidSignature",crate::FinalUseError::BindingMismatch=>"BindingMismatch",crate::FinalUseError::EpochMismatch=>"EpochMismatch",crate::FinalUseError::StaleRevocationHead=>"StaleRevocationHead",crate::FinalUseError::Revoked=>"Revoked",crate::FinalUseError::NotYetValid=>"NotYetValid",crate::FinalUseError::Expired=>"Expired",crate::FinalUseError::AlreadyClaimed=>"AlreadyClaimed",crate::FinalUseError::CapacityExceeded=>"CapacityExceeded",crate::FinalUseError::DispatchInProgress=>"DispatchInProgress",crate::FinalUseError::Unavailable=>"Unavailable",crate::FinalUseError::UnsafeStateDirectory=>"UnsafeStateDirectory",crate::FinalUseError::StateLocked=>"StateLocked", _=>"other_category"}).is_err() {
                state.failed = true;
                return Err(FinalUseError::Unavailable);
            }
            Ok(state)
        }
        #[cfg(not(any(unix, windows)))]
        {
            Ok(state)
        }
    }

    pub(super) fn ensure_current_effect_state<'state>(
        &self,
        state: MutexGuard<'state, State>,
    ) -> Result<MutexGuard<'state, State>, FinalUseError> {
        let mut state = crate::q24_owner_watch!("finaluse.live_state", self.ensure_live_state(state), |q24_err: &crate::FinalUseError| match q24_err {crate::FinalUseError::InvalidGrant=>"InvalidGrant",crate::FinalUseError::InvalidTrust=>"InvalidTrust",crate::FinalUseError::AntiRollbackViolation=>"AntiRollbackViolation",crate::FinalUseError::InvalidSignature=>"InvalidSignature",crate::FinalUseError::BindingMismatch=>"BindingMismatch",crate::FinalUseError::EpochMismatch=>"EpochMismatch",crate::FinalUseError::StaleRevocationHead=>"StaleRevocationHead",crate::FinalUseError::Revoked=>"Revoked",crate::FinalUseError::NotYetValid=>"NotYetValid",crate::FinalUseError::Expired=>"Expired",crate::FinalUseError::AlreadyClaimed=>"AlreadyClaimed",crate::FinalUseError::CapacityExceeded=>"CapacityExceeded",crate::FinalUseError::DispatchInProgress=>"DispatchInProgress",crate::FinalUseError::Unavailable=>"Unavailable",crate::FinalUseError::UnsafeStateDirectory=>"UnsafeStateDirectory",crate::FinalUseError::StateLocked=>"StateLocked", _=>"other_category"})?;
        if let Some(frontier_store) = &self.frontier_store {
            let trusted = match crate::q24_owner_watch!("finaluse.frontier_load", frontier_store.load(&self.signer_id), |q24_err: &crate::AuthorityTrustError| match q24_err {crate::AuthorityTrustError::Invalid=>"Invalid",crate::AuthorityTrustError::Conflict=>"Conflict",crate::AuthorityTrustError::Unavailable=>"Unavailable", _=>"other_category"}) {
                Ok(trusted) => trusted,
                Err(error) => {
                    state.failed = true;
                    return Err(map_trust_error(error));
                }
            };
            if trusted != frontier_for_state_with_profile(&state, self.profile) {
                state.failed = true;
                return Err(FinalUseError::AntiRollbackViolation);
            }
        }
        Ok(state)
    }
}

impl VerifiedUseToken {
    // Each entry must keep the exact revocation head authenticated at claim.
    pub(super) fn validate_entry(
        &self,
        head: &FinalUseRevocations,
        now_unix_ms: u64,
    ) -> Result<u64, FinalUseError> {
        validate_live(&self.grant, head, now_unix_ms)?;
        if head != &self.claimed_head {
            return Err(FinalUseError::StaleRevocationHead);
        }
        // Clock/frontier callbacks can block after the earlier live-state
        // check. Refusal poisons the store shared by every owner clone. The
        // journal I/O can also outlast a grant, so return a fresh time sample
        // for both final validation and the consumer's entry witness.
        #[cfg(any(unix, windows))]
        let now_unix_ms = {
            self.owner.store.revalidate_owner()?;
            let now_unix_ms = self.owner.clock.now_unix_ms().map_err(map_trust_error)?;
            validate_live(&self.grant, head, now_unix_ms)?;
            now_unix_ms
        };
        Ok(now_unix_ms)
    }
}
