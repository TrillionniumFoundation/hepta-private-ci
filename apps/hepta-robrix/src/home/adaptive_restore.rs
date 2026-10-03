//! One-shot layout restore intent, not another destination or timeline owner.
//! The destination is read from current AppState only when the new Dock loads.
use ruma::OwnedUserId;
use crate::app::AppState;

#[derive(Clone, Debug)]
pub(crate) struct AdaptiveDockRestore {
    user: Option<OwnedUserId>,
    epoch: u64,
}

impl AdaptiveDockRestore {
    pub(crate) fn capture() -> Self {
        Self {
            user: crate::sliding_sync::current_user_id(),
            epoch: crate::sliding_sync::runtime::current_epoch(),
        }
    }

    pub(crate) fn is_current(&self, state: &AppState) -> bool {
        state.logged_in
            && self.user == crate::sliding_sync::current_user_id()
            && self.epoch == crate::sliding_sync::runtime::current_epoch()
    }
}

#[cfg(test)]
#[path = "adaptive_restore_tests.rs"]
mod hepta_adaptive_tests;
