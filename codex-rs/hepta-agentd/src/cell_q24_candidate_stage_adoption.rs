//! Positive S/version bindings consume only the original unbound channels.
//! Saved opaque results are comparison pins. Each operation first completes a
//! new Model/E read, then calls the original Version/S owners without holding
//! that Model host or any native Training lane across their network I/O.

use std::sync::Arc;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;
use codex_hepta_types::AuthorityPosture;

use super::Error;
use super::Origin;
use super::OriginalCandidateOperationEvidence;
use super::OriginalCellQ24CandidateStageOwnersV1 as Owners;
use super::operation::CandidateOriginalOperation;
use super::super::auth;
use crate::OriginalCellQ24ModelCommandReceiptV1;
use crate::OriginalCellQ24ModelReadCompletionV1;
use crate::OriginalCircuitCandidateCompletionReadinessClientV1;
use crate::OriginalCircuitCandidateLearningReadContextV1;
use crate::OriginalCircuitCandidateNextUseCommandClientV1;
use crate::OriginalCircuitCandidateNextUseCommandReceiptV1;
use crate::OriginalCircuitModelPublicationContextV1;
use crate::OriginalCircuitModelSelectionCommandClientV1;
use crate::OriginalCircuitModelSelectionCommandReceiptV1;
use crate::OriginalCircuitModelVersionClientV1;
use crate::OriginalCircuitModelVersionPublicationV1;
use crate::RootResidentLearningEffectGateV3;

#[path = "cell_q24_candidate_stage_next_use.rs"]
mod next_use;

#[derive(Default)]
pub(super) struct AdoptionLane {
    model: Option<OriginalCellQ24ModelCommandReceiptV1>,
    selector: Option<Arc<OriginalCircuitModelSelectionCommandClientV1>>,
    version: Option<Arc<OriginalCircuitModelVersionClientV1>>,
    observer: Option<Arc<OriginalCircuitCandidateNextUseCommandClientV1>>,
    readiness: Option<Arc<OriginalCircuitCandidateCompletionReadinessClientV1>>,
    selection: Option<OriginalCircuitModelSelectionCommandReceiptV1>,
    next_use: Option<OriginalCircuitCandidateNextUseCommandReceiptV1>,
    publication: Option<OriginalCircuitModelVersionPublicationV1>,
    failed: bool,
}

#[derive(Clone, Copy, Eq, PartialEq)]
pub(super) enum Action { Execute, Readback }

pub(super) fn model_cut(
    owners: &Owners,
    snapshot: &LearningIterationSnapshotV1,
) -> Result<LearningIterationSnapshotV1, Error> {
    owners.training_prefix(snapshot)?;
    if !(5..=7).contains(&snapshot.receipts.len()) {
        return Err(Error::WrongScope);
    }
    let mut cut = LearningIterationCoordinatorV1::from_snapshot(
        owners.common.material.initial.clone(),
    )?;
    for receipt in &snapshot.receipts[..5] {
        cut.record(receipt.clone(), receipt.observed_unix_seconds)?;
    }
    if cut.next_stage() != Some(Stage::Selection) {
        return Err(Error::WrongScope);
    }
    owners.common.material.scope.validate_snapshot(cut.snapshot())?;
    Ok(cut.snapshot().clone())
}

pub(super) fn publication_context(
    owners: &Owners,
    operation: &CandidateOriginalOperation<'_>,
    completed: &OriginalCellQ24ModelReadCompletionV1,
) -> Result<OriginalCircuitModelPublicationContextV1, Error> {
    operation.require_owner(owners)?;
    if completed.model().snapshot() != &model_cut(owners, &operation.supplied)? {
        return Err(Error::WrongScope);
    }
    OriginalCircuitModelPublicationContextV1::from_original_receipt(
        owners.common.material.clone(),
        owners.protocol.clone(),
        operation.dataset.clone(),
        operation.training.clone(),
        completed.material().original_evaluation().clone(),
        completed.model().clone(),
    ).map_err(|_| Error::WrongScope)
}

