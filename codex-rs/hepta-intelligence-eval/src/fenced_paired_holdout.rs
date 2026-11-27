//! Paired transitions and original-owner observations on the same fenced CAS.
//! These operations retain the current owner's read-error and poison boundaries.

use super::FencedFinalHoldoutOwnerV1;
use super::FencedHoldoutError;
use super::FinalHoldoutCasRecordV1;
use super::FinalHoldoutCasStoreError;
use super::FinalHoldoutCasStoreV1;
use super::MAX_RECORDS;
use crate::FrozenPairedPlanV1;
use crate::HoldoutPlanEnvelopeV2;
use crate::HoldoutUseEnvelopeV2;
use crate::PairedHoldoutJournalReceiptV1;
use crate::holdout_envelope::HoldoutJournalV2;
use codex_hepta_types::Digest32;

impl<S: FinalHoldoutCasStoreV1> FencedFinalHoldoutOwnerV1<S> {
    /// Commit this engineering profile to the existing CAS before releasing its
    /// receipt. Any earlier uncertain observation also blocks paired writes.
    pub fn consume_paired(
        &mut self,
        plan: &FrozenPairedPlanV1,
    ) -> Result<PairedHoldoutJournalReceiptV1, FencedHoldoutError> {
        if self.poisoned {
            return Err(FencedHoldoutError::Poisoned);
        }
        if self.read_error.is_some() {
            self.poisoned = true;
            return Err(FencedHoldoutError::Indeterminate);
        }
        let mut candidate = self.journal.clone();
        let receipt = candidate
            .consume_paired(candidate.head_digest(), plan)
            .map_err(FencedHoldoutError::Journal)?;
        let next =
            FinalHoldoutCasRecordV1::new(self.binding, self.fence.clone(), candidate.snapshot())?;
        match self
            .store
            .compare_and_swap(self.binding, Some(self.state_digest), &next)
        {
            Ok(()) => {
                self.journal = candidate;
                self.state_digest = next.state_digest;
                Ok(receipt)
            }
            Err(FinalHoldoutCasStoreError::Conflict) => {
                self.poisoned = true;
                Err(FencedHoldoutError::Conflict)
            }
            Err(FinalHoldoutCasStoreError::Rejected) => Err(FencedHoldoutError::Rejected),
            Err(FinalHoldoutCasStoreError::Indeterminate) => {
                self.poisoned = true;
                Err(FencedHoldoutError::Indeterminate)
            }
        }
    }

    /// Read the current original store without consumption or CAS. A public
    /// sealed receipt is accepted only when its complete plan and record still
    /// match this exact owner, fence, journal and head.
    pub(crate) fn require_paired_consumption(
        &mut self,
        plan: &FrozenPairedPlanV1,
        receipt: &PairedHoldoutJournalReceiptV1,
    ) -> Result<Digest32, FencedHoldoutError> {
        if self.poisoned {
            return Err(FencedHoldoutError::Poisoned);
        }
        if let Some(error) = self.read_error {
            return Err(FencedHoldoutError::Store(error));
        }
        receipt
            .validate(plan)
            .map_err(|_| FencedHoldoutError::Binding)?;
        let current = match self.store.load(self.binding) {
            Ok(current) => current.ok_or(FencedHoldoutError::Missing)?,
            Err(FinalHoldoutCasStoreError::Indeterminate) => {
                self.read_error = Some(FinalHoldoutCasStoreError::Indeterminate);
                return Err(FencedHoldoutError::Store(
                    FinalHoldoutCasStoreError::Indeterminate,
                ));
            }
            Err(error) => return Err(FencedHoldoutError::Store(error)),
        };
        current.validate(self.binding)?;
        if current.fence != self.fence {
            self.poisoned = true;
            return Err(FencedHoldoutError::StaleFence);
        }
        if current.state_digest != self.state_digest {
            self.poisoned = true;
            return Err(FencedHoldoutError::Conflict);
        }
        let journal =
            HoldoutJournalV2::from_snapshot_with_record_limit(current.journal, MAX_RECORDS)
                .map_err(|_| FencedHoldoutError::Corrupt)?;
        if journal.snapshot() != self.journal.snapshot() {
            return Err(FencedHoldoutError::Corrupt);
        }
        let record = journal
            .records()
            .iter()
            .find(|record| match &record.plan {
                HoldoutPlanEnvelopeV2::CrossFold(stored) => stored.plan_id == plan.spec().plan_id,
                HoldoutPlanEnvelopeV2::Paired(stored) => {
                    stored.spec().plan_id == plan.spec().plan_id
                }
            })
            .ok_or(FencedHoldoutError::Binding)?;
        let HoldoutPlanEnvelopeV2::Paired(stored_plan) = &record.plan else {
            return Err(FencedHoldoutError::Binding);
        };
        if stored_plan.as_ref() != plan
            || !matches!(&record.use_receipt, HoldoutUseEnvelopeV2::Paired(_))
            || record.sequence != receipt.sequence
            || record.record_digest != receipt.record_digest
            || journal.head_digest() != receipt.head_digest
        {
            return Err(FencedHoldoutError::Binding);
        }
        Ok(self.binding)
    }
}
