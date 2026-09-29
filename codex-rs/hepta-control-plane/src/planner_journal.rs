//! Closed-world typed facade for the deterministic planner journal.
//!
//! The codec, hash chain, identity rules, and lifecycle transition validation
//! live in `planner_journal_core.rs`. The facade only adds typed convenience
//! operations; it does not maintain a second state machine.

#[path = "planner_journal_core.rs"]
mod core;

pub use core::PlannerJournalEntryV1;
pub use core::PlannerJournalError;
pub use core::PlannerJournalKindV1;

use codex_hepta_types::Digest32;

use crate::FeasiblePlanReceiptV1;
use crate::GlobalStateSnapshotV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerJournalV1 {
    inner: core::PlannerJournalV1,
}

impl Default for PlannerJournalV1 {
    fn default() -> Self {
        Self::new()
    }
}

impl PlannerJournalV1 {
    #[must_use]
    pub fn new() -> Self {
        Self {
            inner: core::PlannerJournalV1::new(),
        }
    }

    #[must_use]
    pub fn entries(&self) -> &[PlannerJournalEntryV1] {
        self.inner.entries()
    }

    pub fn record_snapshot(
        &mut self,
        snapshot: &GlobalStateSnapshotV1,
    ) -> Result<PlannerJournalEntryV1, PlannerJournalError> {
        self.append(
            PlannerJournalKindV1::Snapshot,
            snapshot.snapshot_digest(),
            snapshot.snapshot_digest(),
        )
    }

    pub fn record_decision(
        &mut self,
        receipt: &FeasiblePlanReceiptV1,
    ) -> Result<PlannerJournalEntryV1, PlannerJournalError> {
        self.append(
            PlannerJournalKindV1::Decision,
            receipt.receipt_digest(),
            receipt.receipt_digest(),
        )
    }

    pub fn select_plan(
        &mut self,
        operation_identity_digest: Digest32,
        receipt: &FeasiblePlanReceiptV1,
    ) -> Result<PlannerJournalEntryV1, PlannerJournalError> {
        self.append(
            PlannerJournalKindV1::SelectedPlan,
            operation_identity_digest,
            receipt.receipt_digest(),
        )
    }

    pub fn revoke(
        &mut self,
        revocation_identity_digest: Digest32,
        target_digest: Digest32,
    ) -> Result<PlannerJournalEntryV1, PlannerJournalError> {
        self.append(
            PlannerJournalKindV1::Revocation,
            revocation_identity_digest,
            target_digest,
        )
    }

    #[must_use]
    pub fn selected_plan_digest(&self) -> Option<Digest32> {
        self.inner.selected_plan_digest()
    }

    pub fn append(
        &mut self,
        kind: PlannerJournalKindV1,
        identity_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<PlannerJournalEntryV1, PlannerJournalError> {
        self.inner.append(kind, identity_digest, payload_digest)
    }

    #[must_use]
    pub fn export_bytes(&self) -> Vec<u8> {
        self.inner.export_bytes()
    }

    pub fn reopen(bytes: &[u8]) -> Result<Self, PlannerJournalError> {
        Ok(Self {
            inner: core::PlannerJournalV1::reopen(bytes)?,
        })
    }
}

#[cfg(test)]
mod hardening_tests {
    use super::*;

    fn digest(label: &str) -> Digest32 {
        Digest32::of_bytes(label.as_bytes())
    }

    #[test]
    fn raw_append_cannot_select_an_unrecorded_decision() {
        let mut journal = PlannerJournalV1::new();
        assert_eq!(
            journal.append(
                PlannerJournalKindV1::SelectedPlan,
                digest("operation"),
                digest("missing-decision"),
            ),
            Err(PlannerJournalError::DecisionNotRecorded)
        );
    }

    #[test]
    fn exact_retry_survives_later_revocation() {
        let mut journal = PlannerJournalV1::new();
        let decision = digest("decision");
        journal
            .append(PlannerJournalKindV1::Decision, decision, decision)
            .unwrap();
        let operation = digest("operation");
        let selected = journal
            .append(PlannerJournalKindV1::SelectedPlan, operation, decision)
            .unwrap();
        journal
            .append(
                PlannerJournalKindV1::Revocation,
                digest("revocation"),
                decision,
            )
            .unwrap();
        assert_eq!(
            journal
                .append(PlannerJournalKindV1::SelectedPlan, operation, decision)
                .unwrap(),
            selected
        );
    }
}
