//! The actual independent Evaluator command in the original Candidate lane.
//! The initial connection is consumed once after original D/T readback. No
//! returned Evaluation or Candidate material is a Model/publication grant.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::AuthorityPosture;

use super::super::auth;
use super::CandidateRead;
use super::Error;
use super::Origin;
use super::OriginalCellQ24CandidateStageOwnersV1;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellEvaluationCommandConnectionV1;
use crate::OriginalCellEvaluationCommandErrorV1;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::RootResidentLearningEffectGateV3;

pub(super) struct EvaluationLane {
    initial: Option<OriginalCellEvaluationCommandConnectionV1>,
    client: Option<OriginalCellEvaluationCommandClientV1>,
    retained: Option<OriginalCellEvaluationCommandReceiptV1>,
    failed: bool,
}

impl EvaluationLane {
    pub(super) fn new(initial: OriginalCellEvaluationCommandConnectionV1) -> Self {
        Self {
            initial: Some(initial),
            client: None,
            retained: None,
            failed: false,
        }
    }

    #[cfg(test)]
    pub(super) fn fixture_unavailable() -> Self {
        Self {
            initial: None,
            client: None,
            retained: None,
            failed: false,
        }
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum Action {
    Execute,
    Readback,
}

impl OriginalCellQ24CandidateStageOwnersV1 {
    pub(super) fn training_prefix(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<LearningIterationSnapshotV1, Error> {
        let complete = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        self.common.material.scope.validate_snapshot(snapshot)?;
        if snapshot.request != self.common.material.initial.request
            || snapshot.owners != self.common.material.initial.owners
            || !(3..=7).contains(&snapshot.receipts.len())
            || snapshot.training_no_update_v2().is_some()
            || complete.candidate().is_none()
        {
            return Err(Error::WrongScope);
        }
        let mut prefix =
            LearningIterationCoordinatorV1::from_snapshot(self.common.material.initial.clone())?;
        for original in &snapshot.receipts[..3] {
            prefix.record(original.clone(), original.observed_unix_seconds)?;
        }
        if prefix.next_stage() != Some(Stage::Evaluation)
            || prefix.candidate() != complete.candidate()
        {
            return Err(Error::WrongScope);
        }
        self.common
            .material
            .scope
            .validate_snapshot(prefix.snapshot())?;
        Ok(prefix.snapshot().clone())
    }

    pub(super) async fn execute_original_evaluation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<LearningIterationReceiptV1, Error> {
        if self.common.origin != Origin::Fresh
            || snapshot.receipts.len() != 3
            || LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?.next_stage()
                != Some(Stage::Evaluation)
        {
            return Err(Error::WrongScope);
        }
        let original = self.original_evaluation(snapshot, Action::Execute).await?;
        Ok(original.receipt().clone())
    }

    pub(super) async fn read_original_evaluation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<OriginalCellEvaluationCommandReceiptV1, Error> {
        self.original_evaluation(snapshot, Action::Readback).await
    }

    async fn original_evaluation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        action: Action,
    ) -> Result<OriginalCellEvaluationCommandReceiptV1, Error> {
        let started_at = auth::now()?;
        self.require_live_deadline()?;
        let training_cut = self.training_prefix(snapshot)?;
        if action == Action::Execute
            && (self.common.origin != Origin::Fresh || snapshot != &training_cut)
        {
            return Err(Error::WrongScope);
        }
        let mut lane_lease = self.evaluation.try_take()?;
        let lane = lane_lease.state_mut()?;
        if lane.failed {
            return Err(Error::CommitUncertain);
        }
        // Cancellation leaves this same instance fenced. Only a separately
        // delivered original readonly recovery may inspect the actual effect.
        lane.failed = true;
        let mode = if action == Action::Execute {
            CandidateRead::Dispatch
        } else {
            CandidateRead::Readback
        };
        let before = OriginalCellQ24CandidateStageOwnersV1::read_original_candidate(
            self,
            &training_cut,
            mode,
        )
        .await?;
        let (dataset, training) = {
            let mut common_lease = self.common.continuation.try_take()?;
            let common = common_lease.state_mut()?;
            common.read_prefix(&self.common, &training_cut).await?;
            (
                common
                    .original_dataset
                    .as_ref()
                    .ok_or(Error::CommitUncertain)?
                    .clone(),
                common
                    .original_training
                    .as_ref()
                    .ok_or(Error::CommitUncertain)?
                    .clone(),
            )
        };
        if before.receipt() != training.receipt() || before.attestation() != training.attestation()
        {
            return Err(Error::WrongScope);
        }
        if lane.client.is_none() {
            let connection = lane.initial.take().ok_or(Error::CommitUncertain)?;
            lane.client = Some(
                OriginalCellEvaluationCommandConnectionV1::bind_original_training(
                    connection,
                    dataset.snapshot().clone(),
                    &training,
                )
                .map_err(evaluation_failure)?,
            );
        }
        if action == Action::Execute {
            let gate = self.common.root.as_ref().ok_or(Error::OwnerUnavailable(
                "fresh resident Evaluation continuation",
            ))?;
            // The actual pending intent is T -> E. Neither an E result nor
            // readback of its signature changes Root's checkpoint prematurely.
            RootResidentLearningEffectGateV3::require_current(
                gate,
                &training_cut,
                &self.common.material.scope,
            )
            .await?;
        }
        let client = lane.client.as_ref().ok_or(Error::CommitUncertain)?;
        let result = match action {
            Action::Execute => {
                OriginalCellEvaluationCommandClientV1::execute_evaluation(client).await
            }
            Action::Readback => OriginalCellEvaluationCommandClientV1::readback(client).await,
        };
        if action == Action::Execute {
            let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
            if RootResidentLearningEffectGateV3::require_current(
                gate,
                &training_cut,
                &self.common.material.scope,
            )
            .await
            .is_err()
            {
                return Err(Error::CommitUncertain);
            }
        }
        let original = result.map_err(evaluation_failure)?;
        let after = OriginalCellQ24CandidateStageOwnersV1::read_original_candidate(
            self,
            &training_cut,
            mode,
        )
        .await?;
        if before.bundle() != after.bundle()
            || before.heads() != after.heads()
            || before.receipt() != after.receipt()
            || before.attestation() != after.attestation()
        {
            return Err(Error::CommitUncertain);
        }
        let mut common_lease = self.common.continuation.try_take()?;
        let common = common_lease.state_mut()?;
        common.read_prefix(&self.common, &training_cut).await?;
        if action == Action::Execute {
            let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
            if RootResidentLearningEffectGateV3::require_current(
                gate,
                &training_cut,
                &self.common.material.scope,
            )
            .await
            .is_err()
            {
                return Err(Error::CommitUncertain);
            }
        }
        // All original Source, role and Root I/O precedes this common fresh
        // validation of the complete original E/D/T/Evaluation signatures.
        let fresh = auth::require_material(&self.common.material, self.common.initial_binding)?;
        auth::require_clock(started_at, fresh)?;
        auth::verify_prefix(&self.common.material, &training_cut, common, fresh)?;
        let current_training = common
            .original_training
            .as_ref()
            .ok_or(Error::CommitUncertain)?;
        if current_training != &training {
            return Err(Error::WrongScope);
        }
        self.verify_original_evaluation(snapshot, &training_cut, &training, &original, fresh)?;
        self.require_live_deadline()?;
        if lane
            .retained
            .as_ref()
            .is_some_and(|saved| saved != &original)
        {
            return Err(Error::WrongScope);
        }
        lane.retained = Some(original.clone());
        lane.failed = false;
        Ok(original)
    }

    pub(super) fn verify_original_evaluation(
        &self,
        supplied: &LearningIterationSnapshotV1,
        training_cut: &LearningIterationSnapshotV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        original: &OriginalCellEvaluationCommandReceiptV1,
        current: u64,
    ) -> Result<(), Error> {
        let receipt = original.receipt();
        let signed = original.attestation();
        let candidate = LearningIterationCoordinatorV1::from_snapshot(training_cut.clone())?;
        let expected = candidate
            .candidate()
            .ok_or(Error::WrongScope)?
            .digest()
            .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
        self.common
            .material
            .scope
            .validate_snapshot(original.snapshot())?;
        if original.snapshot().request != training_cut.request
            || original.snapshot().owners != training_cut.owners
            || original.snapshot().receipts.len() != 4
            || !original
                .snapshot()
                .receipts
                .starts_with(&training_cut.receipts)
            || original.snapshot().receipts.last() != Some(receipt)
            || original.training_attestation() != training.attestation()
            || original.authority() != AuthorityPosture::DENY_ALL
            || supplied
                .receipts
                .get(3)
                .is_some_and(|saved| saved != receipt)
            || receipt.operation_id != training_cut.request.operation_id
            || receipt.predecessor != training_cut.head_digest
            || receipt.actor_id != training_cut.owners.evaluator
            || receipt.observed_unix_seconds > signed.issued_at
            || receipt.observed_unix_seconds > current
            || !matches!(&receipt.observation, LearningIterationObservationV1::Evaluation {
                candidate_bundle, evaluation_profile, ..
            } if *candidate_bundle == expected
                && *evaluation_profile == self.protocol.evaluation_profile())
        {
            return Err(Error::WrongScope);
        }
        let generator = auth::verify_receipt(
            &self.common.material,
            training.receipt(),
            training.attestation(),
            current,
        )?;
        let evaluator = self
            .common
            .material
            .verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                signed,
                &learning_iteration_receipt_signing_bytes_v1(receipt)?,
                current,
            )
            .map_err(Error::Evidence)?;
        if evaluator.principal().principal_id != receipt.actor_id {
            return Err(Error::WrongScope);
        }
        verify_signed_actor_separation(&generator, &evaluator, current).map_err(Error::Evidence)?;
        let mut coordinator = candidate;
        coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
        if coordinator.snapshot() != original.snapshot() {
            return Err(Error::WrongScope);
        }
        Ok(())
    }
}

fn evaluation_failure(error: OriginalCellEvaluationCommandErrorV1) -> Error {
    use OriginalCellEvaluationCommandErrorV1 as Source;
    match error {
        Source::Missing | Source::Pending | Source::ReadbackRequired | Source::CommitUncertain => {
            Error::CommitUncertain
        }
        Source::DeadlineExceeded => Error::DeadlineExceeded,
        Source::Busy => Error::QueueFull,
        Source::Evidence(error) => Error::Evidence(error),
        Source::Binding(_) | Source::Iteration(_) | Source::Checkpoint(_) | Source::Encoding(_) => {
            Error::WrongScope
        }
        Source::Unavailable
        | Source::Transport(_)
        | Source::Receipt(_)
        | Source::Panel(_)
        | Source::Qualification(_)
        | Source::Journal(_)
        | Source::PredecessorUnavailable => {
            Error::OwnerUnavailable("original independent B/retention Evaluator")
        }
    }
}
