//! Read the original B manifest under the existing aggregate lane. The result
//! is material data only and cannot replace its original live publication owners.

use codex_hepta_learning_artifacts::LearningLocalDispositionV2;
use codex_hepta_neuron::CellBackendManifestV2;

use super::historical_operation::OriginalQ24StageOperationV1;
use super::*;

impl OriginalCellQ24LearningStageOwnersV1 {
    /// Authenticate the complete original decision and B material in one
    /// bounded operation. These returned bytes grant no publication authority.
    pub(crate) async fn read_original_publication_material(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<Option<CellBackendManifestV2>, Error> {
        self.inner.require_snapshot(snapshot)?;
        if !self.inner.has_original_root_evaluation()? {
            self.validate_recovery(snapshot).await?;
            let adopts = matches!(snapshot.receipts.last().map(|receipt| &receipt.observation),
                Some(LearningIterationObservationV1::LocalDecisionV2(decision))
                    if decision.disposition == LearningLocalDispositionV2::AdoptCandidate);
            let result = if adopts {
                Some(self.original_publication_manifest(snapshot).await?)
            } else {
                None
            };
            self.require_current().await?;
            return Ok(result);
        }
        let inner = Arc::clone(&self.inner);
        let snapshot = snapshot.clone();
        self.inner
            .in_original_prepared_lane(move |owners, runtime, read| {
                inner.training.with_original_training_operation(
                    &inner.dataset_cut,
                    read,
                    |training| {
                        let mut operation =
                            OriginalQ24StageOperationV1::from_original_receipt_read(
                                &inner, owners, runtime, training, read,
                            )?;
                        let result = operation.read_publication_material(&snapshot);
                        operation.finish_original_b_read()?;
                        result
                    },
                )
            })
            .await
    }

    pub(crate) async fn require_original_publication_material(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        expected: &Option<CellBackendManifestV2>,
    ) -> Result<(), Error> {
        if &self.read_original_publication_material(snapshot).await? != expected {
            return Err(Error::WrongScope);
        }
        Ok(())
    }

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
                Q24StageOwners::original_evaluation_manifest(owners, &inner, training, &snapshot)
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
        if self.inner.has_original_root_evaluation()? {
            return self
                .with_original_root_publication(snapshot, manifest, work)
                .await;
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
                    && &Q24StageOwners::original_evaluation_manifest(
                        owners, &inner, training, &snapshot,
                    )? != expected
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
                    && &Q24StageOwners::original_evaluation_manifest(
                        owners, &inner, training, &snapshot,
                    )? != expected
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

    async fn with_original_root_publication<T: Send + 'static>(
        &self,
        snapshot: LearningIterationSnapshotV1,
        manifest: Option<CellBackendManifestV2>,
        work: impl FnOnce() -> Result<T, crate::OriginalCellQ24PublicationErrorV1> + Send + 'static,
    ) -> Result<T, crate::OriginalCellQ24PublicationErrorV1> {
        let inner = Arc::clone(&self.inner);
        let started = Arc::new(AtomicBool::new(false));
        let effect_started = Arc::clone(&started);
        let result = self
            .inner
            .in_original_prepared_lane(move |owners, runtime, read| {
                inner.training.with_original_training_operation(
                    &inner.dataset_cut,
                    read,
                    |training| {
                        let mut operation =
                            OriginalQ24StageOperationV1::from_original_receipt_read(
                                &inner, owners, runtime, training, read,
                            )?;
                        let result = (|| {
                            if operation.read_publication_material(&snapshot)? != manifest {
                                return Err(Error::WrongScope);
                            }
                            if inner.cancelled.load(Ordering::Acquire) {
                                return Err(Error::CommitUncertain);
                            }
                            effect_started.store(true, Ordering::Release);
                            let value = work();
                            if operation.read_publication_material(&snapshot)? != manifest {
                                return Err(Error::WrongScope);
                            }
                            Ok(value)
                        })();
                        operation.finish_original_b_read()?;
                        result
                    },
                )
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
