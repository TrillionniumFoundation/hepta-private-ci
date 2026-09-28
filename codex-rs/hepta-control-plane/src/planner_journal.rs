//! Closed-world state-machine wrapper for the deterministic planner journal.
//!
//! The byte codec and hash-chain implementation remain in
//! `planner_journal_core.rs`. Every public mutation and every reopen crosses the
//! same transition validator so a structurally valid byte stream cannot bypass
//! the typed planner lifecycle.

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
        if let Some(existing) = self
            .entries()
            .iter()
            .find(|entry| entry.identity_digest == identity_digest)
        {
            // Preserve the core's exact-idempotency and conflict behavior. A
            // retry of an already committed transition remains safe even when
            // a later revocation changed the current projection.
            if existing.kind == kind && existing.payload_digest == payload_digest {
                return self.inner.append(kind, identity_digest, payload_digest);
            }
            return Err(PlannerJournalError::IdentityConflict);
        }
        validate_transition(self.entries(), kind, payload_digest)?;
        self.inner.append(kind, identity_digest, payload_digest)
    }

    #[must_use]
    pub fn export_bytes(&self) -> Vec<u8> {
        self.inner.export_bytes()
    }

    pub fn reopen(bytes: &[u8]) -> Result<Self, PlannerJournalError> {
        let decoded = core::PlannerJournalV1::reopen(bytes)?;
        let mut validated = Self::new();
        for entry in decoded.entries() {
            let replayed =
                validated.append(entry.kind, entry.identity_digest, entry.payload_digest)?;
            if replayed != *entry {
                return Err(PlannerJournalError::CorruptEntryDigest);
            }
        }
        Ok(validated)
    }
}

fn validate_transition(
    entries: &[PlannerJournalEntryV1],
    kind: PlannerJournalKindV1,
    payload_digest: Digest32,
) -> Result<(), PlannerJournalError> {
    if kind != PlannerJournalKindV1::SelectedPlan {
        return Ok(());
    }
    let decision_exists = entries.iter().any(|entry| {
        entry.kind == PlannerJournalKindV1::Decision && entry.payload_digest == payload_digest
    });
    if !decision_exists {
        return Err(PlannerJournalError::DecisionNotRecorded);
    }
    let revoked = entries.iter().any(|entry| {
        entry.kind == PlannerJournalKindV1::Revocation && entry.payload_digest == payload_digest
    });
    if revoked {
        return Err(PlannerJournalError::RevokedPlan);
    }
    Ok(())
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
    fn reopen_rejects_a_structurally_valid_illegal_transition() {
        let mut unchecked = core::PlannerJournalV1::new();
        unchecked
            .append(
                PlannerJournalKindV1::SelectedPlan,
                digest("operation"),
                digest("missing-decision"),
            )
            .unwrap();
        assert_eq!(
            PlannerJournalV1::reopen(&unchecked.export_bytes()),
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
