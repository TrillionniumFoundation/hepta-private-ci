//! Actual C readiness is a read, never permission to execute the C task.
//! The original Observer command attests completion only after Ready. Recovered
//! requests use its readonly command; no execution bit or endpoint is recreated.

use std::sync::Arc;
use std::time::Duration;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;

use super::Action;
use super::Error;
use super::Origin;
use super::Owners;
use super::auth;
use super::publication_context;
use super::require_published_selection;
use super::OriginalCircuitModelVersionClientV1;
use super::OriginalCircuitModelVersionPublicationV1;
use super::CandidateOriginalOperation;
use super::OriginalCandidateOperationEvidence;
use super::OriginalCellQ24ModelReadCompletionV1;
use super::OriginalCircuitCandidateCompletionReadinessClientV1;
use super::OriginalCircuitCandidateNextUseCommandClientV1;
use super::OriginalCircuitModelPublicationContextV1;
use super::OriginalCircuitModelSelectionCommandClientV1;
use super::OriginalCircuitModelSelectionCommandReceiptV1;
use crate::OriginalCircuitCandidateLearningReadbackV1;

impl Owners {
    async fn bind_adoption_next_use(
        &self,
        operation: &CandidateOriginalOperation<'_>,
        completed: &OriginalCellQ24ModelReadCompletionV1,
        action: Action,
    ) -> Result<(
        Arc<OriginalCircuitCandidateNextUseCommandClientV1>,
        Arc<OriginalCircuitCandidateCompletionReadinessClientV1>,
        OriginalCircuitModelSelectionCommandReceiptV1,
        OriginalCircuitModelVersionPublicationV1,
    ), Error> {
        let existing = {
            let lane = self.adoption.try_lock().map_err(|_| Error::QueueFull)?;
            if lane.model.as_ref().is_some_and(|saved| saved != completed.model()) {
                return Err(Error::CommitUncertain);
            }
            match (&lane.observer, &lane.readiness, &lane.selection, &lane.publication) {
                (Some(observer), Some(readiness), Some(selection), Some(publication)) => Some((
                    Arc::clone(observer), Arc::clone(readiness), selection.clone(), publication.clone(),
                )),
                (None, None, _, _) => None,
                _ => return Err(Error::CommitUncertain),
            }
        };
        if let Some(existing) = existing {
            // This is only the original C binding/comparison pin. The caller
            // still sends a new C command, whose owner rereads original S/T.
            return Ok(existing);
        }
        let (selector, version) = self.bind_adoption_selection(operation, completed, true)?;
        let saved = {
            let lane = self.adoption.try_lock().map_err(|_| Error::QueueFull)?;
            lane.publication.clone()
        };
        let publication = match saved {
            Some(pin) => pin,
            None => {
                // A cold readonly assembly learns this pin through the
                // original Version owner, never from a supplied S/C tuple.
                let current = OriginalCircuitModelVersionClientV1::readback(version.as_ref())
                    .await.map_err(|_| Error::CommitUncertain)?;
                current.publication().ok_or(Error::CommitUncertain)?.clone()
            }
        };
        let selection = OriginalCircuitModelSelectionCommandClientV1::readback(selector.as_ref())
            .await.map_err(|_| Error::CommitUncertain)?;
        let mut expected = LearningIterationCoordinatorV1::from_snapshot(
            completed.model().snapshot().clone(),
        )?;
        expected.record(selection.receipt().clone(), selection.receipt().observed_unix_seconds)?;
        if selection.model() != completed.model()
            || selection.snapshot() != expected.snapshot()
            || operation.supplied.receipts.get(..6) != Some(selection.snapshot().receipts.as_slice())
        {
            return Err(Error::CommitUncertain);
        }
        require_published_selection(&publication, &selection)?;
        let (observer, readiness) = {
            let mut common = self.common.continuation.try_lock().map_err(|_| Error::QueueFull)?;
            common.take_candidate_next_use_channels(&operation.dataset, &operation.training)?
        };
        let origin = if action == Action::Readback { Origin::Recovered } else { self.common.origin };
        let observer = OriginalCircuitCandidateNextUseCommandClientV1::bind_original_stage_channel(
            observer, &self.common.material, &operation.dataset, &selection, origin,
        ).map_err(|_| Error::CommitUncertain)?;
        let readiness = OriginalCircuitCandidateCompletionReadinessClientV1::bind_original_stage_channel(
            readiness, &self.common.material, &operation.dataset, &selection,
        ).map_err(|_| Error::CommitUncertain)?;
        let mut lane = self.adoption.try_lock().map_err(|_| Error::QueueFull)?;
        if lane.observer.is_some() || lane.readiness.is_some()
            || lane.selection.as_ref().is_some_and(|saved| saved != &selection)
        {
            return Err(Error::CommitUncertain);
        }
        if lane.publication.as_ref().is_some_and(|saved| saved != &publication) {
            return Err(Error::CommitUncertain);
        }
        lane.publication = Some(publication.clone());
        lane.selection = Some(selection.clone());
        lane.observer = Some(Arc::new(observer));
        lane.readiness = Some(Arc::new(readiness));
        Ok((
            Arc::clone(lane.observer.as_ref().ok_or(Error::CommitUncertain)?),
            Arc::clone(lane.readiness.as_ref().ok_or(Error::CommitUncertain)?),
            selection,
            publication,
        ))
    }

