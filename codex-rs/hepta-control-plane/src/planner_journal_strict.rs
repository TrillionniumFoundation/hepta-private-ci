//! Production-facing semantic replay for the bounded planner journal.
//!
//! `PlannerJournalV1` verifies byte integrity and hash chaining. This wrapper
//! additionally replays state-machine invariants so a hash-valid serialization
//! cannot introduce a selection before its decision or after revocation.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::PlannerJournalEntryV1;
use crate::PlannerJournalError;
use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StrictPlannerJournalError {
    Journal(PlannerJournalError),
    SnapshotIdentityMismatch,
    DecisionIdentityMismatch,
    SelectionBeforeDecision,
    SelectionAfterRevocation,
    RevocationBeforeDecision,
}

impl fmt::Display for StrictPlannerJournalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Journal(error) => write!(formatter, "{error}"),
            Self::SnapshotIdentityMismatch => {
                formatter.write_str("snapshot journal identity does not equal payload")
            }
            Self::DecisionIdentityMismatch => {
                formatter.write_str("decision journal identity does not equal receipt digest")
            }
            Self::SelectionBeforeDecision => {
                formatter.write_str("selected plan has no preceding decision record")
            }
            Self::SelectionAfterRevocation => {
                formatter.write_str("selected plan was already revoked")
            }
            Self::RevocationBeforeDecision => {
                formatter.write_str("revocation targets an unknown decision")
            }
        }
    }
}

impl StdError for StrictPlannerJournalError {}

impl From<PlannerJournalError> for StrictPlannerJournalError {
    fn from(error: PlannerJournalError) -> Self {
        Self::Journal(error)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StrictPlannerJournalV1 {
    inner: PlannerJournalV1,
}

impl StrictPlannerJournalV1 {
    pub fn reopen(bytes: &[u8]) -> Result<Self, StrictPlannerJournalError> {
        let inner = PlannerJournalV1::reopen(bytes)?;
        replay_semantics(inner.entries())?;
        Ok(Self { inner })
    }

    #[must_use]
    pub fn entries(&self) -> &[PlannerJournalEntryV1] {
        self.inner.entries()
    }

    #[must_use]
    pub fn selected_plan_digest(&self) -> Option<Digest32> {
        self.inner.selected_plan_digest()
    }

    #[must_use]
    pub fn export_bytes(&self) -> Vec<u8> {
        self.inner.export_bytes()
    }

    #[must_use]
    pub fn into_inner(self) -> PlannerJournalV1 {
        self.inner
    }
}

fn replay_semantics(entries: &[PlannerJournalEntryV1]) -> Result<(), StrictPlannerJournalError> {
    let mut decisions = BTreeSet::new();
    let mut revoked = BTreeSet::new();
    for entry in entries {
        match entry.kind {
            PlannerJournalKindV1::Snapshot => {
                if entry.identity_digest != entry.payload_digest {
                    return Err(StrictPlannerJournalError::SnapshotIdentityMismatch);
                }
            }
            PlannerJournalKindV1::Decision => {
                if entry.identity_digest != entry.payload_digest {
                    return Err(StrictPlannerJournalError::DecisionIdentityMismatch);
                }
                decisions.insert(entry.payload_digest);
            }
            PlannerJournalKindV1::SelectedPlan => {
                if !decisions.contains(&entry.payload_digest) {
                    return Err(StrictPlannerJournalError::SelectionBeforeDecision);
                }
                if revoked.contains(&entry.payload_digest) {
                    return Err(StrictPlannerJournalError::SelectionAfterRevocation);
                }
            }
            PlannerJournalKindV1::Revocation => {
                if !decisions.contains(&entry.payload_digest) {
                    return Err(StrictPlannerJournalError::RevocationBeforeDecision);
                }
                revoked.insert(entry.payload_digest);
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;

    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn strict_reopen_accepts_semantically_valid_history() {
        let mut journal = PlannerJournalV1::new();
        let decision = digest("decision");
        journal
            .append(PlannerJournalKindV1::Decision, decision, decision)
            .expect("decision");
        journal
            .append(
                PlannerJournalKindV1::SelectedPlan,
                digest("select-operation"),
                decision,
            )
            .expect("selection");
        let reopened =
            StrictPlannerJournalV1::reopen(&journal.export_bytes()).expect("strict reopen");
        assert_eq!(reopened.selected_plan_digest(), Some(decision));
    }

    #[test]
    fn hash_valid_selection_before_decision_is_rejected() {
        let mut journal = PlannerJournalV1::new();
        journal
            .append(
                PlannerJournalKindV1::SelectedPlan,
                digest("select-operation"),
                digest("decision"),
            )
            .expect("raw journal allows generic append");
        assert_eq!(
            StrictPlannerJournalV1::reopen(&journal.export_bytes()),
            Err(StrictPlannerJournalError::SelectionBeforeDecision)
        );
    }

    #[test]
    fn hash_valid_selection_after_revocation_is_rejected() {
        let mut journal = PlannerJournalV1::new();
        let decision = digest("decision");
        journal
            .append(PlannerJournalKindV1::Decision, decision, decision)
            .expect("decision");
        journal
            .append(
                PlannerJournalKindV1::Revocation,
                digest("revoke-operation"),
                decision,
            )
            .expect("revocation");
        journal
            .append(
                PlannerJournalKindV1::SelectedPlan,
                digest("select-operation"),
                decision,
            )
            .expect("raw journal allows generic append");
        assert_eq!(
            StrictPlannerJournalV1::reopen(&journal.export_bytes()),
            Err(StrictPlannerJournalError::SelectionAfterRevocation)
        );
    }
}
