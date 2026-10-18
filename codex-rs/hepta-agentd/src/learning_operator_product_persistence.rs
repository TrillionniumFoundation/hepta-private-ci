//! Non-test product entry to the actual fenced immutable artifact writer.

use super::AgentdIntelligenceProductRunnerV1;
use crate::learning_operator_artifact_owner::LearningOperatorArtifactOwnerV2;
use crate::learning_operator_artifact_owner::LearningOperatorPublicationErrorV1;
use crate::learning_operator_artifact_owner::LearningOperatorPublicationInputsV2;
use crate::learning_operator_artifact_owner::LearningOperatorStorageReceiptV2;
use codex_hepta_agent_components::learning_ledger::LedgerWriter;

impl AgentdIntelligenceProductRunnerV1 {
    /// Bounded synchronous owner operation. The permit and borrowed exclusive
    /// writer survive until fsync/ack finishes; no timed-out detached write can
    /// release capacity early. This stores bytes and does not install a model.
    pub fn persist_learning_operator_candidate(
        &self,
        training_ledger: &LedgerWriter,
        evaluation_ledger: &LedgerWriter,
        artifacts: &mut LearningOperatorArtifactOwnerV2,
        inputs: LearningOperatorPublicationInputsV2<'_>,
    ) -> Result<LearningOperatorStorageReceiptV2, LearningOperatorPublicationErrorV1> {
        let trust =
            self.evaluation_trust
                .as_ref()
                .ok_or(LearningOperatorPublicationErrorV1::Rejected(
                    "host learning trust unavailable",
                ))?;
        if trust.distribution_digest() != training_ledger.trust_distribution_digest()
            || trust.distribution_digest() != evaluation_ledger.trust_distribution_digest()
        {
            return Err(LearningOperatorPublicationErrorV1::Rejected(
                "host learning trust mismatch",
            ));
        }
        let _permit = self
            .worker_slots
            .try_acquire()
            .map_err(|_| LearningOperatorPublicationErrorV1::Rejected("owner workers busy"))?;
        artifacts.persist_or_reconcile(training_ledger, evaluation_ledger, inputs)
    }
}