    async fn await_original_candidate_c(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        readiness: &OriginalCircuitCandidateCompletionReadinessClientV1,
        context: &OriginalCircuitModelPublicationContextV1,
        completed: &OriginalCellQ24ModelReadCompletionV1,
    ) -> Result<OriginalCircuitCandidateLearningReadbackV1, Error> {
        // Reserve one request on this original 128-frame purpose for the
        // final independent Root read. No channel is restarted on exhaustion.
        for _ in 0..127 {
            self.require_adoption_effect(snapshot).await?;
            let actual = OriginalCircuitCandidateCompletionReadinessClientV1::read_current(readiness)
                .await.map_err(|_| Error::CommitUncertain)?;
            context.authenticate_material(completed.material(), auth::now()?, true)
                .map_err(|_| Error::CommitUncertain)?;
            self.require_live_deadline()?;
            if let Some(ready) = actual {
                return Ok(ready);
            }
            // Same original purpose and absolute lifetime. None cannot create
            // or retry C execution; the independently authorized Version host
            // owns that task. The outer Root cancellation drops this future.
            tokio::time::sleep(Duration::from_secs(2)).await;
        }
        Err(Error::OwnerUnavailable("original positive C readiness frame budget"))
    }

    pub(in super::super) async fn original_next_use(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        action: Action,
    ) -> Result<OriginalCandidateOperationEvidence<'_>, Error> {
        self.require_adoption_cut(snapshot, Stage::NextUse, action)?;
        let operation = CandidateOriginalOperation::begin(self, snapshot).await?;
        self.begin_adoption()?;
        let completed: OriginalCellQ24ModelReadCompletionV1 =
            self.read_model_for_adoption(&operation).await?;
        let context: OriginalCircuitModelPublicationContextV1 =
            publication_context(self, &operation, &completed)?;
        let (observer, readiness, selection, publication) = self.bind_adoption_next_use(
            &operation, &completed, action,
        ).await?;
        context.authenticate_material(completed.material(), auth::now()?, false)
            .map_err(|_| Error::CommitUncertain)?;
        let ready = match action {
            Action::Execute => self.await_original_candidate_c(
                snapshot, readiness.as_ref(), &context, &completed,
            ).await?,
            Action::Readback => OriginalCircuitCandidateCompletionReadinessClientV1::read_current(
                readiness.as_ref(),
            ).await.map_err(|_| Error::CommitUncertain)?.ok_or(Error::CommitUncertain)?,
        };
        if ready.publication_digest() != publication.publication_digest()
            || ready.source_input_digest() != publication.task_digest()
            || ready.source_publication_digest().is_none()
        {
            return Err(Error::CommitUncertain);
        }
        let original = match action {
            Action::Execute => {
                self.require_adoption_effect(snapshot).await?;
                let result = OriginalCircuitCandidateNextUseCommandClientV1::attest_completed_task(
                    observer.as_ref(),
                ).await;
                self.require_adoption_effect(snapshot).await
                    .map_err(|_| Error::CommitUncertain)?;
                result.map_err(|_| Error::CommitUncertain)?
            }
            Action::Readback => OriginalCircuitCandidateNextUseCommandClientV1::readback(
                observer.as_ref(),
            ).await.map_err(|_| Error::CommitUncertain)?,
        };
        if ready.observation() != &original.receipt().observation {
            return Err(Error::CommitUncertain);
        }
        let closed = CandidateOriginalOperation::close(operation).await
            .map_err(|_| Error::CommitUncertain)?;
        let evidence = closed.next_use(completed, selection, original.clone(), publication, ready)
            .map_err(|_| Error::CommitUncertain)?;
        self.require_live_deadline().map_err(|_| Error::CommitUncertain)?;
        let mut lane = self.adoption.try_lock().map_err(|_| Error::CommitUncertain)?;
        if lane.next_use.as_ref().is_some_and(|saved| saved != &original) {
            return Err(Error::CommitUncertain);
        }
        lane.next_use = Some(original);
        lane.failed = false;
        Ok(evidence)
    }
}
