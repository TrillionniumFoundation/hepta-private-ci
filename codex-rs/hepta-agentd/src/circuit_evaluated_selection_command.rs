//! Complete original evaluated NoUpdate pins in the existing Selector command
//! machinery. Legacy constructors keep their original three-cut refusal.

use super::*;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;

impl Clone for OriginalCircuitSelectionCommandContextV1 {
    fn clone(&self) -> Self {
        Self {
            training: self.training.clone(), scope: self.scope.clone(), verifier: self.verifier.clone(),
            training_evidence: self.training_evidence.clone(),
            evaluated: self.evaluated.as_ref().map(OriginalCircuitEvaluatedRetentionContextV1::clone_for_original_receipt),
        }
    }
}

impl OriginalCircuitSelectionCommandContextV1 {
    pub fn from_original_evaluation(
        scope: FrozenLearningScopeV2,
        verifier: LearningEvidenceVerifierV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: &OriginalCellEvaluationCommandReceiptV1,
    ) -> Result<Self, Error> {
        let original = OriginalCircuitEvaluatedRetentionContextV1::from_original_evaluation(
            scope, verifier, training, evaluation).map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        Self::from_evaluated_context(&original)
    }

    pub(super) fn from_evaluated_context(original: &OriginalCircuitEvaluatedRetentionContextV1) -> Result<Self, Error> {
        let (scope, verifier, training_evidence) = original.receipt_configuration();
        let context = Self {
            training: original.snapshot().clone(), scope, verifier, training_evidence,
            evaluated: Some(original.clone_for_original_receipt()),
        };
        context.authenticate(now()?)?;
        Ok(context)
    }

    pub(super) fn authenticate_evaluated(
        &self, original: &OriginalCircuitEvaluatedRetentionContextV1, current: u64,
    ) -> Result<VerifiedLearningEvidenceV1, Error> {
        let (scope, verifier, training) = original.receipt_configuration();
        if original.snapshot() != &self.training || scope != self.scope
            || verifier.trust_digest() != self.verifier.trust_digest()
            || verifier.scope_digest() != self.verifier.scope_digest()
            || verifier.objective_digest() != self.verifier.objective_digest()
            || training != self.training_evidence {
            return Err(Error::Binding("same full original evaluated Selector pins"));
        }
        let [training, _evaluation] = original.original_receipt_predecessors(current)
            .map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        Ok(training)
    }

    pub(super) fn operation(&self) -> &'static str {
        match &self.evaluated {
            None => wire::OPERATION,
            Some(_) => "runtime.learning.original-circuit-evaluated-selection.command.v1",
        }
    }
}

impl Clone for OriginalCircuitSelectionCommandReceiptV1 {
    fn clone(&self) -> Self {
        Self {
            snapshot: self.snapshot.clone(), receipt: self.receipt.clone(), attestation: self.attestation.clone(),
            training_evidence: self.training_evidence.clone(),
            evaluated: self.evaluated.as_ref().map(OriginalCircuitEvaluatedRetentionContextV1::clone_for_original_receipt),
        }
    }
}
impl PartialEq for OriginalCircuitSelectionCommandReceiptV1 {
    fn eq(&self, other: &Self) -> bool {
        self.snapshot == other.snapshot && self.receipt == other.receipt && self.attestation == other.attestation
            && self.training_evidence == other.training_evidence
            && self.evaluated.as_ref().map(OriginalCircuitEvaluatedRetentionContextV1::receipt_context_binding)
                == other.evaluated.as_ref().map(OriginalCircuitEvaluatedRetentionContextV1::receipt_context_binding)
    }
}
impl Eq for OriginalCircuitSelectionCommandReceiptV1 {}
impl std::fmt::Debug for OriginalCircuitSelectionCommandReceiptV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.debug_struct("OriginalCircuitSelectionCommandReceiptV1")
            .field("snapshot", &self.snapshot).field("receipt", &self.receipt)
            .field("attestation", &self.attestation).field("training_evidence", &self.training_evidence)
            .field("evaluated_binding", &self.evaluated.as_ref().map(OriginalCircuitEvaluatedRetentionContextV1::receipt_context_binding)).finish()
    }
}

impl OriginalCircuitSelectionCommandReceiptV1 {
    pub(crate) fn evaluated_context(&self) -> Option<&OriginalCircuitEvaluatedRetentionContextV1> {
        self.evaluated.as_ref()
    }

    pub(crate) fn evaluated_receipt(&self) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        OriginalCircuitEvaluatedSelectionReceiptV1::from_original_command_response(self).map_err(Error::Owner)
    }
}

impl OriginalCircuitSelectionCommandClientV1 {
    /// This fresh/cold-independent method restores reads only. Actual opaque
    /// predecessor pins are attenuated before touching the original channel.
    pub fn recover_from_original_evaluated_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        original: OriginalCircuitEvaluatedRetentionContextV1,
        expected: Option<(LearningIterationSnapshotV1, SignedLearningEvidenceV1)>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let context = OriginalCircuitSelectionCommandContextV1::from_evaluated_context(
            &original.into_original_receipt_readback())?;
        let retained = expected.map(|(snapshot, signed)|
            wire::authenticate_completed(&context, snapshot, signed, now()?)).transpose()?;
        Self::bind_original_stream(stream, peer, original_owner_pidfd, context, timeout, lifetime,
            /*execution_requested*/ true, retained)
    }
}
