//! A completed, independently evaluated Candidate may retain the original
//! model. This is a separate four-receipt profile, never TrainingNoUpdateV2.
//! The opaque original command results are pins, not publication authority.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;

use super::OriginalCircuitRetainedPublicationErrorV1 as Error;
use super::context::PublicationAccess;
use super::now;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;

/// Only original opaque Trainer and Evaluator responses construct this value.
/// Missing or insufficient Evaluation has no response to convert. A complete
/// negative comparison retains its actual trained Candidate and B receipt.
pub struct OriginalCircuitEvaluatedRetentionContextV1 {
    scope: FrozenLearningScopeV2,
    verifier: LearningEvidenceVerifierV1,
    training: OriginalCellQ24TrainingCommandReceiptV1,
    evaluation: OriginalCellEvaluationCommandReceiptV1,
    origin: Origin,
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum Origin {
    Fresh,
    Readback,
}

/// Borrowed authenticated facts for a read purpose; no publication or signing
/// capability is returned, and the original fresh/cold origin remains bound.
pub(crate) struct EvaluatedRetentionReadProofV1<'a> {
    pub(crate) scope: &'a FrozenLearningScopeV2,
    pub(crate) verifier: &'a LearningEvidenceVerifierV1,
    pub(crate) training: &'a SignedLearningEvidenceV1,
    pub(crate) evaluation: &'a SignedLearningEvidenceV1,
    pub(crate) origin: &'static [u8],
}

impl OriginalCircuitEvaluatedRetentionContextV1 {
    pub fn from_original_evaluation(
        scope: FrozenLearningScopeV2,
        verifier: LearningEvidenceVerifierV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: &OriginalCellEvaluationCommandReceiptV1,
    ) -> Result<Self, Error> {
        let context = Self {
            scope,
            verifier,
            training: training.clone(),
            evaluation: evaluation.clone(),
            origin: Origin::Fresh,
        };
        context.authenticate(now()?, PublicationAccess::NewWork)?;
        Ok(context)
    }

    /// A cold context is permanently read-only. Even a still-valid original
    /// receipt cannot turn this constructor into a new preparation capability.
    pub fn recover_original_evaluation(
        scope: FrozenLearningScopeV2,
        verifier: LearningEvidenceVerifierV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: &OriginalCellEvaluationCommandReceiptV1,
    ) -> Result<Self, Error> {
        let context = Self {
            scope,
            verifier,
            training: training.clone(),
            evaluation: evaluation.clone(),
            origin: Origin::Readback,
        };
        context.authenticate(now()?, PublicationAccess::Readback)?;
        Ok(context)
    }

