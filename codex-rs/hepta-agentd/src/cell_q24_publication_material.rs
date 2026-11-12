//! Read the original B manifest under the existing aggregate lane. The result
//! is material data only and cannot replace its original live publication owners.

use codex_hepta_learning_artifacts::LearningLocalDispositionV2;
use codex_hepta_neuron::CellBackendManifestV2;

use super::*;

impl OriginalCellQ24LearningStageOwnersV1 {
    pub(crate) async fn original_publication_manifest(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<CellBackendManifestV2, Error> {
        self.inner.require_snapshot(snapshot)?;
        if !matches!(snapshot.receipts.last().map(|receipt| &receipt.observation),
            Some(LearningIterationObservationV1::LocalDecisionV2(decision))
                if decision.disposition == LearningLocalDispositionV2::AdoptCandidate)
        {
            return Err(Error::WrongScope);
        }
        let inner = Arc::clone(&self.inner);
        let snapshot = snapshot.clone();
        self.inner
            .in_lane(move |owners, training, runtime| {
                for receipt in &snapshot.receipts {
                    owners.require_receipt(&inner, training, runtime, &snapshot, receipt)?;
                }
                owners.original_evaluation_manifest(&inner, training, &snapshot)
            })
            .await
    }

    /// Execute the actual embedded-host operation under the same original
    /// owner lane. Dropping this future engages that lane's permanent fence;
    /// no independent blocking task can outlive it as an unfenced publisher.
    pub(crate) async fn with_original_publication<T: Send + 'static>(
        &self,
        snapshot: LearningIterationSnapshotV1,
        manifest: Option<CellBackendManifestV2>,
        work: impl FnOnce() -> Result<T, crate::OriginalCellQ24PublicationErrorV1> + Send + 'static,
    ) -> Result<T, crate::OriginalCellQ24PublicationErrorV1> {
        self.inner.require_snapshot(&snapshot)?;
        let adopts = matches!(snapshot.receipts.last().map(|receipt| &receipt.observation),
            Some(LearningIterationObservationV1::LocalDecisionV2(decision))
                if decision.disposition == LearningLocalDispositionV2::AdoptCandidate);
        let coordinator =
            LearningIterationCoordinatorV1::from_snapshot(snapshot.clone()).map_err(Error::from)?;
        let changed = coordinator
            .next_task_bundle()
            .is_some_and(|bundle| bundle != &snapshot.request.selected_bundle);
        if adopts != changed || adopts != manifest.is_some() {
            return Err(Error::WrongScope.into());
        }
        let inner = Arc::clone(&self.inner);
        let started = Arc::new(AtomicBool::new(/*val*/ false));
        let effect_started = Arc::clone(&started);
        let result = self
            .inner
            .in_lane(move |owners, training, runtime| {
                for receipt in &snapshot.receipts {
                    owners.require_receipt(&inner, training, runtime, &snapshot, receipt)?;
                }
                if let Some(expected) = &manifest
                    && &owners.original_evaluation_manifest(&inner, training, &snapshot)?
                        != expected
                {
                    return Err(Error::WrongScope);
                }
                if inner.cancelled.load(Ordering::Acquire) {
                    return Err(Error::CommitUncertain);
                }
                effect_started.store(true, Ordering::Release);
                let value = work();
                for receipt in &snapshot.receipts {
                    owners.require_receipt(&inner, training, runtime, &snapshot, receipt)?;
                }
                if let Some(expected) = &manifest
                    && &owners.original_evaluation_manifest(&inner, training, &snapshot)?
                        != expected
                {
                    return Err(Error::WrongScope);
                }
                Ok(value)
            })
            .await;
        match result {
            Ok(value) => value,
            Err(_) if started.load(Ordering::Acquire) => {
                Err(crate::OriginalCellQ24PublicationErrorV1::CommitUncertain)
            }
            Err(error) => Err(error.into()),
        }
    }
}
