//! Shared signature and role validation for original receipt readers. This
//! holds only borrowed data and verifier input; it never supplies evidence,
//! opens an owner, authorizes a stage or publishes a checkpoint.

use super::*;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

pub(crate) struct OriginalReceiptVerificationV1<'a> {
    verifier: &'a LearningEvidenceVerifierV1,
    snapshot: &'a LearningIterationSnapshotV1,
    receipt: &'a LearningIterationReceiptV1,
    role: LearningEvidenceRoleV1,
    payload: Vec<u8>,
}

impl<'a> OriginalReceiptVerificationV1<'a> {
    pub(crate) fn new(
        verifier: &'a LearningEvidenceVerifierV1,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
    ) -> Result<Self, LearningIterationRuntimeErrorV1> {
        let role = match receipt.observation.stage() {
            LearningIterationStageV1::Training => LearningEvidenceRoleV1::Generator,
            LearningIterationStageV1::Evaluation => LearningEvidenceRoleV1::Evaluator,
            LearningIterationStageV1::Selection => LearningEvidenceRoleV1::Selector,
            LearningIterationStageV1::Experience
            | LearningIterationStageV1::Dataset
            | LearningIterationStageV1::NextUse => LearningEvidenceRoleV1::Observer,
            LearningIterationStageV1::Proposal => {
                return Err(LearningIterationRuntimeErrorV1::Evidence(
                    SignedEvidenceError::RoleMismatch,
                ));
            }
        };
        let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
        Ok(Self {
            verifier,
            snapshot,
            receipt,
            role,
            payload,
        })
    }

    pub(crate) fn verify(
        &self,
        signature: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<VerifiedLearningEvidenceV1, LearningIterationRuntimeErrorV1> {
        let verified = self
            .verifier
            .verify(self.role, signature, &self.payload, now)
            .map_err(LearningIterationRuntimeErrorV1::Evidence)?;
        if verified.principal().principal_id != self.receipt.actor_id
            || &self.receipt.actor_id
                != self.snapshot.owners.owner(self.receipt.observation.stage())
            || verified.trust_digest() != self.snapshot.owners.evidence_trust_digest
            || verified.objective_digest() != self.snapshot.request.envelope.objective_digest
        {
            return Err(LearningIterationRuntimeErrorV1::Evidence(
                SignedEvidenceError::ContextMismatch,
            ));
        }
        Ok(verified)
    }
}

pub(crate) fn independent_receipt_stages(
    snapshot: &LearningIterationSnapshotV1,
    receipt: &LearningIterationReceiptV1,
) -> &'static [LearningIterationStageV1] {
    match receipt.observation.stage() {
        LearningIterationStageV1::Evaluation => &[LearningIterationStageV1::Training],
        LearningIterationStageV1::Selection if snapshot.training_no_update_v2().is_some() => {
            // An unchanged native training result has no evaluator result.
            // The original trainer must still be independent of selection.
            &[LearningIterationStageV1::Training]
        }
        LearningIterationStageV1::Selection => &[
            LearningIterationStageV1::Training,
            LearningIterationStageV1::Evaluation,
        ],
        LearningIterationStageV1::NextUse => &[
            LearningIterationStageV1::Training,
            LearningIterationStageV1::Selection,
        ],
        LearningIterationStageV1::Experience
        | LearningIterationStageV1::Dataset
        | LearningIterationStageV1::Training
        | LearningIterationStageV1::Proposal => &[],
    }
}
