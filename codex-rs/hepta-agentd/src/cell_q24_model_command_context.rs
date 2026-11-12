//! Full original D/T/E and initial context. This private value is built only
//! from the existing opaque command results; no request can upload these rows.
use super::Error;
use super::now;
use super::require_clock;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;

#[derive(Clone)]
pub(in super::super) struct Context {
    pub(in super::super) material: OriginalCellQ24MaterialReceiptConfigV1,
    pub(in super::super) registration: OriginalCellEvaluationPanelRegistrationV1,
    pub(in super::super) dataset: OriginalCellQ24MaterialCommandReceiptV1,
    pub(in super::super) training: OriginalCellQ24TrainingCommandReceiptV1,
    pub(in super::super) evaluation: OriginalCellEvaluationCommandReceiptV1,
    pub(in super::super) training_cut: LearningIterationSnapshotV1,
    initial_binding: Digest32,
}
impl Context {
    pub(in super::super) fn from_original(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        registration: OriginalCellEvaluationPanelRegistrationV1,
        dataset: OriginalCellQ24MaterialCommandReceiptV1,
        training: OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: OriginalCellEvaluationCommandReceiptV1,
    ) -> Result<Self, Error> {
        let (initial_binding, started) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())?;
        if dataset.snapshot().receipts.len() != 2
            || coordinator.next_stage() != Some(LearningIterationStageV1::Training)
        {
            return Err(Error::Binding("actual original Dataset cut"));
        }
        coordinator.record(
            training.receipt().clone(),
            training.receipt().observed_unix_seconds,
        )?;
        let original = Self {
            material,
            registration,
            dataset,
            training,
            evaluation,
            training_cut: coordinator.snapshot().clone(),
            initial_binding,
        };
        Self::authenticate(&original, started)?;
        Ok(original)
    }

    pub(in super::super) fn authenticate(&self, lower: u64) -> Result<u64, Error> {
        let (binding, at) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(
                &self.material,
            )?;
        let dataset_at = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            &self.dataset,
            &self.material,
        )?;
        let current = now()?;
        require_clock(lower, at)?;
        require_clock(at, dataset_at)?;
        require_clock(dataset_at, current)?;
        let initial = LearningIterationCoordinatorV1::new(
            self.training_cut.request.clone(),
            self.training_cut.owners.clone(),
        )?;
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(self.training_cut.clone())?;
        let t = self.training.receipt();
        let e = self.evaluation.receipt();
        if binding != self.initial_binding
            || initial.snapshot() != &self.material.initial
            || self.training_cut.receipts.len() != 3
            || coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation)
            || self.training_cut.receipts.last() != Some(t)
            || !self
                .training_cut
                .receipts
                .starts_with(&self.dataset.snapshot().receipts)
            || !matches!(
                &t.observation,
                LearningIterationObservationV1::Training { .. }
            )
            || self.training_cut.request.evaluation_profile
                != self.registration.evaluation_profile()
            || self.evaluation.training_attestation() != self.training.attestation()
            || t.actor_id != self.training_cut.owners.trainer
            || t.observed_unix_seconds != self.training.attestation().issued_at
            || e.actor_id != self.training_cut.owners.evaluator
            || e.observed_unix_seconds > self.evaluation.attestation().issued_at
            || t.observed_unix_seconds > current
            || e.observed_unix_seconds > current
        {
            return Err(Error::Binding(
                "unchanged original Dataset, Candidate and full T/E signatures",
            ));
        }
        let verifier = &self.material.verifier;
        let generator = verifier.verify(
            LearningEvidenceRoleV1::Generator,
            self.training.attestation(),
            &learning_iteration_receipt_signing_bytes_v1(t)?,
            current,
        )?;
        let evaluator = verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            self.evaluation.attestation(),
            &learning_iteration_receipt_signing_bytes_v1(e)?,
            current,
        )?;
        if generator.principal().principal_id != self.training_cut.owners.trainer
            || evaluator.principal().principal_id != self.training_cut.owners.evaluator
        {
            return Err(Error::Binding("original enrolled Generator and Evaluator"));
        }
        verify_signed_actor_separation(&generator, &evaluator, current)?;
        coordinator.record(e.clone(), e.observed_unix_seconds)?;
        self.material
            .scope
            .validate_snapshot(coordinator.snapshot())?;
        if coordinator.snapshot() != self.evaluation.snapshot()
            || self.evaluation.snapshot().receipts.len() != 4
        {
            return Err(Error::Binding("exact original Evaluation extension"));
        }
        Ok(current)
    }

    pub(in super::super) fn require_qualified(&self) -> Result<(), Error> {
        if !matches!(
            &self.evaluation.receipt().observation,
            LearningIterationObservationV1::Evaluation {
                disposition: LearningEvaluationDispositionV1::Qualified,
                ..
            }
        ) || LearningIterationCoordinatorV1::from_snapshot(self.evaluation.snapshot().clone())?
            .next_stage()
            != Some(LearningIterationStageV1::Proposal)
        {
            return Err(Error::Ineligible);
        }
        Ok(())
    }

    pub(in super::super) fn binding(&self) -> Result<Digest32, Error> {
        let mut bytes = b"hepta.agentd.original-q24-model-command.v1\0".to_vec();
        for digest in [
            self.initial_binding,
            self.material.scope.binding(),
            self.registration.evaluation_profile(),
            self.material.verifier.trust_digest(),
            self.material.verifier.scope_digest(),
            self.material.verifier.objective_digest(),
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        let snapshot = encode_original_owner_snapshot_v1(self.evaluation.snapshot())?;
        bytes.extend_from_slice(&(snapshot.len() as u64).to_be_bytes());
        bytes.extend_from_slice(&snapshot);
        for signed in self
            .dataset
            .attestations()
            .iter()
            .chain([self.training.attestation(), self.evaluation.attestation()])
        {
            let original = signed.signing_bytes();
            bytes.extend_from_slice(&(original.len() as u64).to_be_bytes());
            bytes.extend_from_slice(&original);
            bytes.extend_from_slice(&signed.signature);
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}