    /// The original four-stage cut is inspection data, without a Model,
    /// Selector, CURRENT, FinalUse or task-execution capability.
    pub fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.evaluation.snapshot()
    }

    pub(crate) fn original_read_proof(
        &self,
        at: u64,
    ) -> Result<EvaluatedRetentionReadProofV1<'_>, Error> {
        self.authenticate(at, PublicationAccess::Readback)?;
        Ok(EvaluatedRetentionReadProofV1 {
            scope: &self.scope,
            verifier: &self.verifier,
            training: self.training.attestation(),
            evaluation: self.evaluation.attestation(),
            origin: match self.origin {
                Origin::Fresh => b"fresh",
                Origin::Readback => b"readback",
            },
        })
    }

    pub(super) fn authenticate(
        &self,
        at: u64,
        access: PublicationAccess,
    ) -> Result<LearningIterationCoordinatorV1, Error> {
        if matches!(access, PublicationAccess::NewWork) && self.origin != Origin::Fresh {
            return Err(Error::Binding("recovered evaluated retention is read-only"));
        }
        let snapshot = self.evaluation.snapshot();
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        self.scope.validate_snapshot(snapshot)?;
        if snapshot.receipts.len() != 4
            || coordinator.next_stage() != Some(LearningIterationStageV1::Selection)
            || snapshot.training_no_update_v2().is_some()
            || snapshot.receipts.get(2) != Some(self.training.receipt())
            || snapshot.receipts.last() != Some(self.evaluation.receipt())
            || self.evaluation.training_attestation() != self.training.attestation()
            || snapshot.owners.evidence_trust_digest != self.verifier.trust_digest()
            || snapshot.request.envelope.objective_digest != self.verifier.objective_digest()
            || !matches!(
                self.evaluation.receipt().observation,
                LearningIterationObservationV1::Evaluation {
                    disposition: LearningEvaluationDispositionV1::NoUpdate,
                    ..
                }
            )
        {
            return Err(Error::Binding(
                "original evaluated NoUpdate retention profile",
            ));
        }
        let candidate = coordinator
            .candidate()
            .ok_or(Error::Binding("original evaluated Candidate"))?;
        if candidate
            .digest()
            .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?
            == snapshot
                .request
                .selected_bundle
                .digest()
                .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?
        {
            return Err(Error::Binding(
                "evaluated retention requires a changed Candidate",
            ));
        }
        self.verify_original_predecessors(at)?;
        if matches!(access, PublicationAccess::NewWork)
            && at >= snapshot.request.envelope.expiry_unix_seconds
        {
            return Err(Error::DeadlineExceeded);
        }
        Ok(coordinator)
    }

    fn verify_original_predecessors(
        &self,
        at: u64,
    ) -> Result<[VerifiedLearningEvidenceV1; 2], Error> {
        let snapshot = self.snapshot();
        let original = [
            (
                LearningEvidenceRoleV1::Generator,
                self.training.receipt(),
                self.training.attestation(),
                &snapshot.owners.trainer,
            ),
            (
                LearningEvidenceRoleV1::Evaluator,
                self.evaluation.receipt(),
                self.evaluation.attestation(),
                &snapshot.owners.evaluator,
            ),
        ];
        let mut verified = Vec::with_capacity(2);
        for (role, receipt, signature, actor) in original {
            if &receipt.actor_id != actor
                || receipt.observed_unix_seconds > signature.issued_at
                || signature.issued_at > at
            {
                return Err(Error::Binding(
                    "original evaluated retention actor and time",
                ));
            }
            let evidence = self.verifier.verify(
                role,
                signature,
                &learning_iteration_receipt_signing_bytes_v1(receipt)?,
                at,
            )?;
            if &evidence.principal().principal_id != actor {
                return Err(Error::Binding("original evaluated retention signer"));
            }
            verified.push(evidence);
        }
        verify_signed_actor_separation(&verified[0], &verified[1], at)?;
        verified
            .try_into()
            .map_err(|_| Error::Binding("two original evaluated predecessors"))
    }

    // Receipt owners retain the same opaque pins and origin. This is not an
    // owner/client getter, a new stream, or a promotion from cold to fresh.
    pub(crate) fn clone_for_original_receipt(&self) -> Self {
        Self {
            scope: self.scope.clone(),
            verifier: self.verifier.clone(),
            training: self.training.clone(),
            evaluation: self.evaluation.clone(),
            origin: self.origin,
        }
    }

    pub(crate) fn into_original_receipt_readback(mut self) -> Self {
        self.origin = Origin::Readback;
        self
    }

    pub(crate) fn receipt_configuration(
        &self,
    ) -> (
        FrozenLearningScopeV2,
        LearningEvidenceVerifierV1,
        SignedLearningEvidenceV1,
    ) {
        (
            self.scope.clone(),
            self.verifier.clone(),
            self.training.attestation().clone(),
        )
    }

    pub(crate) fn receipt_context_binding(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.agentd.original-evaluated-retention-receipt-context.v1\0",
            self.snapshot().head_digest.as_array(),
            self.scope.binding().as_array(),
            self.verifier.trust_digest().as_array(),
            self.verifier.scope_digest().as_array(),
            self.verifier.objective_digest().as_array(),
            &self.training.attestation().signing_bytes(),
            &self.training.attestation().signature,
            &self.evaluation.attestation().signing_bytes(),
            &self.evaluation.attestation().signature,
        ])
    }

    pub(crate) fn original_receipt_predecessors(
        &self,
        at: u64,
    ) -> Result<[VerifiedLearningEvidenceV1; 2], Error> {
        self.authenticate(at, PublicationAccess::Readback)?;
        self.verify_original_predecessors(at)
    }

    pub(crate) fn require_new_original_receipt(&self, at: u64) -> Result<(), Error> {
        self.authenticate(at, PublicationAccess::NewWork)
            .map(|_| ())
    }

    pub(crate) async fn require_original_receipt_owners(
        &self,
        trainer: &OriginalCellQ24TrainingCommandClientV1,
        evaluator: &OriginalCellEvaluationCommandClientV1,
    ) -> Result<(), Error> {
        self.require_current(trainer, evaluator, PublicationAccess::Readback)
            .await
    }

    /// Read both original owners at every publication boundary. A renewed
    /// signature, missing record or changed predecessor is never repaired here.
    pub(super) async fn require_current(
        &self,
        trainer: &OriginalCellQ24TrainingCommandClientV1,
        evaluator: &OriginalCellEvaluationCommandClientV1,
        access: PublicationAccess,
    ) -> Result<(), Error> {
        let started = now()?;
        self.authenticate(started, access)?;
        let training = OriginalCellQ24TrainingCommandClientV1::readback(trainer).await?;
        if training != self.training {
            return Err(Error::Binding(
                "original evaluated retention Training changed",
            ));
        }
        let evaluation = OriginalCellEvaluationCommandClientV1::readback(evaluator).await?;
        if evaluation != self.evaluation {
            return Err(Error::Binding(
                "original evaluated retention Evaluation changed",
            ));
        }
        let finished = now()?;
        if finished < started {
            return Err(Error::Clock);
        }
        self.authenticate(finished, access)?;
        Ok(())
    }
}