fn require_published_selection(
    publication: &OriginalCircuitModelVersionPublicationV1,
    selection: &OriginalCircuitModelSelectionCommandReceiptV1,
) -> Result<(), Error> {
    if publication.authority() != AuthorityPosture::DENY_ALL
        || !matches!(&selection.receipt().observation,
            LearningIterationObservationV1::Selection { candidate_bundle, selection_digest }
            if *candidate_bundle == publication.bundle_digest()
                && *selection_digest == publication.selection_digest())
        || publication.run_id() == &selection.snapshot().request.source_run_id
    {
        return Err(Error::CommitUncertain);
    }
    Ok(())
}

impl Owners {
    fn require_adoption_cut(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        stage: Stage,
        action: Action,
    ) -> Result<(), Error> {
        self.require_live_deadline()?;
        model_cut(self, snapshot)?;
        let expected = match (stage, action) {
            (Stage::Selection, Action::Execute) => 5,
            (Stage::Selection, Action::Readback) => 6,
            (Stage::NextUse, Action::Execute) => 6,
            (Stage::NextUse, Action::Readback) => 7,
            _ => return Err(Error::WrongScope),
        };
        if snapshot.receipts.len() != expected
            || action == Action::Execute && (
                self.common.origin != Origin::Fresh
                || LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?.next_stage()
                    != Some(stage)
            )
        {
            return Err(Error::WrongScope);
        }
        Ok(())
    }

    fn begin_adoption(&self) -> Result<(), Error> {
        let mut lane = self.adoption.try_lock().map_err(|_| Error::QueueFull)?;
        if lane.failed { return Err(Error::CommitUncertain); }
        // No error or dropped future clears this bit. The independent
        // Candidate operation also remains fenced until Root consumes it.
        lane.failed = true;
        Ok(())
    }

    fn bind_adoption_selection(
        &self,
        operation: &CandidateOriginalOperation<'_>,
        completed: &OriginalCellQ24ModelReadCompletionV1,
        readback_only: bool,
    ) -> Result<(Arc<OriginalCircuitModelSelectionCommandClientV1>,
                 Arc<OriginalCircuitModelVersionClientV1>), Error> {
        let publication = publication_context(self, operation, completed)?;
        let context = OriginalCircuitCandidateLearningReadContextV1::from_original_model(
            publication,
        ).map_err(|_| Error::WrongScope)?;
        let mut lane = self.adoption.try_lock().map_err(|_| Error::QueueFull)?;
        if lane.model.as_ref().is_some_and(|saved| saved != completed.model()) {
            return Err(Error::CommitUncertain);
        }
        if lane.selector.is_none() && lane.version.is_none() {
            let mut common = self.common.continuation.try_lock().map_err(|_| Error::QueueFull)?;
            let (selector, version) = common.take_candidate_selection_channels(
                &operation.dataset, &operation.training,
            )?;
            // Both are the original peer objects. Late binding never creates
            // a descriptor, resets a peer deadline, or reuses a NoUpdate client.
            let selector = OriginalCircuitModelSelectionCommandClientV1::bind_original_stage_channel(
                selector, context.clone(), readback_only, None,
            ).map_err(|_| Error::CommitUncertain)?;
            let version = if readback_only {
                OriginalCircuitModelVersionClientV1::recover_original_stage_channel(version, context)
            } else {
                OriginalCircuitModelVersionClientV1::bind_original_stage_channel(version, context)
            }.map_err(|_| Error::CommitUncertain)?;
            lane.selector = Some(Arc::new(selector));
            lane.version = Some(Arc::new(version));
            lane.model = Some(completed.model().clone());
        }
        Ok((
            Arc::clone(lane.selector.as_ref().ok_or(Error::CommitUncertain)?),
            Arc::clone(lane.version.as_ref().ok_or(Error::CommitUncertain)?),
        ))
    }

