//! Complete original Model data pinned after an actual admitted Model read.
//! This is comparison metadata. Every publication and Selector operation must
//! contact its retained original Model and Evaluator owners again.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::AuthorityPosture;

use super::Error;
use super::now;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellEvaluationModelMaterialV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24ModelCommandClientV1;
use crate::OriginalCellQ24ModelCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;

/// No Clone, Deserialize, public fields or original owner extraction. Sharing
/// an Arc shares comparison data only, never a completed CURRENT observation.
pub struct OriginalCircuitModelPublicationContextV1 {
    material: OriginalCellQ24MaterialReceiptConfigV1,
    registration: OriginalCellEvaluationPanelRegistrationV1,
    dataset: OriginalCellQ24MaterialCommandReceiptV1,
    training: OriginalCellQ24TrainingCommandReceiptV1,
    evaluation: OriginalCellEvaluationCommandReceiptV1,
    model: OriginalCellQ24ModelCommandReceiptV1,
    training_cut: LearningIterationSnapshotV1,
}

impl OriginalCircuitModelPublicationContextV1 {
    pub async fn from_original_model(
        original: &OriginalCellQ24ModelCommandClientV1,
        material: OriginalCellQ24MaterialReceiptConfigV1,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        dataset: OriginalCellQ24MaterialCommandReceiptV1,
        training: OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: OriginalCellEvaluationCommandReceiptV1,
    ) -> Result<Self, Error> {
        let model = OriginalCellQ24ModelCommandClientV1::readback(original).await?;
        Self::from_original_receipt(material, registration, dataset, training, evaluation, model)
    }

