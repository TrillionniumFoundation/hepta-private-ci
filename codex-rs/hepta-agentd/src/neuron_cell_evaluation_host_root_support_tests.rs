//! Test-only authentication of already original Evaluation bytes. The
//! mechanism's heldout/Product credentials remain explicitly synthetic.
use super::*;

impl OriginalCellEvaluationCommandReceiptV1 {
    pub(crate) fn fixture_original_model_evaluation(
        dataset: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        verifier: LearningEvidenceVerifierV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        receipt: LearningIterationReceiptV1,
        evidence: SignedLearningEvidenceV1,
    ) -> Result<Self, Error> {
        let context =
            Context::from_original_training(dataset, scope, registration, verifier, training)?;
        authenticate_receipt(&context, receipt, evidence, super::super::now()?)
    }
}
