//! Proposal uses its initially delivered original Model purpose. Evaluation
//! I/O occurs outside the Model lane. The final Model read follows complete
//! D/T/E readback; saved results are exact comparison pins, never CURRENT.

use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;
use codex_hepta_types::AuthorityPosture;

use super::super::auth;
use super::Error;
use super::Origin;
use super::OriginalCellQ24CandidateStageOwnersV1;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24ModelCommandClientV1;
use crate::OriginalCellQ24ModelCommandConnectionV1;
use crate::OriginalCellQ24ModelCommandErrorV1;
use crate::OriginalCellQ24ModelCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::RootResidentLearningEffectGateV3;

pub(super) struct ModelLane {
    initial: Option<OriginalCellQ24ModelCommandConnectionV1>,
    client: Option<OriginalCellQ24ModelCommandClientV1>,
    retained: Option<OriginalCellQ24ModelCommandReceiptV1>,
    failed: bool,
}

impl ModelLane {
    pub(super) fn new(initial: OriginalCellQ24ModelCommandConnectionV1) -> Self {
        Self { initial: Some(initial), client: None, retained: None, failed: false }
    }

    #[cfg(test)]
    pub(super) fn fixture_unavailable() -> Self {
        Self { initial: None, client: None, retained: None, failed: false }
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum Action { Execute, Readback }

impl OriginalCellQ24CandidateStageOwnersV1 {
    pub(super) async fn execute_original_model(
        &self, snapshot: &LearningIterationSnapshotV1,
    ) -> Result<LearningIterationReceiptV1, Error> {
        if self.common.origin != Origin::Fresh || snapshot.receipts.len() != 4 {
            return Err(Error::WrongScope);
        }
        Ok(self.original_model(snapshot, Action::Execute).await?.receipt().clone())
    }

    /// Only the concrete Root bundle can request this original Model readback.
    /// No generic StageOwner signature API can represent Proposal evidence.
    pub(crate) async fn read_original_model(
        &self, snapshot: &LearningIterationSnapshotV1,
    ) -> Result<OriginalCellQ24ModelCommandReceiptV1, Error> {
        self.original_model(snapshot, Action::Readback).await
    }

    async fn original_model(
        &self, snapshot: &LearningIterationSnapshotV1, action: Action,
    ) -> Result<OriginalCellQ24ModelCommandReceiptV1, Error> {
        let started = auth::now()?;
        self.require_live_deadline()?;
        let training_cut = self.training_prefix(snapshot)?;
        if !(4..=5).contains(&snapshot.receipts.len()) {
            return Err(Error::WrongScope);
        }
        let mut evaluation_cut = LearningIterationCoordinatorV1::from_snapshot(training_cut.clone())?;
        let evaluation = &snapshot.receipts[3];
        evaluation_cut.record(evaluation.clone(), evaluation.observed_unix_seconds)?;
        if evaluation_cut.next_stage() != Some(Stage::Proposal)
            || !matches!(&evaluation.observation, LearningIterationObservationV1::Evaluation {
                disposition: LearningEvaluationDispositionV1::Qualified, ..
            })
            || action == Action::Execute && (self.common.origin != Origin::Fresh
                || evaluation_cut.snapshot() != snapshot)
        {
            return Err(Error::WrongScope);
        }
        {
            let mut lane = self.model.try_lock().map_err(|_| Error::QueueFull)?;
            if lane.failed { return Err(Error::CommitUncertain); }
            // This flag is never cleared on cancellation, changed CURRENT or
            // an unconfirmed dispatch. Recovery needs a new readonly handoff.
            lane.failed = true;
        }
        let before = self.model_predecessors(evaluation_cut.snapshot(), &training_cut).await?;
        if action == Action::Execute {
            let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
            RootResidentLearningEffectGateV3::require_current(
                gate, evaluation_cut.snapshot(), &self.common.material.scope,
            ).await?;
        }
        let actual = {
            let mut lane = self.model.try_lock().map_err(|_| Error::QueueFull)?;
            if lane.client.is_none() {
                let connection = lane.initial.take().ok_or(Error::CommitUncertain)?;
                lane.client = Some(OriginalCellQ24ModelCommandConnectionV1::bind_original_evaluation(
                    connection, before.0.clone(), before.1.clone(), before.2.clone(),
                ).map_err(model_failure)?);
            }
            let client = lane.client.as_ref().ok_or(Error::CommitUncertain)?;
            match action {
                Action::Execute => {
                    let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
                    OriginalCellQ24ModelCommandClientV1::commit_model(
                        client, RootResidentLearningEffectGateV3::training_cancellation(gate),
                    ).await
                }
                Action::Readback => OriginalCellQ24ModelCommandClientV1::readback(client).await,
            }.map_err(model_failure)?
        };
        // No Model/Trainer owner or Model lane is held during Evaluator I/O.
        let after = self.model_predecessors(evaluation_cut.snapshot(), &training_cut).await?;
        if before != after { return Err(Error::CommitUncertain); }
        let current = {
            let lane = self.model.try_lock().map_err(|_| Error::QueueFull)?;
            let client = lane.client.as_ref().ok_or(Error::CommitUncertain)?;
            OriginalCellQ24ModelCommandClientV1::readback(client).await.map_err(model_failure)?
        };
        if current != actual
            || current.authority() != AuthorityPosture::DENY_ALL
            || current.snapshot().receipts.len() != 5
            || !current.snapshot().receipts.starts_with(&evaluation_cut.snapshot().receipts)
            || snapshot.receipts.get(4).is_some_and(|original| original != current.receipt())
        {
            return Err(Error::CommitUncertain);
        }
        if action == Action::Execute {
            let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
            if RootResidentLearningEffectGateV3::require_current(
                gate, evaluation_cut.snapshot(), &self.common.material.scope,
            ).await.is_err() {
                return Err(Error::CommitUncertain);
            }
        }
        let common = self.common.continuation.try_lock().map_err(|_| Error::QueueFull)?;
        if common.original_dataset.as_ref() != Some(&after.0)
            || common.original_training.as_ref() != Some(&after.1)
        { return Err(Error::CommitUncertain); }
        let fresh = auth::require_material(&self.common.material, self.common.initial_binding)?;
        auth::require_clock(started, fresh)?;
        auth::verify_prefix(&self.common.material, &training_cut, &common, fresh)?;
        self.verify_original_evaluation(snapshot, &training_cut, &after.1, &after.2, fresh)?;
        self.common.material.scope.validate_snapshot(current.snapshot())?;
        self.require_live_deadline()?;
        let mut lane = self.model.try_lock().map_err(|_| Error::QueueFull)?;
        if lane.retained.as_ref().is_some_and(|saved| saved != &current) {
            return Err(Error::CommitUncertain);
        }
        lane.retained = Some(current.clone());
        lane.failed = false;
        Ok(current)
    }

    async fn model_predecessors(
        &self, evaluation_cut: &LearningIterationSnapshotV1, training_cut: &LearningIterationSnapshotV1,
    ) -> Result<(OriginalCellQ24MaterialCommandReceiptV1,
        OriginalCellQ24TrainingCommandReceiptV1, OriginalCellEvaluationCommandReceiptV1), Error>
    {
        let evaluation = self.read_original_evaluation(evaluation_cut).await?;
        let mut common = self.common.continuation.try_lock().map_err(|_| Error::QueueFull)?;
        common.read_prefix(&self.common, training_cut).await?;
        let dataset = common.original_dataset.as_ref().ok_or(Error::CommitUncertain)?.clone();
        let training = common.original_training.as_ref().ok_or(Error::CommitUncertain)?.clone();
        if evaluation.snapshot() != evaluation_cut || evaluation.training_attestation() != training.attestation() {
            return Err(Error::WrongScope);
        }
        Ok((dataset, training, evaluation))
    }
}

fn model_failure(error: OriginalCellQ24ModelCommandErrorV1) -> Error {
    use OriginalCellQ24ModelCommandErrorV1 as Source;
    match error {
        Source::Missing | Source::Pending | Source::ReadbackRequired | Source::CommitUncertain
        | Source::Cancelled => Error::CommitUncertain,
        Source::Busy => Error::QueueFull,
        Source::DeadlineExceeded => Error::DeadlineExceeded,
        Source::Evidence(error) => Error::Evidence(error),
        Source::Binding(_) | Source::Ineligible | Source::Iteration(_)
        | Source::Checkpoint(_) | Source::Encoding(_) => Error::WrongScope,
        Source::Unavailable | Source::Transport(_) | Source::Model(_) | Source::Stage(_)
        | Source::Training(_) | Source::Bootstrap(_) | Source::Material(_) | Source::Evaluation(_) => {
            Error::OwnerUnavailable("original Model journal and CURRENT")
        }
    }
}
