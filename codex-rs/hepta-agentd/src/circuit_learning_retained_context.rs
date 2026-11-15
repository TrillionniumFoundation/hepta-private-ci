//! Exact original NoUpdate context. This data is never publication authority.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use super::OriginalCircuitRetainedPublicationErrorV1;
use super::now;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;

/// Created from an actual opaque Trainer response. A later call must still read
/// that same original owner. No Candidate, evaluation rejection or empty cut
/// can be converted into this strict TrainingNoUpdate profile.
pub struct OriginalCircuitRetainedPublicationContextV1 {
    pub(super) training: LearningIterationSnapshotV1,
    pub(super) scope: FrozenLearningScopeV2,
    pub(super) verifier: LearningEvidenceVerifierV1,
    pub(super) training_evidence: SignedLearningEvidenceV1,
}

#[derive(Clone, Copy)]
pub(super) enum PublicationAccess {
    NewWork,
    Readback,
}

impl OriginalCircuitRetainedPublicationContextV1 {
    pub fn from_original_training(
        dataset: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        verifier: LearningEvidenceVerifierV1,
        original: &OriginalCellQ24TrainingCommandReceiptV1,
    ) -> Result<Self, OriginalCircuitRetainedPublicationErrorV1> {
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(dataset)?;
        if coordinator.next_stage() != Some(LearningIterationStageV1::Training)
            || coordinator.snapshot().receipts.len() != 2
        {
            return Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
                "original Dataset before Training",
            ));
        }
        coordinator.record(
            original.receipt().clone(),
            original.receipt().observed_unix_seconds,
        )?;
        let context = Self {
            training: coordinator.snapshot().clone(),
            scope,
            verifier,
            training_evidence: original.attestation().clone(),
        };
        context.authenticate(now()?, PublicationAccess::NewWork)?;
        Ok(context)
    }

    pub(super) fn authenticate(
        &self,
        at: u64,
        access: PublicationAccess,
    ) -> Result<LearningIterationCoordinatorV1, OriginalCircuitRetainedPublicationErrorV1> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(self.training.clone())?;
        self.scope.validate_snapshot(&self.training)?;
        let receipt = self.training.receipts.last().ok_or(
            OriginalCircuitRetainedPublicationErrorV1::Binding("original Training receipt"),
        )?;
        if self.training.receipts.len() != 3
            || coordinator.next_stage() != Some(LearningIterationStageV1::Selection)
            || !matches!(
                &receipt.observation,
                LearningIterationObservationV1::TrainingNoUpdateV2(_)
            )
            || self.training.owners.evidence_trust_digest != self.verifier.trust_digest()
            || self.training.request.envelope.objective_digest != self.verifier.objective_digest()
            || receipt.actor_id != self.training.owners.trainer
            || receipt.observed_unix_seconds != self.training_evidence.issued_at
            || receipt.observed_unix_seconds > at
        {
            return Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
                "strict original TrainingNoUpdate publication profile",
            ));
        }
        let verified = self.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &self.training_evidence,
            &learning_iteration_receipt_signing_bytes_v1(receipt)?,
            at,
        )?;
        if verified.principal().principal_id != self.training.owners.trainer {
            return Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
                "original enrolled Trainer",
            ));
        }
        if matches!(access, PublicationAccess::NewWork)
            && at >= self.training.request.envelope.expiry_unix_seconds
        {
            return Err(OriginalCircuitRetainedPublicationErrorV1::DeadlineExceeded);
        }
        Ok(coordinator)
    }

    pub(super) async fn require_training_current(
        &self,
        trainer: &OriginalCellQ24TrainingCommandClientV1,
        access: PublicationAccess,
    ) -> Result<(), OriginalCircuitRetainedPublicationErrorV1> {
        let started = now()?;
        self.authenticate(started, access)?;
        let actual = OriginalCellQ24TrainingCommandClientV1::readback(trainer).await?;
        if self.training.receipts.last() != Some(actual.receipt())
            || &self.training_evidence != actual.attestation()
        {
            return Err(OriginalCircuitRetainedPublicationErrorV1::Binding(
                "original complete Training receipt and signature changed",
            ));
        }
        let finished = now()?;
        if finished < started {
            return Err(OriginalCircuitRetainedPublicationErrorV1::Clock);
        }
        self.authenticate(finished, access)?;
        Ok(())
    }
}
