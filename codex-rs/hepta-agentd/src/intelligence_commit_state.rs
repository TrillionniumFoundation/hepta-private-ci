//! Stable projection of durable Decision/Outcome commit uncertainty.
//!
//! `UnknownCommittedState` is intentionally non-terminal.  It means the exact
//! durable operation must remain open for destination-first reconciliation; it
//! is never permission to create a new idempotency identity or redispatch an
//! external effect.

use crate::AgentdIntelligenceLearningDispositionV1;
use crate::AgentdIntelligenceLearningReceiptV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AgentdIntelligenceCommitStateV1 {
    Applied,
    NotApplied,
    Quarantined,
    UnknownCommittedState,
}

impl AgentdIntelligenceCommitStateV1 {
    #[must_use]
    pub const fn is_terminal(self) -> bool {
        !matches!(self, Self::UnknownCommittedState)
    }
}

#[must_use]
pub const fn intelligence_commit_state_v1(
    disposition: AgentdIntelligenceLearningDispositionV1,
) -> AgentdIntelligenceCommitStateV1 {
    match disposition {
        AgentdIntelligenceLearningDispositionV1::Acknowledged => {
            AgentdIntelligenceCommitStateV1::Applied
        }
        AgentdIntelligenceLearningDispositionV1::Rejected => {
            AgentdIntelligenceCommitStateV1::NotApplied
        }
        AgentdIntelligenceLearningDispositionV1::Revoked => {
            AgentdIntelligenceCommitStateV1::Quarantined
        }
        AgentdIntelligenceLearningDispositionV1::Indeterminate => {
            AgentdIntelligenceCommitStateV1::UnknownCommittedState
        }
    }
}

impl AgentdIntelligenceLearningReceiptV1 {
    #[must_use]
    pub const fn commit_state(&self) -> AgentdIntelligenceCommitStateV1 {
        intelligence_commit_state_v1(self.disposition)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn indeterminate_is_an_explicit_non_terminal_commit_state() {
        assert_eq!(
            intelligence_commit_state_v1(
                AgentdIntelligenceLearningDispositionV1::Indeterminate
            ),
            AgentdIntelligenceCommitStateV1::UnknownCommittedState
        );
        assert!(
            !AgentdIntelligenceCommitStateV1::UnknownCommittedState.is_terminal()
        );
    }

    #[test]
    fn known_destination_observations_are_terminal() {
        for disposition in [
            AgentdIntelligenceLearningDispositionV1::Acknowledged,
            AgentdIntelligenceLearningDispositionV1::Rejected,
            AgentdIntelligenceLearningDispositionV1::Revoked,
        ] {
            assert!(intelligence_commit_state_v1(disposition).is_terminal());
        }
    }
}
