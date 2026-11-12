//! Ordinary C Observer composition. Both original predecessors use their
//! distinct read-only command purposes, preserving initial peers and deadlines.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_neuron::AnchorWitnessStore;

use super::OriginalCircuitNextUseReceiptOwnerV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCellQ24TrainingReadbackConnectionV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitNextUseCommandErrorV1 as Error;
use crate::OriginalCircuitNextUseCommandOwnerV1;
use crate::OriginalCircuitSelectionCommandReceiptV1;
use crate::OriginalCircuitSelectionReadbackConnectionV1;

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitNextUseReceiptOwnerV1<W> {
    /// Retain the actual Selector publication and original T/S signatures.
    /// This only composes existing owners; C execution and grants stay separate.
    pub fn into_command_owner_from_original_readbacks(
        self,
        live: OriginalCircuitLearningReadClientV1,
        trainer: OriginalCellQ24TrainingReadbackConnectionV1,
        selector: OriginalCircuitSelectionReadbackConnectionV1,
        dataset: OriginalCellQ24MaterialCommandReceiptV1,
        training: OriginalCellQ24TrainingCommandReceiptV1,
        selection: OriginalCircuitSelectionCommandReceiptV1,
    ) -> Result<OriginalCircuitNextUseCommandOwnerV1<W>, Error> {
        let mut actual = LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())?;
        actual.record(training.receipt().clone(), training.receipt().observed_unix_seconds)?;
        actual.record(selection.receipt().clone(), selection.receipt().observed_unix_seconds)?;
        if actual.snapshot() != &self.config.selection
            || selection.snapshot() != &self.config.selection
            || training.attestation() != &self.config.training_evidence
            || selection.training_attestation() != &self.config.training_evidence
            || selection.attestation() != &self.config.selection_evidence
        {
            return Err(Error::Binding("same original C D/T/S and complete signatures"));
        }
        let original_trainer = OriginalCellQ24TrainingReadbackConnectionV1::bind_original_training(
            trainer, dataset.clone(), training.clone(),
        )
        .map_err(|_| Error::Binding("original Trainer read-only command capability"))?;
        let original_selector = OriginalCircuitSelectionReadbackConnectionV1::bind_original_selection(
            selector, dataset, &training, selection,
        )
        .map_err(|_| Error::Binding("original Selector read-only command capability"))?;
        OriginalCircuitNextUseCommandOwnerV1::from_original_receipt_owner(
            self, live, original_trainer, original_selector,
        )
    }
}
