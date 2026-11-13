//! Fixed-purpose local reads of the original published Version.
//! The binding is constructed only here from the same retained owners. It
//! holds one original Version permit; readiness does not open another lane.

use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_neuron::FileAnchorWitnessStore;
use tokio::sync::OwnedSemaphorePermit;

use super::super::super::context::PublicationAccess;
use super::super::Error;
use super::super::RetainedVersionOriginV1;
use super::super::RetainedVersionPurposeV1;
use super::next_use_readback::NextUseReadPurpose;
use super::OriginalCircuitRetainedVersionHostV1;
use super::RetainedVersionFinalUseOutcomeV1;
use crate::OriginalCircuitEvaluatedLearningReadContextV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::OriginalCircuitPublishedLocalReadV1;

type OriginalLocalReader =
    OriginalCircuitLearningReadOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

#[derive(Clone, Copy)]
pub(crate) enum OriginalVersionLocalReadOperationV1 {
    Readback,
    CompletionReadiness,
}

enum OriginalVersionLocalReadPurpose {
    Selection,
    NextUse(OriginalCircuitEvaluatedSelectionReceiptV1),
}

/// Crate-private transport binding, with no public constructor or owner
/// access. The same concrete Version remains responsible for every response.
pub(crate) struct OriginalVersionLocalReadBindingV1 {
    version: Arc<OriginalCircuitRetainedVersionHostV1>,
    reader: Arc<OriginalLocalReader>,
    selection: Option<OriginalCircuitEvaluatedSelectionReceiptV1>,
    context: OriginalCircuitEvaluatedLearningReadContextV1,
    _permit: OwnedSemaphorePermit,
    timeout: Duration,
    end: Instant,
}

impl OriginalVersionLocalReadBindingV1 {
    pub(crate) fn original_context(&self) -> OriginalCircuitEvaluatedLearningReadContextV1 {
        self.context.clone()
    }

    pub(crate) fn original_end(&self) -> Instant {
        self.end
    }

    pub(crate) fn original_timeout(&self) -> Duration {
        self.timeout
    }

    pub(crate) fn require_original_shared_readbacks(
        &self,
        shared: &crate::OriginalCircuitPublishedEvidenceReadbackV1,
    ) -> Result<(), Error> {
        self.version.require_lifetime()?;
        if Instant::now() >= self.end
            || self.version.purpose != RetainedVersionPurposeV1::EvaluatedNoUpdate
            || self.version.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published
        {
            return Err(Error::ReadbackRequired);
        }
        let state = self.version.state.try_lock().map_err(|_| Error::Busy)?;
        let cut = state.cut.as_ref().ok_or(Error::Unavailable)?;
        let evaluated = cut.evaluated.as_ref().ok_or(Error::ReadbackRequired)?;
        let held = state.shared_evaluated.as_ref().ok_or(Error::ReadbackRequired)?;
        crate::OriginalCircuitPublishedEvidenceReadbackV1::require_original_context(
            held, evaluated,
        )?;
        crate::OriginalCircuitPublishedEvidenceReadbackV1::require_original_context(
            shared, evaluated,
        )?;
        let (held_trainer, held_evaluator) =
            crate::OriginalCircuitPublishedEvidenceReadbackV1::original_clients(held);
        let (given_trainer, given_evaluator) =
            crate::OriginalCircuitPublishedEvidenceReadbackV1::original_clients(shared);
        if !std::ptr::eq(held_trainer, given_trainer)
            || !std::ptr::eq(held_evaluator, given_evaluator)
        {
            return Err(Error::Binding("same Version local T/E readback owners"));
        }
        cut.require_fresh(super::super::now()?, PublicationAccess::Readback)?;
        self.version.require_lifetime()?;
        if Instant::now() >= self.end
            || self.version.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published
        {
            return Err(Error::ReadbackRequired);
        }
        Ok(())
    }

    pub(crate) fn respond(
        &self,
        operation: OriginalVersionLocalReadOperationV1,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        if Instant::now() >= self.end || !(1..=128).contains(&request_id) {
            return Err(Error::Unavailable);
        }
        let response = match &self.selection {
            Some(selection) => OriginalCircuitRetainedVersionHostV1::original_evaluated_next_use_response(
                &self.version,
                selection,
                self.reader.as_ref(),
                match operation {
                    OriginalVersionLocalReadOperationV1::Readback => &NextUseReadPurpose::Readback,
                    OriginalVersionLocalReadOperationV1::CompletionReadiness =>
                        &NextUseReadPurpose::CompletionReadiness,
                },
                bytes,
                request_id,
            )?,
            None => {
                if matches!(operation, OriginalVersionLocalReadOperationV1::CompletionReadiness) {
                    return Err(Error::Binding("local Selection is not completion readiness"));
                }
                self.version.original_evaluated_local_selection_response(
                    self.reader.as_ref(), bytes, request_id,
                )?
            }
        };
        if Instant::now() >= self.end {
            return Err(Error::Unavailable);
        }
        Ok(response)
    }
}

