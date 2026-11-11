//! Original raw evaluator execution custody with an independent witness.
//! This owner holds the original locked file throughout work and readback.
//! It neither signs executions nor establishes the evaluator's role authority.
//! Joint rollback of both original files remains outside this proof.

use std::fs::File;

use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionErrorV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionClaimV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_types::Digest32;

#[path = "neuron_cell_evaluation_execution_readback.rs"]
mod readback;
#[path = "neuron_cell_evaluation_execution_recovery.rs"]
mod recovery;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellEvaluationExecutionStoreErrorV1 {
    #[error("original execution file: {0}")]
    File(#[from] LockedFileProductEvaluationExecutionErrorV1),
    #[error("independent execution witness: {0:?}")]
    Witness(#[from] WitnessStoreError),
    #[error("original execution binding: {0}")]
    Binding(&'static str),
    #[error("original execution outcome is uncertain")]
    CommitUncertain,
}

type Error = OriginalCellEvaluationExecutionStoreErrorV1;
type StoreError = ProductEvaluationExecutionStoreErrorV1;
type State = ProductEvaluationExecutionStateV1;

/// The original evaluator host transfers the unique raw file and its already
/// admitted independent witness before runner work. No writable parts, signing
/// key, namespace replacement or generic mutation callback can be extracted.
pub struct OriginalCellEvaluationExecutionStoreV1<W: AnchorWitnessStore> {
    journal: LockedFileProductEvaluationExecutionStoreV1,
    witness: W,
    fenced: bool,
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum Effect {
    OneFrame,
    AtMostOneFrame,
}

impl<W: AnchorWitnessStore> OriginalCellEvaluationExecutionStoreV1<W> {
    /// Initialize only a genuinely empty raw file and empty witness. If raw
    /// initialization or its witness acknowledgement fails, retain both
    /// originals for host reconciliation. Recovery never completes a partial
    /// initialization or advances a missing/stale witness.
    pub fn create(file: File, mut witness: W, binding: Digest32) -> Result<Self, Error> {
        if witness.current()?.is_some() {
            return Err(Error::Binding("execution witness already initialized"));
        }
        let mut journal = LockedFileProductEvaluationExecutionStoreV1::create(file, binding)?;
        let initial = witnessed(journal.read_current_anchor()?)?;
        if initial.sequence != 1 {
            return Err(Error::Binding("new execution file is not empty"));
        }
        witness.compare_and_swap(None, initial)?;
        let mut owner = Self { journal, witness, fenced: false };
        if owner.require_current()? != initial {
            return Err(Error::CommitUncertain);
        }
        Ok(owner)
    }

    /// Borrow one exact execution through a port that cannot claim or complete.
    /// Each read still checks the original physical file and independent
    /// witness on both sides. Missing/Pending are never substituted with work.
    pub fn readback_only<'a>(
        &'a mut self,
        key: &'a ProductEvaluationExecutionKeyV1,
    ) -> impl ProductEvaluationExecutionStoreV1 + 'a {
        readback::Readback { original: self, key }
    }

    fn require_current(&mut self) -> Result<JournalAnchor, Error> {
        if self.fenced {
            return Err(Error::CommitUncertain);
        }
        let result = (|| {
            let before = self.witness.current()?;
            let physical = self.journal.read_current_anchor()?;
            let current = witnessed(physical)?;
            let after = self.witness.current()?;
            if before != Some(current) || after != Some(current) {
                return Err(Error::CommitUncertain);
            }
            Ok(current)
        })();
        if result.is_err() {
            self.fenced = true;
        }
        result
    }

    fn unchanged(&mut self, before: JournalAnchor) -> Result<(), StoreError> {
        let after = self.require_current().map_err(|_| StoreError::Indeterminate)?;
        if before != after {
            self.fenced = true;
            return Err(StoreError::Indeterminate);
        }
        Ok(())
    }

    fn failed_operation(&mut self, before: JournalAnchor, error: StoreError) -> StoreError {
        if self.unchanged(before).is_err() {
            return StoreError::Indeterminate;
        }
        match error {
            StoreError::Missing | StoreError::Conflict | StoreError::Rejected => error,
            StoreError::Unavailable | StoreError::Indeterminate | StoreError::Corrupt => {
                self.fenced = true;
                StoreError::Indeterminate
            }
        }
    }

    fn witness_effect(&mut self, before: JournalAnchor, effect: Effect) -> Result<(), StoreError> {
        let result = (|| -> Result<(), Error> {
            let next = witnessed(self.journal.read_current_anchor()?)?;
            if next == before {
                if effect == Effect::OneFrame {
                    return Err(Error::CommitUncertain);
                }
            } else {
                if next.sequence != before.sequence.checked_add(1).ok_or(Error::CommitUncertain)? {
                    return Err(Error::CommitUncertain);
                }
                self.witness.compare_and_swap(Some(before), next)?;
            }
            if self.require_current()? != next {
                return Err(Error::CommitUncertain);
            }
            Ok(())
        })();
        if result.is_err() {
            self.fenced = true;
            return Err(StoreError::Indeterminate);
        }
        Ok(())
    }
}

impl<W: AnchorWitnessStore> ProductEvaluationExecutionStoreV1
    for OriginalCellEvaluationExecutionStoreV1<W>
{
    fn claim(&mut self, key: &ProductEvaluationExecutionKeyV1)
        -> Result<ProductEvaluationExecutionClaimV1, StoreError>
    {
        let before = self.require_current().map_err(|_| StoreError::Indeterminate)?;
        let result = ProductEvaluationExecutionStoreV1::claim(&mut self.journal, key);
        match result {
            Ok(ProductEvaluationExecutionClaimV1::Claimed) => {
                self.witness_effect(before, Effect::OneFrame)?;
                Ok(ProductEvaluationExecutionClaimV1::Claimed)
            }
            Ok(ProductEvaluationExecutionClaimV1::Existing(state)) => {
                self.unchanged(before)?;
                Ok(ProductEvaluationExecutionClaimV1::Existing(state))
            }
            Err(error) => Err(self.failed_operation(before, error)),
        }
    }

    fn complete(&mut self, key: &ProductEvaluationExecutionKeyV1, payload: &[u8])
        -> Result<(), StoreError>
    {
        let before = self.require_current().map_err(|_| StoreError::Indeterminate)?;
        match ProductEvaluationExecutionStoreV1::complete(&mut self.journal, key, payload) {
            Ok(()) => self.witness_effect(before, Effect::AtMostOneFrame),
            Err(error) => Err(self.failed_operation(before, error)),
        }
    }

    fn readback(&mut self, key: &ProductEvaluationExecutionKeyV1) -> Result<State, StoreError> {
        let before = self.require_current().map_err(|_| StoreError::Indeterminate)?;
        let state = ProductEvaluationExecutionStoreV1::readback(&mut self.journal, key);
        self.unchanged(before)?;
        match state {
            Err(error) => Err(self.failed_operation(before, error)),
            Ok(state) => Ok(state),
        }
    }
}

fn witnessed(physical: ProductEvaluationExecutionAnchorV1) -> Result<JournalAnchor, Error> {
    if physical.history_digest.is_zero() {
        return Err(Error::Binding("original execution history digest"));
    }
    Ok(JournalAnchor {
        sequence: physical.sequence.checked_add(1)
            .ok_or(Error::Binding("original execution witness sequence"))?,
        checkpoint_digest: physical.history_digest,
    })
}

#[cfg(all(test, target_os = "linux"))]
#[path = "neuron_cell_evaluation_execution_store_tests.rs"]
mod tests;
