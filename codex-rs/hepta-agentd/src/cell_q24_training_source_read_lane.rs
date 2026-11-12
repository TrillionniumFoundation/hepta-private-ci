//! The actual native/Generator read stays inside one occupied original lane.
//! Effects use the unchanged in_lane/in_model_lane paths. This closed helper
//! is reached only by original completion and Candidate material readback.

use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;

use super::Error;
use super::OriginalCellQ24TrainingCompletionV1;
use super::OriginalCellQ24TrainingStageV1;
use crate::CellQ24TrainingOwnerV1;

enum SourceRequirement {
    IfCaptured,
    Required,
}

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingStageV1<TW, RW>
{
    pub(super) async fn read_original_source_completion(
        &self,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        let permit = Arc::clone(&self.lane)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let owners = Arc::clone(&self.owners);
        tokio::task::spawn_blocking(move || {
            let mut owners = owners.try_lock().map_err(|_| Error::CommitUncertain)?;
            let (_, original) = owners.read_source_transaction(
                &permit,
                SourceRequirement::IfCaptured,
                |_, _| Ok(()),
            )?;
            Ok(original)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    pub(super) fn read_original_source_candidate(
        &self,
    ) -> Result<crate::OriginalCellQ24CandidateMaterialV1, Error> {
        let permit = Arc::clone(&self.lane)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let mut owners = self.owners.try_lock().map_err(|_| Error::CommitUncertain)?;
        let (material, _) = owners.read_source_transaction(
            &permit,
            SourceRequirement::Required,
            |training, completed| {
                let candidate = match CellQ24TrainingOwnerV1::readback(training)? {
                    crate::CellQ24TrainingOutcomeV1::Candidate(candidate) => *candidate,
                    crate::CellQ24TrainingOutcomeV1::NoUpdate { .. } => {
                        return Err(
                            crate::OriginalCellQ24CandidateMaterialErrorV1::NoCandidate.into()
                        );
                    }
                };
                Ok(
                    crate::OriginalCellQ24CandidateMaterialV1::from_original_candidate(
                        &self.dataset,
                        candidate,
                        completed.receipt.clone(),
                        completed.attestation.clone(),
                    )?,
                )
            },
        )?;
        Ok(material)
    }
}

impl<TW: AnchorWitnessStore, RW: AnchorWitnessStore> super::Owners<TW, RW> {
    fn read_source_transaction<T>(
        &mut self,
        permit: &tokio::sync::OwnedSemaphorePermit,
        requirement: SourceRequirement,
        read: impl FnOnce(
            &mut CellQ24TrainingOwnerV1<TW>,
            &OriginalCellQ24TrainingCompletionV1,
        ) -> Result<T, Error>,
    ) -> Result<(T, OriginalCellQ24TrainingCompletionV1), Error> {
        if self.source_fenced {
            return Err(Error::CommitUncertain);
        }
        {
            let super::Owners {
                training, receipts, ..
            } = self;
            let training: &mut CellQ24TrainingOwnerV1<TW> = training;
            training
                .require_original_dataset_scope(&receipts.config.dataset, &receipts.config.scope)?;
        }
        let before =
            CellQ24TrainingOwnerV1::begin_original_source_read(&mut self.training, permit)?;
        if before.is_none() {
            match requirement {
                SourceRequirement::Required => {
                    // Keep the old legacy error precedence and original
                    // native fence. Missing/Pending returns before admission;
                    // an existing completion is never a captured Candidate.
                    let original = self.read_original_completion()?;
                    let refused = match CellQ24TrainingOwnerV1::require_original_source_capture(
                        &mut self.training,
                    ) {
                        Err(error) => error,
                        Ok(()) => return Err(Error::CommitUncertain),
                    };
                    let current = self
                        .read_original_completion()
                        .map_err(|_| Error::CommitUncertain)?;
                    if current.receipt != original.receipt
                        || current.attestation != original.attestation
                    {
                        return Err(Error::CommitUncertain);
                    }
                    return Err(refused.into());
                }
                SourceRequirement::IfCaptured => {
                    let original = self.read_original_completion()?;
                    let result = read(&mut self.training, &original)?;
                    return Ok((result, original));
                }
            }
        }
        let result = self.read_original_completion().and_then(|original| {
            read(&mut self.training, &original).map(|value| (value, original))
        });
        // Dropping an async requester cannot release this blocking operation's
        // permit. A tail failure cannot restore its original transport channel.
        let after = CellQ24TrainingOwnerV1::finish_original_source_read(&mut self.training, before)
            .map_err(|_| {
                self.source_fenced = true;
                Error::CommitUncertain
            })?;
        let current = match &result {
            Ok((_, original)) => {
                let current = self.read_original_completion().map_err(|_| {
                    self.source_fenced = true;
                    Error::CommitUncertain
                })?;
                if current.receipt != original.receipt
                    || current.attestation != original.attestation
                {
                    self.source_fenced = true;
                    return Err(Error::CommitUncertain);
                }
                Some(current)
            }
            Err(_) => {
                // Preserve the original Missing/Pending read semantics while
                // still completing the real Source and physical tail checks.
                self.require_captured_tail_current().map_err(|_| {
                    self.source_fenced = true;
                    Error::CommitUncertain
                })?;
                None
            }
        };
        // The last original file/witness read precedes final fresh Observer
        // and Generator checks; neither check performs another external read.
        CellQ24TrainingOwnerV1::authenticate_original_source_read(&mut self.training, after)
            .map_err(|_| {
                self.source_fenced = true;
                Error::CommitUncertain
            })?;
        if let Some(current) = current
            && self.require_retained_attestation_current(&current).is_err()
        {
            self.source_fenced = true;
            return Err(Error::CommitUncertain);
        }
        result
    }
}