impl OriginalCircuitRetainedVersionHostV1 {
    /// A four-cut local Selection reader. It can only read the same actual
    /// publication; it cannot publish, start C, or issue an S receipt.
    pub async fn open_original_evaluated_selection_local_read(
        self: Arc<Self>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<OriginalCircuitPublishedLocalReadV1, Error> {
        self.open_original_evaluated_local_read(OriginalVersionLocalReadPurpose::Selection, timeout, lifetime).await
    }

    /// A five-cut reader fixed by the original opaque S. Its readback and
    /// readiness aliases share this one permit, request budget and deadline.
    pub async fn open_original_evaluated_next_use_local_read(
        self: Arc<Self>,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<OriginalCircuitPublishedLocalReadV1, Error> {
        self.open_original_evaluated_local_read(OriginalVersionLocalReadPurpose::NextUse(selection), timeout, lifetime).await
    }

    async fn open_original_evaluated_local_read(
        self: Arc<Self>,
        purpose: OriginalVersionLocalReadPurpose,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<OriginalCircuitPublishedLocalReadV1, Error> {
        if timeout.is_zero()
            || timeout > Duration::from_millis(500)
            || lifetime.is_zero()
            || lifetime > Duration::from_secs(300)
        {
            return Err(Error::Binding("bounded original local Version read"));
        }
        let started = Instant::now();
        let end = started.checked_add(lifetime).ok_or(Error::Clock)?.min(self.end);
        let admission_end = started.checked_add(timeout).ok_or(Error::Clock)?.min(end);
        self.require_lifetime()?;
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let worker = tokio::task::spawn_blocking(move || {
            self.bind_original_evaluated_local_read(purpose, timeout, end, permit)
        });
        let bound = tokio::time::timeout_at(
            tokio::time::Instant::from_std(admission_end), worker,
        )
        .await
        .map_err(|_| Error::Unavailable)?
        .map_err(|_| Error::CommitUncertain)??;
        if Instant::now() >= admission_end {
            return Err(Error::Unavailable);
        }
        let local = OriginalCircuitPublishedLocalReadV1::from_original_version(bound)
            .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        if Instant::now() >= admission_end {
            return Err(Error::Unavailable);
        }
        Ok(local)
    }

    fn bind_original_evaluated_local_read(
        self: Arc<Self>,
        purpose: OriginalVersionLocalReadPurpose,
        timeout: Duration,
        end: Instant,
        permit: OwnedSemaphorePermit,
    ) -> Result<OriginalVersionLocalReadBindingV1, Error> {
        self.require_lifetime()?;
        if Instant::now() >= end
            || self.purpose != RetainedVersionPurposeV1::EvaluatedNoUpdate
            || self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published
        {
            return Err(Error::ReadbackRequired);
        }
        let selection = match purpose {
            OriginalVersionLocalReadPurpose::Selection => None,
            OriginalVersionLocalReadPurpose::NextUse(selection) => Some(selection),
        };
        let (reader, context) = match &selection {
            Some(selection) => {
                let reader = self.build_original_evaluated_next_use_reader(selection.clone())?;
                let context = OriginalCircuitEvaluatedLearningReadContextV1::for_original_next_use(
                    selection.clone(),
                )
                .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
                (Arc::new(reader), context)
            }
            None => {
                let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
                if let Err(error) = self.bind_original_predecessor(&mut state) {
                    if self.origin == RetainedVersionOriginV1::Recovered {
                        state.selection_reader = None;
                    }
                    return Err(error);
                }
                let before = if self.origin == RetainedVersionOriginV1::Recovered {
                    self.read_original_recovery(&mut state)?
                } else {
                    self.read_original(&state)?
                };
                if before.publication().is_none() {
                    return Err(Error::ReadbackRequired);
                }
                let cut = state.cut.as_ref().ok_or(Error::Unavailable)?;
                let evaluated = cut.evaluated.as_ref().ok_or(Error::ReadbackRequired)?;
                let context = OriginalCircuitEvaluatedLearningReadContextV1::for_original_selection(
                    evaluated.clone_for_original_receipt(),
                )
                .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
                let reader = Arc::clone(
                    state.selection_reader.as_ref().ok_or(Error::ReadbackRequired)?,
                );
                let after = self.read_original(&state)?;
                if before != after || after.publication().is_none() {
                    return Err(Error::CommitUncertain);
                }
                cut.require_fresh(super::super::now()?, PublicationAccess::Readback)?;
                (reader, context)
            }
        };
        self.require_lifetime()?;
        if Instant::now() >= end
            || self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published
        {
            return Err(Error::ReadbackRequired);
        }
        Ok(OriginalVersionLocalReadBindingV1 {
            version: self,
            reader,
            selection,
            context,
            _permit: permit,
            timeout,
            end,
        })
    }

    fn original_evaluated_local_selection_response(
        &self,
        reader: &OriginalLocalReader,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        self.require_lifetime()?;
        if self.purpose != RetainedVersionPurposeV1::EvaluatedNoUpdate
            || self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published
        {
            return Err(Error::ReadbackRequired);
        }
        let state = self.state.try_lock().map_err(|_| Error::Busy)?;
        let before = self.read_original(&state)?;
        if before.publication().is_none() {
            return Err(Error::ReadbackRequired);
        }
        let cut = state.cut.as_ref().ok_or(Error::Unavailable)?;
        let evaluated = cut.evaluated.as_ref().ok_or(Error::ReadbackRequired)?;
        cut.require_fresh(super::super::now()?, PublicationAccess::Readback)?;
        let response =
            OriginalCircuitLearningReadOwnerV1::original_evaluated_selection_response(
                reader, evaluated, bytes, request_id,
            )
            .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        let after = self.read_original(&state)?;
        if before != after || after.publication().is_none() {
            return Err(Error::CommitUncertain);
        }
        cut.require_fresh(super::super::now()?, PublicationAccess::Readback)?;
        self.require_lifetime()?;
        if self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published {
            return Err(Error::ReadbackRequired);
        }
        Ok(response)
    }
}
