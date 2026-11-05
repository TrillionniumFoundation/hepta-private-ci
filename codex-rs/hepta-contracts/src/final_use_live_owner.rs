//! Per-entry validation of the same retained final-use store owner.
//!
//! The original state guard remains held across native ownership and external
//! frontier checks. Refusal fences the shared owner, not just one token or a
//! caller's cached view. These checks precede the existing clock and effect
//! callbacks; they do not revoke an effect that has already entered.

use super::FinalUseError;
use super::Inner;
use super::State;
use super::frontier_for_state_with_profile;
use super::map_trust_error;
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
            if self.store.revalidate_owner().is_err() {
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
