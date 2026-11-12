//! Complete the original Evaluator host composition with one shared, purpose-
//! fixed Trainer readback. B, retention, execution and qualification owners stay
//! exactly the already-held originals; this creates no outcome or signature.

use std::sync::Arc;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_neuron::FileAnchorWitnessStore;

use super::Error;
use super::OriginalCellEvaluationHostV1;
use super::OriginalPanelTrainingSourceV1;
use super::Panel;
use crate::OriginalCellEvaluationReceiptOwnerV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCellQ24TrainingReadbackConnectionV1;

impl OriginalCellEvaluationReceiptOwnerV1<FileAnchorWitnessStore> {
    /// Consume an actual completed panel and the original initial Trainer
    /// read-only stream. Every member and the final receipt owner thereafter
    /// use the same live Trainer connection, never a cached T attestation.
    pub fn into_host_from_original_training_readback(
        self,
        mut panel: Panel,
        trainer: OriginalCellQ24TrainingReadbackConnectionV1,
        dataset: OriginalCellQ24MaterialCommandReceiptV1,
        training: OriginalCellQ24TrainingCommandReceiptV1,
    ) -> Result<OriginalCellEvaluationHostV1, Error> {
        let mut actual = LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())
            .map_err(|_| Error::Binding("original Dataset before Evaluator readback"))?;
        actual
            .record(
                training.receipt().clone(),
                training.receipt().observed_unix_seconds,
            )
            .map_err(|_| Error::Binding("original Training before Evaluator readback"))?;
        let (receipt, _) = OriginalCellEvaluationReceiptOwnerV1::original_host_profile(&self);
        if panel.fenced || receipt.training != *actual.snapshot() {
            return Err(Error::Binding("same original Evaluator Training cut"));
        }
        for member in std::iter::once(&panel.primary).chain(&panel.retention) {
            let original = &member.qualification.config;
            if original.training != *actual.snapshot()
                || original.training_evidence != *training.attestation()
                || original.scope != receipt.scope
                || original.verifier.trust_digest() != receipt.signing.verifier.trust_digest()
                || original.verifier.scope_digest() != receipt.signing.verifier.scope_digest()
                || original.verifier.objective_digest()
                    != receipt.signing.verifier.objective_digest()
            {
                return Err(Error::Binding(
                    "same original full Training for every panel member",
                ));
            }
        }
        let trainer = Arc::new(
            OriginalCellQ24TrainingReadbackConnectionV1::bind_original_training(
                trainer, dataset, training,
            )
            .map_err(|_| Error::Binding("original Evaluator Trainer read-only capability"))?,
        );
        // Only the read-only transport is replaced during this consuming host
        // composition. No member, journal, witness, seal or retained state changes.
        panel.primary.trainer = Arc::clone(&trainer);
        for member in &mut panel.retention {
            member.trainer = Arc::clone(&trainer);
        }
        let training_source = OriginalPanelTrainingSourceV1::from_original_training_readback(
            trainer,
            &panel.primary.qualification.config,
        );
        let mut host = OriginalCellEvaluationHostV1::from_original_receipt_owner(self, panel)?;
        host.owners
            .get_mut()
            .map_err(|_| Error::Unavailable)?
            .training_source = training_source;
        Ok(host)
    }
}
