//! The separate evaluated C command retains the actual opaque five-cut S and
//! all original T/B/S pins. It cannot execute C or create a missing predecessor.

use super::*;

impl OriginalCircuitNextUseCommandContextV1 {
    pub fn from_original_evaluated_selection(
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<Self, Error> {
        Self::from_evaluated_selection(selection)
    }

    pub(super) fn from_evaluated_selection(selection: &OriginalCircuitEvaluatedSelectionReceiptV1) -> Result<Self, Error> {
        let (scope, verifier, training_evidence) = selection.original_context().receipt_configuration();
        let context = Self {
            selection: selection.snapshot().clone(), scope, verifier, training_evidence,
            selection_evidence: selection.attestation().clone(), evaluated: Some(selection.clone()),
        };
        context.authenticate(now()?)?;
        Ok(context)
    }

    pub(super) fn authenticate_evaluated(
        &self, original: &OriginalCircuitEvaluatedSelectionReceiptV1, current: u64,
    ) -> Result<[VerifiedLearningEvidenceV1; 2], Error> {
        let (scope, verifier, training) = original.original_context().receipt_configuration();
        if original.snapshot() != &self.selection || scope != self.scope
            || verifier.trust_digest() != self.verifier.trust_digest()
            || verifier.scope_digest() != self.verifier.scope_digest()
            || verifier.objective_digest() != self.verifier.objective_digest()
            || training != self.training_evidence || original.attestation() != &self.selection_evidence {
            return Err(Error::Binding("same complete original evaluated C predecessors"));
        }
        let [training, _evaluation, selection] = original.original_receipt_predecessors(current)
            .map_err(OriginalCircuitNextUseReceiptErrorV1::from)?;
        Ok([training, selection])
    }

    pub(super) fn operation(&self) -> &'static str {
        match &self.evaluated {
            None => wire::OPERATION,
            Some(_) => "runtime.learning.original-circuit-evaluated-next-use.command.v1",
        }
    }
}

impl PartialEq for OriginalCircuitNextUseCommandReceiptV1 {
    fn eq(&self, other: &Self) -> bool {
        self.snapshot == other.snapshot && self.receipt == other.receipt && self.attestation == other.attestation
            && self.training_evidence == other.training_evidence && self.selection_evidence == other.selection_evidence
            && self.evaluated.as_ref().map(OriginalCircuitEvaluatedSelectionReceiptV1::original_receipt_binding)
                == other.evaluated.as_ref().map(OriginalCircuitEvaluatedSelectionReceiptV1::original_receipt_binding)
    }
}
impl Eq for OriginalCircuitNextUseCommandReceiptV1 {}
impl std::fmt::Debug for OriginalCircuitNextUseCommandReceiptV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.debug_struct("OriginalCircuitNextUseCommandReceiptV1")
            .field("snapshot", &self.snapshot).field("receipt", &self.receipt)
            .field("attestation", &self.attestation).field("training_evidence", &self.training_evidence)
            .field("selection_evidence", &self.selection_evidence)
            .field("evaluated_binding", &self.evaluated.as_ref().map(OriginalCircuitEvaluatedSelectionReceiptV1::original_receipt_binding)).finish()
    }
}

impl OriginalCircuitNextUseCommandReceiptV1 {
    pub(crate) fn evaluated_selection(&self) -> Option<&OriginalCircuitEvaluatedSelectionReceiptV1> {
        self.evaluated.as_ref()
    }
}

impl OriginalCircuitNextUseCommandClientV1 {
    pub fn recover_from_original_evaluated_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        original: OriginalCircuitEvaluatedSelectionReceiptV1,
        expected: Option<(LearningIterationSnapshotV1, SignedLearningEvidenceV1)>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let context = OriginalCircuitNextUseCommandContextV1::from_evaluated_selection(
            &original.into_original_receipt_readback())?;
        let retained = expected.map(|(snapshot, signed)|
            wire::authenticate_completed(&context, snapshot, signed, now()?)).transpose()?;
        Self::bind_original_stream(stream, peer, original_owner_pidfd, context, timeout, lifetime,
            /*execution_requested*/ true, retained)
    }
}
