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

#[cfg(test)]
#[path = "learning_owner_journal_historical_delivery_tests.rs"]
mod tests;
