//! State and replay rules carried by one local outcome transition.

use super::LocalOutcomeState;

#[derive(Clone, Copy)]
pub(super) enum ExactReplay {
    Allow,
    Reject,
}

pub(super) struct OutcomeTransition<'a> {
    pub(super) allowed: &'a [LocalOutcomeState],
    pub(super) resulting_state: LocalOutcomeState,
    pub(super) replay_policy: ExactReplay,
}