    /// Only a concrete same-operation caller may pass its already obtained
    /// opaque Model result. This pure constructor never completes owner I/O.
    pub(crate) fn from_original_receipt(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        dataset: OriginalCellQ24MaterialCommandReceiptV1,
        training: OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: OriginalCellEvaluationCommandReceiptV1,
        model: OriginalCellQ24ModelCommandReceiptV1,
    ) -> Result<Self, Error> {
        let mut cut = LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())?;
        cut.record(training.receipt().clone(), training.receipt().observed_unix_seconds)?;
        let context = Self {
            material,
            registration,
            dataset,
            training,
            evaluation,
            model,
            training_cut: cut.snapshot().clone(),
        };
        context.authenticate(now()?, false)?;
        Ok(context)
    }

    pub fn decision(&self) -> &LearningIterationSnapshotV1 {
        self.model.snapshot()
    }

    pub fn scope(&self) -> &FrozenLearningScopeV2 {
        &self.material.scope
    }

    pub fn verifier(&self) -> &LearningEvidenceVerifierV1 {
        &self.material.verifier
    }

    pub fn model(&self) -> &OriginalCellQ24ModelCommandReceiptV1 {
        &self.model
    }

    pub(crate) fn signatures(&self) -> &[SignedLearningEvidenceV1; 4] {
        self.model.original_predecessors_for_publication()
    }

    pub(crate) fn authenticate(
        &self,
        lower: u64,
        new_work: bool,
    ) -> Result<LearningIterationCoordinatorV1, Error> {
        self.authenticate_at_current(lower, new_work).map(|(cut, _)| cut)
    }

    fn authenticate_at_current(
        &self,
        lower: u64,
        new_work: bool,
    ) -> Result<(LearningIterationCoordinatorV1, u64), Error> {
        let current = self.model.require_original_context(
            &self.material,
            &self.registration,
            &self.dataset,
            &self.training,
            &self.evaluation,
        )?;
        if current < lower {
            return Err(Error::Clock);
        }
        let decision = self.decision();
        self.scope().validate_snapshot(decision)?;
        self.scope()
            .require_verifier(self.verifier())
            .map_err(|_| Error::Binding("same original frozen Model verifier"))?;
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(decision.clone())?;
        let candidate = coordinator.candidate().ok_or(Error::Binding("original Model candidate"))?;
        let stages = [
            LearningIterationStageV1::Experience,
            LearningIterationStageV1::Dataset,
            LearningIterationStageV1::Training,
            LearningIterationStageV1::Evaluation,
            LearningIterationStageV1::Proposal,
        ];
        if decision.receipts.len() != stages.len()
            || !decision.receipts.iter().zip(stages).all(|(receipt, stage)| receipt.observation.stage() == stage)
            || coordinator.next_stage() != Some(LearningIterationStageV1::Selection)
            || coordinator.next_task_bundle() != Some(candidate)
            || candidate == &decision.request.selected_bundle
            || decision.training_no_update_v2().is_some()
            || self.model.authority() != AuthorityPosture::DENY_ALL
        {
            return Err(Error::Binding("exact qualified changed Model decision"));
        }
        let mut verified = Vec::with_capacity(4);
        for ((receipt, signed), role) in decision.receipts.iter().take(4).zip(self.signatures()).zip([
            LearningEvidenceRoleV1::Observer,
            LearningEvidenceRoleV1::Observer,
            LearningEvidenceRoleV1::Generator,
            LearningEvidenceRoleV1::Evaluator,
        ]) {
            let evidence = self.verifier().verify(
                role,
                signed,
                &learning_iteration_receipt_signing_bytes_v1(receipt)?,
                current,
            )?;
            if evidence.principal().principal_id != receipt.actor_id
                || receipt.actor_id != *decision.owners.owner(receipt.observation.stage())
                || receipt.observed_unix_seconds > signed.issued_at
                || signed.issued_at > current
            {
                return Err(Error::Binding("complete original Model predecessor identities"));
            }
            verified.push(evidence);
        }
        verify_signed_actor_separation(&verified[2], &verified[3], current)?;
        if new_work && current >= decision.request.envelope.expiry_unix_seconds {
            return Err(Error::DeadlineExceeded);
        }
        Ok((coordinator, current))
    }

    pub(crate) async fn require_model_current(
        &self,
        original: &OriginalCellQ24ModelCommandClientV1,
        new_work: bool,
    ) -> Result<(), Error> {
        let started = now()?;
        self.authenticate(started, new_work)?;
        let actual = OriginalCellQ24ModelCommandClientV1::readback(original).await?;
        if actual != self.model {
            return Err(Error::Binding("unchanged full original Model receipt and four signatures"));
        }
        self.authenticate(started, new_work)?;
        Ok(())
    }

    /// Called after the actual final owner I/O. Every primary and retention
    /// signature is checked, including the complete original cohort freezes.
    pub(crate) fn authenticate_material(
        &self,
        material: &OriginalCellEvaluationModelMaterialV1,
        lower: u64,
        new_work: bool,
    ) -> Result<u64, Error> {
        let (coordinator, current) = self.authenticate_at_current(lower, new_work)?;
        material.authenticate_current(current)?;
        let input = material.require_original_model_input(
            &self.training_cut,
            self.training.attestation(),
            current,
        )?;
        if material.original_evaluation() != &self.evaluation
            || input.material_digest() != self.model.material_digest()
            || input.evaluation() != self.evaluation.receipt()
            || input.candidate() != coordinator.candidate()
                .ok_or(Error::Binding("original Model candidate"))?.digest()
                    .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?
        {
            return Err(Error::Binding("complete original Model and B/retention material"));
        }
        let mut expiry = material.original_publication_expiry(current)?;
        for ((receipt, signed), role) in self.decision().receipts.iter().take(4).zip(self.signatures()).zip([
            LearningEvidenceRoleV1::Observer,
            LearningEvidenceRoleV1::Observer,
            LearningEvidenceRoleV1::Generator,
            LearningEvidenceRoleV1::Evaluator,
        ]) {
            let verified = self.verifier().verify(
                role, signed, &learning_iteration_receipt_signing_bytes_v1(receipt)?, current,
            )?;
            expiry = expiry.min(signed.expires_at).min(verified.principal().expires_at);
        }
        if expiry <= current {
            return Err(Error::DeadlineExceeded);
        }
        Ok(expiry)
    }
}
