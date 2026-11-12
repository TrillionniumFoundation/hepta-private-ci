//! Proposal uses its initially delivered original Model purpose. Evaluation
//! I/O occurs outside the native Training lane. One original Model operation
//! spans the Candidate prefix closure, then performs actual E Finish and the
//! last native Model read. Saved results are only exact comparison pins.

use std::sync::Arc;

use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;
use codex_hepta_types::AuthorityPosture;

use super::Error;
use super::Origin;
use super::OriginalCellQ24CandidateStageOwnersV1;
use super::OriginalCandidateOperationEvidence;
use super::operation::CandidateOriginalOperation;
use crate::OriginalCellQ24ModelCommandClientV1;
use crate::OriginalCellQ24ModelCommandConnectionV1;
use crate::OriginalCellQ24ModelCommandErrorV1;
use crate::OriginalCellQ24ModelCommandReceiptV1;
use crate::OriginalCellQ24ModelReadV1;
use crate::OriginalCellQ24ModelReadCompletionV1;
use crate::OriginalCircuitModelPublicationContextV1;
use crate::RootResidentLearningEffectGateV3;

pub(super) struct ModelLane {
    initial: Option<OriginalCellQ24ModelCommandConnectionV1>,
    client: Option<Arc<OriginalCellQ24ModelCommandClientV1>>,
    retained: Option<OriginalCellQ24ModelCommandReceiptV1>,
    failed: bool,
}

