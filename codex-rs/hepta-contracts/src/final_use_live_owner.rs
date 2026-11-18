//! Per-entry validation of the retained final-use journal and trusted frontier.
//!
//! Journal identity/length fencing in this port is Unix-specific. Windows
//! continues to use the existing R3 private-state owner without claiming a
//! new live-journal identity guarantee.
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
        #[cfg(unix)]
        {
            let mut state = state;
            if self.store.revalidate_owner().is_err() {
                state.failed = true;
                return Err(FinalUseError::Unavailable);
            }
            Ok(state)
        }
        #[cfg(not(unix))]
        {
            Ok(state)
        }
    }

    pub(super) fn ensure_current_effect_state<'state>(
        &self,
        state: MutexGuard<'state, State>,
    ) -> Result<MutexGuard<'state, State>, FinalUseError> {
        let mut state = self.ensure_live_state(state)?;
        if let Some(frontier_store) = &self.frontier_store {
            let trusted = match frontier_store.load(&self.signer_id) {
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
        #[cfg(unix)]
        let now_unix_ms = {
            self.owner.store.revalidate_owner()?;
            let now_unix_ms = self.owner.clock.now_unix_ms().map_err(map_trust_error)?;
            validate_live(&self.grant, head, now_unix_ms)?;
            now_unix_ms
        };
        Ok(now_unix_ms)
    }
}
