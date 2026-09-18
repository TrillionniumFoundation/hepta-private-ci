//! Multi-host fencing adapter for durable final-holdout ownership.
//!
//! The filesystem journal remains the byte-level durable record. A production
//! multi-host owner supplies a separate linearizable compare-and-swap store whose
//! state survives independently of journal backups. Reservations are written to
//! that fence before journal mutation; ambiguous transitions therefore fail closed.

use crate::CrossFoldPlanReceiptV1;
use crate::DurableFinalHoldoutJournalV1;
use crate::DurableHoldoutError;
use crate::FinalHoldoutJournalReceiptV1;
use crate::HoldoutAnchorV1;
use crate::HoldoutUseDispositionV1;
use codex_hepta_types::Digest32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HoldoutFenceStateV1 {
    pub epoch: u64,
    pub committed_anchor: HoldoutAnchorV1,
    /// Nonzero while one exact plan owns the holdout reservation. A pending
    /// reservation requires explicit reconciliation and blocks another owner.
    pub pending_plan_digest: Digest32,
}

impl HoldoutFenceStateV1 {
    pub const fn committed(epoch: u64, anchor: HoldoutAnchorV1) -> Self {
        Self {
            epoch,
            committed_anchor: anchor,
            pending_plan_digest: Digest32::ZERO,
        }
    }
}

/// Linearizable state supplied by the production host. Implementations must
/// persist independently of journal backups/snapshots and authenticate callers.
pub trait HoldoutFenceStoreV1 {
    fn load(&mut self) -> Result<HoldoutFenceStateV1, DurableHoldoutError>;

    /// Atomically replace `expected` with `desired`. Returns false when the
    /// current state is not exactly `expected`.
    fn compare_and_swap(
        &mut self,
        expected: HoldoutFenceStateV1,
        desired: HoldoutFenceStateV1,
    ) -> Result<bool, DurableHoldoutError>;
}

pub struct FencedFinalHoldoutOwnerV1<S> {
    journal: DurableFinalHoldoutJournalV1,
    fence: S,
    poisoned: bool,
}

impl<S: HoldoutFenceStoreV1> FencedFinalHoldoutOwnerV1<S> {
    pub fn new(
        journal: DurableFinalHoldoutJournalV1,
        mut fence: S,
    ) -> Result<Self, DurableHoldoutError> {
        let state = fence.load()?;
        if !state.pending_plan_digest.is_zero() || state.committed_anchor != journal.anchor() {
            return Err(DurableHoldoutError::Indeterminate);
        }
        Ok(Self {
            journal,
            fence,
            poisoned: false,
        })
    }

    pub fn anchor(&self) -> HoldoutAnchorV1 {
        self.journal.anchor()
    }

    pub fn consume(
        &mut self,
        plan: &CrossFoldPlanReceiptV1,
    ) -> Result<FinalHoldoutJournalReceiptV1, DurableHoldoutError> {
        if self.poisoned {
            return Err(DurableHoldoutError::Poisoned);
        }
        if plan.plan_digest.is_zero() {
            return Err(DurableHoldoutError::Semantic);
        }

        let current = self.fence.load()?;
        if !current.pending_plan_digest.is_zero() || current.committed_anchor != self.journal.anchor()
        {
            return Err(DurableHoldoutError::Conflict);
        }

        let preview = self.journal.preview_consume(current.committed_anchor, plan)?;
        if preview.disposition == HoldoutUseDispositionV1::IdempotentReplay {
            return Ok(preview);
        }

        let reserved_epoch = current
            .epoch
            .checked_add(1)
            .ok_or(DurableHoldoutError::Capacity)?;
        let reserved = HoldoutFenceStateV1 {
            epoch: reserved_epoch,
            committed_anchor: current.committed_anchor,
            pending_plan_digest: plan.plan_digest,
        };
        if !self.fence.compare_and_swap(current, reserved)? {
            return Err(DurableHoldoutError::Conflict);
        }

        let receipt = match self.journal.consume(current.committed_anchor, plan) {
            Ok(receipt) => receipt,
            Err(_) => {
                // The fence remains pending. The caller must reconcile the exact
                // journal bytes before any further holdout use is possible.
                self.poisoned = true;
                return Err(DurableHoldoutError::Indeterminate);
            }
        };
        let committed_epoch = reserved_epoch
            .checked_add(1)
            .ok_or(DurableHoldoutError::Capacity)?;
        let committed = HoldoutFenceStateV1::committed(committed_epoch, self.journal.anchor());
        match self.fence.compare_and_swap(reserved, committed) {
            Ok(true) => Ok(receipt),
            Ok(false) | Err(_) => {
                self.poisoned = true;
                Err(DurableHoldoutError::Indeterminate)
            }
        }
    }

    pub fn into_parts(self) -> (DurableFinalHoldoutJournalV1, S) {
        (self.journal, self.fence)
    }
}

#[cfg(test)]
#[path = "fenced_holdout_tests.rs"]
mod tests;