impl ModelLane {
    pub(super) fn new(initial: OriginalCellQ24ModelCommandConnectionV1) -> Self {
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
pub(super) enum Action {
    Execute,
    Readback,
}

impl OriginalCellQ24CandidateStageOwnersV1 {
    pub(super) async fn execute_original_model(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<LearningIterationReceiptV1, Error> {
        if self.common.origin != Origin::Fresh || snapshot.receipts.len() != 4 {
            return Err(Error::WrongScope);
        }
        Ok(self
            .original_model(snapshot, Action::Execute)
            .await?
            .into_model()?
            .receipt()
            .clone())
    }

    /// Only the concrete Root bundle can request this original Model readback.
    /// No generic StageOwner signature API can represent Proposal evidence.
    pub(crate) async fn read_original_model(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<OriginalCellQ24ModelCommandReceiptV1, Error> {
        self.original_model(snapshot, Action::Readback).await?.into_model()
    }

    pub(super) async fn original_model(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        action: Action,
    ) -> Result<OriginalCandidateOperationEvidence<'_>, Error> {
        self.require_live_deadline()?;
        let training_cut = self.training_prefix(snapshot)?;
        if !(4..=5).contains(&snapshot.receipts.len()) {
            return Err(Error::WrongScope);
        }
        let mut evaluation_cut =
            LearningIterationCoordinatorV1::from_snapshot(training_cut.clone())?;
        let evaluation = &snapshot.receipts[3];
        evaluation_cut.record(evaluation.clone(), evaluation.observed_unix_seconds)?;
        if evaluation_cut.next_stage() != Some(Stage::Proposal)
            || !matches!(
                &evaluation.observation,
                LearningIterationObservationV1::Evaluation {
                    disposition: LearningEvaluationDispositionV1::Qualified,
                    ..
                }
            )
            || action == Action::Execute
                && (self.common.origin != Origin::Fresh || evaluation_cut.snapshot() != snapshot)
        {
            return Err(Error::WrongScope);
        }
        let operation = CandidateOriginalOperation::begin(self, snapshot).await?;
        {
            let mut lane = self.model.try_lock().map_err(|_| Error::QueueFull)?;
            if lane.failed {
                return Err(Error::CommitUncertain);
            }
            // This flag is never cleared on cancellation, changed CURRENT or
            // an unconfirmed dispatch. Recovery needs a new readonly handoff.
            lane.failed = true;
        }
        let before = OriginalCellQ24CandidateStageOwnersV1::read_evaluation_in_operation(
            self, &operation, super::evaluation::Action::Readback,
        ).await?;
        if before.snapshot() != evaluation_cut.snapshot()
            || before.training_attestation() != operation.training.attestation()
        {
            return Err(Error::WrongScope);
        }
        if action == Action::Execute {
            let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
            RootResidentLearningEffectGateV3::require_current(
                gate,
                evaluation_cut.snapshot(),
                &self.common.material.scope,
            )
            .await?;
        }
        let client = {
            let mut lane = self.model.try_lock().map_err(|_| Error::QueueFull)?;
            if lane.client.is_none() {
                let connection = lane.initial.take().ok_or(Error::CommitUncertain)?;
                lane.client = Some(Arc::new(
                    OriginalCellQ24ModelCommandConnectionV1::bind_original_evaluation(
                        connection,
                        operation.dataset.clone(),
                        operation.training.clone(),
                        before.clone(),
                    ).map_err(model_failure)?,
                ));
            }
            Arc::clone(lane.client.as_ref().ok_or(Error::CommitUncertain)?)
        };
        // The Candidate Model mutex is released here. The Model host also
        // releases every native Training permit before its E network reads.
        let original: OriginalCellQ24ModelReadV1<'_> = match action {
            Action::Execute => {
                let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
                OriginalCellQ24ModelCommandClientV1::begin_original_model_commit(
                    client.as_ref(),
                    RootResidentLearningEffectGateV3::training_cancellation(gate),
                ).await
            }
            Action::Readback => OriginalCellQ24ModelCommandClientV1::begin_original_model_read(
                client.as_ref(),
            ).await,
        }.map_err(|_| Error::CommitUncertain)?;
        if original.material().original_evaluation() != &before {
            return Err(Error::CommitUncertain);
        }
        let actual = original.model().clone();
        // This actual independent D/T prefix read occurs while the original
        // Model/E transfer remains open, with no native T lane held.
        let closed = CandidateOriginalOperation::close(operation)
            .await.map_err(|_| Error::CommitUncertain)?;
        // Finish reads the original E/retention and then the final native
        // Model/T. There is no second whole Model or outer E transfer.
        let completed: OriginalCellQ24ModelReadCompletionV1 =
            original.finish().await.map_err(|_| Error::CommitUncertain)?;
        let after = completed.material().original_evaluation();
        let current: &OriginalCellQ24ModelCommandReceiptV1 = completed.model();
        if &before != after {
            return Err(Error::CommitUncertain);
        }
        if current != &actual
            || current.authority() != AuthorityPosture::DENY_ALL
            || current.snapshot().receipts.len() != 5
            || !current
                .snapshot()
                .receipts
                .starts_with(&evaluation_cut.snapshot().receipts)
            || snapshot
                .receipts
                .get(4)
                .is_some_and(|original| original != current.receipt())
        {
            return Err(Error::CommitUncertain);
        }
        if action == Action::Execute {
            let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
            if RootResidentLearningEffectGateV3::require_current(
                gate,
                evaluation_cut.snapshot(),
                &self.common.material.scope,
            )
            .await
            .is_err()
            {
                return Err(Error::CommitUncertain);
            }
        }
        self.common.material.scope.validate_snapshot(current.snapshot())?;
        self.require_live_deadline()?;
        let mut lane = self.model.try_lock().map_err(|_| Error::QueueFull)?;
        if lane
            .retained
            .as_ref()
            .is_some_and(|saved| saved != current)
        {
            return Err(Error::CommitUncertain);
        }
        lane.retained = Some(current.clone());
        let evidence = closed.model(completed)?;
        lane.failed = false;
        Ok(evidence)
    }

    /// An adoption operation needs a new actual Model/E observation. A saved
    /// client supplies only the original connection and comparison context.
    /// Finish releases the Model host before Version/S/C can call that same host.
    pub(super) async fn read_model_for_adoption(
        &self,
        operation: &CandidateOriginalOperation<'_>,
    ) -> Result<crate::OriginalCellQ24ModelReadCompletionV1, Error> {
        operation.require_owner(self)?;
        let expected = super::adoption::model_cut(self, &operation.supplied)?;
        let needs_binding = {
            let mut lane = self.model.try_lock().map_err(|_| Error::QueueFull)?;
            if lane.failed { return Err(Error::CommitUncertain); }
            lane.failed = true;
            lane.client.is_none()
        };
        if needs_binding {
            let evaluation = OriginalCellQ24CandidateStageOwnersV1::read_evaluation_in_operation(
                self, operation, super::evaluation::Action::Readback,
            ).await?;
            let mut lane = self.model.try_lock().map_err(|_| Error::QueueFull)?;
            if lane.client.is_some() { return Err(Error::CommitUncertain); }
            let initial = lane.initial.take().ok_or(Error::CommitUncertain)?;
            lane.client = Some(Arc::new(
                OriginalCellQ24ModelCommandConnectionV1::bind_original_evaluation(
                    initial, operation.dataset.clone(), operation.training.clone(), evaluation,
                ).map_err(model_failure)?,
            ));
        }
        let client = {
            let lane = self.model.try_lock().map_err(|_| Error::QueueFull)?;
            Arc::clone(lane.client.as_ref().ok_or(Error::CommitUncertain)?)
        };
        let original: OriginalCellQ24ModelReadV1<'_> = OriginalCellQ24ModelCommandClientV1::begin_original_model_read(
            client.as_ref(),
        ).await.map_err(|_| Error::CommitUncertain)?;
        if original.model().snapshot() != &expected {
            return Err(Error::CommitUncertain);
        }
        let before = original.model().clone();
        let completed: OriginalCellQ24ModelReadCompletionV1 =
            original.finish().await.map_err(|_| Error::CommitUncertain)?;
        if completed.model() != &before {
            return Err(Error::CommitUncertain);
        }
        // The complete opaque D/T/E context is compared before any adoption
        // dispatch. This pure factory does not turn the pin into a CURRENT.
        let context: OriginalCircuitModelPublicationContextV1 =
            super::adoption::publication_context(self, operation, &completed)?;
        context.authenticate_material(
            completed.material(), super::super::auth::now()?, false,
        ).map_err(|_| Error::CommitUncertain)?;
        self.require_live_deadline()?;
        let mut lane = self.model.try_lock().map_err(|_| Error::QueueFull)?;
        if lane.retained.as_ref().is_some_and(|saved| saved != completed.model()) {
            return Err(Error::CommitUncertain);
        }
        lane.retained = Some(completed.model().clone());
        lane.failed = false;
        Ok(completed)
    }

}

fn model_failure(error: OriginalCellQ24ModelCommandErrorV1) -> Error {
    use OriginalCellQ24ModelCommandErrorV1 as Source;
    match error {
        Source::Missing
        | Source::Pending
        | Source::ReadbackRequired
        | Source::CommitUncertain
        | Source::Cancelled => Error::CommitUncertain,
        Source::Busy => Error::QueueFull,
        Source::DeadlineExceeded => Error::DeadlineExceeded,
        Source::Evidence(error) => Error::Evidence(error),
        Source::Binding(_)
        | Source::Ineligible
        | Source::Iteration(_)
        | Source::Checkpoint(_)
        | Source::Encoding(_) => Error::WrongScope,
        Source::Unavailable
        | Source::Transport(_)
        | Source::Model(_)
        | Source::Stage(_)
        | Source::Training(_)
        | Source::Bootstrap(_)
        | Source::Material(_)
        | Source::Evaluation(_) => Error::OwnerUnavailable("original Model journal and CURRENT"),
    }
}
