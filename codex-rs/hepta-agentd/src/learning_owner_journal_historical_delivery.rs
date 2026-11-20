//! The supervised historical delivery owns its journal across the real async
//! dispatch. Dropping that future closes the owner and leaves the durable claim
//! Pending. No blocking worker or replacement delivery is detached at shutdown.

use std::future::Future;

use super::*;

impl<W: AnchorWitnessStore> LearningOwnerJournalV1<W> {
    pub(crate) async fn commit_original_historical_delivery<F>(
        &mut self,
        key: &ProductEvaluationExecutionKeyV1,
        dispatch: impl FnOnce() -> F,
    ) -> Result<Vec<u8>, Error>
    where
        F: Future<Output = Result<Vec<u8>, Error>>,
    {
        self.require_current()?;
        let before = anchor(self.journal.anchor())?;
        match self.journal.claim(key) {
            Ok(ProductEvaluationExecutionClaimV1::Existing(
                ProductEvaluationExecutionStateV1::Completed(bytes),
            )) => {
                self.require_current()?;
                return Ok(bytes);
            }
            Ok(ProductEvaluationExecutionClaimV1::Existing(
                ProductEvaluationExecutionStateV1::Pending,
            )) => return Err(Error::Pending),
            Ok(ProductEvaluationExecutionClaimV1::Claimed) => self.anchor_append(before)?,
            Err(error) => {
                self.fenced = true;
                return Err(error.into());
            }
        }
        let bytes = dispatch().await?;
        self.require_current()?;
        let before = anchor(self.journal.anchor())?;
        if self.journal.complete(key, &bytes).is_err() {
            self.fenced = true;
            return Err(Error::CommitUncertain);
        }
        self.anchor_append(before)?;
        let saved = self.read(key)?;
        if saved != bytes {
            self.fenced = true;
            return Err(Error::CommitUncertain);
        }
        Ok(saved)
    }
}

/// This one-shot claim keeps the same exclusive journal and exact operation.
/// It carries no Root observation and dropping it retains witnessed Pending.
pub(crate) struct OriginalHistoricalDeliveryClaimV1<'owner, W: AnchorWitnessStore> {
    owner: &'owner mut LearningOwnerJournalV1<W>,
    key: ProductEvaluationExecutionKeyV1,
}

pub(crate) enum OriginalHistoricalDeliveryPreparationV1<'owner, W: AnchorWitnessStore> {
    Completed(Vec<u8>),
    Claimed(OriginalHistoricalDeliveryClaimV1<'owner, W>),
}

impl<W: AnchorWitnessStore> LearningOwnerJournalV1<W> {
    pub(crate) fn prepare_original_historical_delivery(
        &mut self,
        key: &ProductEvaluationExecutionKeyV1,
    ) -> Result<OriginalHistoricalDeliveryPreparationV1<'_, W>, Error> {
        self.require_current()?;
        let before = anchor(self.journal.anchor())?;
        match self.journal.claim(key) {
            Ok(ProductEvaluationExecutionClaimV1::Existing(
                ProductEvaluationExecutionStateV1::Completed(bytes),
            )) => {
                self.require_current()?;
                return Ok(OriginalHistoricalDeliveryPreparationV1::Completed(bytes));
            }
            Ok(ProductEvaluationExecutionClaimV1::Existing(
                ProductEvaluationExecutionStateV1::Pending,
            )) => return Err(Error::Pending),
            Ok(ProductEvaluationExecutionClaimV1::Claimed) => self.anchor_append(before)?,
            Err(error) => {
                self.fenced = true;
                return Err(error.into());
            }
        }
        Ok(OriginalHistoricalDeliveryPreparationV1::Claimed(
            OriginalHistoricalDeliveryClaimV1 {
                owner: self,
                key: key.clone(),
            },
        ))
    }
}

impl<W: AnchorWitnessStore> OriginalHistoricalDeliveryClaimV1<'_, W> {
    /// The caller has completed its original dispatch; only this same retained
    /// claim may complete its exact key. No readback path constructs this guard.
    pub(crate) fn complete_original_historical_delivery(
        self,
        bytes: &[u8],
    ) -> Result<Vec<u8>, Error> {
        let owner = self.owner;
        owner.require_current()?;
        let before = anchor(owner.journal.anchor())?;
        if owner.journal.complete(&self.key, bytes).is_err() {
            owner.fenced = true;
            return Err(Error::CommitUncertain);
        }
        owner.anchor_append(before)?;
        let saved = owner.read(&self.key)?;
        if saved != bytes {
            owner.fenced = true;
            return Err(Error::CommitUncertain);
        }
        Ok(saved)
    }
}

#[cfg(test)]
#[path = "learning_owner_journal_historical_delivery_tests.rs"]
mod tests;
