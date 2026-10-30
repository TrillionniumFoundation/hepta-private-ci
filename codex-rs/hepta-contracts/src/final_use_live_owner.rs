//! Per-entry validation of the same retained final-use store owner.
//!
//! The exact original state guard remains held across the native check. Native
//! context locking ends before the existing clock/frontier/effect callbacks.
//! Refusal fences the shared owner, not just one token or caller's cached view.

use super::FinalUseError;
use super::Inner;
use super::State;
use std::sync::MutexGuard;

impl Inner {
    pub(super) fn ensure_live_state<'state>(
        &self,
        state: MutexGuard<'state, State>,
    ) -> Result<MutexGuard<'state, State>, FinalUseError> {
        if state.failed {
            return Err(FinalUseError::Unavailable);
        }
        #[cfg(windows)]
        {
            let mut state = state;
            if self.store.revalidate_owner().is_err() {
                state.failed = true;
                return Err(FinalUseError::Unavailable);
            }
            Ok(state)
        }
        #[cfg(not(windows))]
        {
            Ok(state)
        }
    }
}
