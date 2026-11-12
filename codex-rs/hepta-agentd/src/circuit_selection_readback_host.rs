//! Ordinary Selector host composition with a purpose-fixed original Trainer
//! readback. The original Selector still owns its own journal, witness and key.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_neuron::AnchorWitnessStore;

use super::OriginalCircuitSelectionReceiptOwnerV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCellQ24TrainingReadbackConnectionV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitSelectionCommandErrorV1 as Error;
use crate::OriginalCircuitSelectionCommandOwnerV1;

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitSelectionReceiptOwnerV1<W> {
    /// Bind actual opaque predecessors to the initial Trainer read-only stream.
    /// This is the command-host path for deep original sources. The legacy
    /// evidence constructor remains available for its original local profile.
    pub fn into_command_owner_from_original_readbacks(
        self,
        live: OriginalCircuitLearningReadClientV1,
        trainer: OriginalCellQ24TrainingReadbackConnectionV1,
        dataset: OriginalCellQ24MaterialCommandReceiptV1,
        training: OriginalCellQ24TrainingCommandReceiptV1,
    ) -> Result<OriginalCircuitSelectionCommandOwnerV1<W>, Error> {
        let mut actual = LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())?;
        actual.record(training.receipt().clone(), training.receipt().observed_unix_seconds)?;
        if actual.snapshot() != &self.config.decision
            || training.attestation() != &self.config.training_evidence
        {
            return Err(Error::Binding("same original Selector D/T and complete signature"));
        }
        let trainer = OriginalCellQ24TrainingReadbackConnectionV1::bind_original_training(
            trainer, dataset, training,
        )
        .map_err(|_| Error::Binding("original Trainer read-only command capability"))?;
        OriginalCircuitSelectionCommandOwnerV1::from_original_receipt_owner(self, live, trainer)
    }
}
