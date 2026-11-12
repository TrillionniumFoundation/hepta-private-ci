//! Selector admission from the actual Root B Model stream. The original
//! Selector journal and key stay local; no Root response is a signature.

use super::*;
use crate::OriginalRootIndependentBEvaluationReadbackV1;
use crate::cell_q24_training_receipt_owner::OriginalQ24TrainingOperationEvidenceV1;

impl<W: AnchorWitnessStore> OriginalCellQ24LocalDecisionOwnerV1<W> {
    pub(crate) async fn attest_original_root_decision(
        &mut self,
        factory: &mut AgentdRootQ24ModelFactoryV1,
        training: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        evaluation: &OriginalRootIndependentBEvaluationReadbackV1,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let proposal = self
            .original_root_proposal(factory, training, evaluation, snapshot)
            .await?;
        let saved = self.saved(&proposal);
        let bytes = self.sign_original_proposal(&proposal, &saved);
        // Even a failed or uncertain journal operation must recheck the actual
        // Root source. No new signature or retry follows a missing ACK.
        if self
            .original_root_proposal(factory, training, evaluation, snapshot)
            .await?
            != proposal
        {
            return Err(Error::CommitUncertain);
        }
        self.authenticate(snapshot, &proposal, &saved, &bytes?)
    }

    pub(crate) async fn read_original_root_decision(
        &mut self,
        factory: &mut AgentdRootQ24ModelFactoryV1,
        training: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        evaluation: &OriginalRootIndependentBEvaluationReadbackV1,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let proposal = self
            .original_root_proposal(factory, training, evaluation, snapshot)
            .await?;
        let saved = self.saved(&proposal);
        let bytes = self.journal.read(&saved);
        if self
            .original_root_proposal(factory, training, evaluation, snapshot)
            .await?
            != proposal
        {
            return Err(Error::CommitUncertain);
        }
        self.authenticate(snapshot, &proposal, &saved, &bytes?)
    }

    async fn original_root_proposal(
        &self,
        factory: &mut AgentdRootQ24ModelFactoryV1,
        training: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        evaluation: &OriginalRootIndependentBEvaluationReadbackV1,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<LearningIterationSnapshotV1, Error> {
        let prefix = self.proposal_prefix(factory, snapshot)?;
        let original = factory
            .read_from_original_b(training, evaluation)
            .await
            .map_err(|error| {
                if crate::cell_q24_learning_owner_error::is_commit_uncertain(&error) {
                    Error::CommitUncertain
                } else {
                    Error::Binding("original Root Model proposal unavailable")
                }
            })?;
        self.require_original_proposal(prefix, &original)
    }
}