    async fn require_adoption_effect(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), Error> {
        self.require_live_deadline()?;
        let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
        RootResidentLearningEffectGateV3::require_current(
            gate, snapshot, &self.common.material.scope,
        ).await
    }

    pub(super) async fn original_selection(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        action: Action,
    ) -> Result<OriginalCandidateOperationEvidence<'_>, Error> {
        self.require_adoption_cut(snapshot, Stage::Selection, action)?;
        let operation = CandidateOriginalOperation::begin(self, snapshot).await?;
        self.begin_adoption()?;
        let completed: OriginalCellQ24ModelReadCompletionV1 =
            self.read_model_for_adoption(&operation).await?;
        let context: OriginalCircuitModelPublicationContextV1 =
            publication_context(self, &operation, &completed)?;
        let (selector, version) = self.bind_adoption_selection(
            &operation, &completed,
            self.common.origin == Origin::Recovered || action == Action::Readback,
        )?;
        context.authenticate_material(completed.material(), auth::now()?, false)
            .map_err(|_| Error::CommitUncertain)?;
        let published = match action {
            Action::Execute => {
                self.require_adoption_effect(snapshot).await?;
                let gate = self.common.root.as_ref().ok_or(Error::CommitUncertain)?;
                let cancellation = RootResidentLearningEffectGateV3::training_cancellation(gate);
                let result = OriginalCircuitModelVersionClientV1::publish_original_version(
                    version.as_ref(), cancellation,
                ).await;
                self.require_adoption_effect(snapshot).await
                    .map_err(|_| Error::CommitUncertain)?;
                result.map_err(|_| Error::CommitUncertain)?
            }
            Action::Readback => OriginalCircuitModelVersionClientV1::readback(version.as_ref())
                .await.map_err(|_| Error::CommitUncertain)?,
        };
        let publication = published.publication().ok_or(Error::OwnerUnavailable(
            "original changed version has no completed FinalUse publication",
        ))?;
        if published.authority() != AuthorityPosture::DENY_ALL
            || publication.authority() != AuthorityPosture::DENY_ALL
        {
            return Err(Error::CommitUncertain);
        }
        {
            let mut lane = self.adoption.try_lock().map_err(|_| Error::QueueFull)?;
            if lane.publication.as_ref().is_some_and(|saved| saved != publication) {
                return Err(Error::CommitUncertain);
            }
            lane.publication = Some(publication.clone());
        }
        context.authenticate_material(completed.material(), auth::now()?, action == Action::Execute)
            .map_err(|_| Error::CommitUncertain)?;
        let original = match action {
            Action::Execute => {
                self.require_adoption_effect(snapshot).await
                    .map_err(|_| Error::CommitUncertain)?;
                let result = OriginalCircuitModelSelectionCommandClientV1::execute_selection(
                    selector.as_ref(),
                ).await;
                self.require_adoption_effect(snapshot).await
                    .map_err(|_| Error::CommitUncertain)?;
                result.map_err(|_| Error::CommitUncertain)?
            }
            Action::Readback => OriginalCircuitModelSelectionCommandClientV1::readback(
                selector.as_ref(),
            ).await.map_err(|_| Error::CommitUncertain)?,
        };
        let closed = CandidateOriginalOperation::close(operation).await
            .map_err(|_| Error::CommitUncertain)?;
        require_published_selection(publication, &original)?;
        let evidence = closed.selection(completed, original.clone(), publication.clone())
            .map_err(|_| Error::CommitUncertain)?;
        self.require_live_deadline().map_err(|_| Error::CommitUncertain)?;
        let mut lane = self.adoption.try_lock().map_err(|_| Error::CommitUncertain)?;
        if lane.selection.as_ref().is_some_and(|saved| saved != &original) {
            return Err(Error::CommitUncertain);
        }
        lane.selection = Some(original);
        lane.failed = false;
        Ok(evidence)
    }
}
