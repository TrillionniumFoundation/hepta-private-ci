//! The published Version serves C from the original owners it already holds.
//! An opaque original S fixes the five-cut read purpose. No task, writer,
//! signer, RunStart, owner getter or additional T/E connection is created.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::FileAnchorWitnessStore;
use tokio::sync::OwnedSemaphorePermit;

use super::super::super::context::PublicationAccess;
use super::super::Error;
use super::super::RetainedVersionOriginV1;
use super::super::RetainedVersionPurposeV1;
use super::OriginalCircuitRetainedVersionHostV1;
use super::RetainedVersionFinalUseOutcomeV1;
use super::RetainedVersionHostPhaseV1;
use crate::AgentdRootAuthorityPeer;
use crate::OriginalCircuitEvaluatedLearningReadContextV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

type OriginalNextUseReader =
    OriginalCircuitLearningReadOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

pub(super) enum NextUseReadPurpose {
    Readback,
    CompletionReadiness,
    #[cfg(test)]
    CompletionReadinessDeadlineProbe {
        end: Instant,
        cross_end_after_original_read: bool,
        response_observed: Arc<std::sync::atomic::AtomicBool>,
    },
}

impl OriginalCircuitRetainedVersionHostV1 {
    /// Serve the actual C observation to the original NextUse owner. S must
    /// already be an opaque original receipt for this Version's exact T/E cut.
    /// This entry cannot dispatch C or create its original completion evidence.
    pub async fn serve_original_evaluated_next_use_readback(
        self: Arc<Self>,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        self.serve_original_evaluated_next_use(
            selection,
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
            NextUseReadPurpose::Readback,
        )
        .await
    }

    /// A separate readonly readiness channel for the same actual C and S.
    /// Pending is unresolved. Only the existing daemon control may start C.
    pub async fn serve_original_evaluated_completion_readiness(
        self: Arc<Self>,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<u64, Error> {
        self.serve_original_evaluated_next_use(
            selection,
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
            NextUseReadPurpose::CompletionReadiness,
        )
        .await
    }

    async fn serve_original_evaluated_next_use(
        self: Arc<Self>,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
        stream: UnixStream,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
        purpose: NextUseReadPurpose,
    ) -> Result<u64, Error> {
        if timeout.is_zero()
            || timeout > Duration::from_millis(500)
            || lifetime.is_zero()
            || lifetime > Duration::from_secs(300)
        {
            return Err(Error::Binding("original Version NextUse read bounds"));
        }
        self.require_lifetime()?;
        let permit = Arc::clone(&self.connections)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let remaining = self
            .end
            .checked_duration_since(Instant::now())
            .ok_or(Error::Unavailable)?;
        let channel = original_owner_command_channel_v1(
            stream,
            consumer,
            consumer_uid,
            original_consumer_pidfd,
            timeout,
            lifetime.min(remaining),
        )?;
        self.serve_original_evaluated_next_use_channel(selection, channel, permit, purpose)
            .await
    }

    async fn serve_original_evaluated_next_use_channel(
        self: Arc<Self>,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
        mut channel: HostAuthorityPeerChannel,
        permit: OwnedSemaphorePermit,
        purpose: NextUseReadPurpose,
    ) -> Result<u64, Error> {
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            channel.check_peer_lifetime()?;
            let reader = self.build_original_evaluated_next_use_reader(selection.clone())?;
            self.require_lifetime()?;
            channel.check_peer_lifetime()?;
            self.serve_original_evaluated_next_use_loop(&selection, &reader, &mut channel, &purpose)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }

    fn serve_original_evaluated_next_use_loop(
        &self,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
        reader: &OriginalNextUseReader,
        channel: &mut HostAuthorityPeerChannel,
        purpose: &NextUseReadPurpose,
    ) -> Result<u64, Error> {
        let end = match purpose {
            #[cfg(test)]
            NextUseReadPurpose::CompletionReadinessDeadlineProbe { end, .. } => {
                (*end).min(self.end)
            }
            _ => self.end,
        };
        for request_id in 1..=128 {
            let mut failure = None;
            let exchanged = channel.exchange(|bytes| {
                let original = (|| {
                    if Instant::now() >= end {
                        return Err(Error::Unavailable);
                    }
                    let bytes = self.original_evaluated_next_use_response(
                        selection, reader, purpose, bytes, request_id,
                    )?;
                    if Instant::now() >= end {
                        return Err(Error::Unavailable);
                    }
                    Ok(bytes)
                })();
                original.map_err(|error| {
                    failure = Some(error);
                    HostIssuerTransportError::InvalidRequest
                })
            });
            match exchanged {
                Ok(true) => {}
                Ok(false) => return Ok(request_id - 1),
                Err(error) => return Err(failure.unwrap_or(Error::Transport(error))),
            }
        }
        Err(Error::Unavailable)
    }

    pub(super) fn original_evaluated_next_use_response(
        &self,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
        reader: &OriginalNextUseReader,
        purpose: &NextUseReadPurpose,
        bytes: &[u8],
        request_id: u64,
    ) -> Result<Vec<u8>, Error> {
        self.require_lifetime()?;
        if self.purpose != RetainedVersionPurposeV1::EvaluatedNoUpdate
            || self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published
        {
            return Err(Error::ReadbackRequired);
        }
        // This concrete owner retains the same T/E clients and same C. The
        // lock spans both full live reads and the actual C response. No
        // caller-supplied checker, cached freshness token or retry is used.
        let state = self.state.try_lock().map_err(|_| Error::Busy)?;
        let before = self.read_original(&state)?;
        if before.publication().is_none() {
            return Err(Error::ReadbackRequired);
        }
        let cut = state.cut.as_ref().ok_or(Error::Unavailable)?;
        let evaluated = cut.evaluated.as_ref().ok_or(Error::ReadbackRequired)?;
        let original_context = selection.original_context();
        if original_context.snapshot() != evaluated.snapshot()
            || original_context.receipt_context_binding() != evaluated.receipt_context_binding()
        {
            return Err(Error::Binding(
                "same original Version T/E and Selection cut",
            ));
        }
        selection
            .original_receipt_predecessors(super::super::now()?)
            .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        let original = match purpose {
            NextUseReadPurpose::Readback => {
                OriginalCircuitLearningReadOwnerV1::original_evaluated_next_use_response(
                    reader, bytes, request_id,
                )
            }
            NextUseReadPurpose::CompletionReadiness => {
                OriginalCircuitLearningReadOwnerV1::original_evaluated_next_use_readiness_response(
                    reader, bytes, request_id,
                )
            }
            #[cfg(test)]
            NextUseReadPurpose::CompletionReadinessDeadlineProbe { .. } => {
                OriginalCircuitLearningReadOwnerV1::original_evaluated_next_use_readiness_response(
                    reader, bytes, request_id,
                )
            }
        }
        .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        #[cfg(test)]
        if let NextUseReadPurpose::CompletionReadinessDeadlineProbe {
            end,
            cross_end_after_original_read,
            response_observed,
        } = purpose
        {
            reader.fixture_observe_original_next_use_response(
                (*end).min(self.end),
                *cross_end_after_original_read,
                Arc::clone(response_observed),
            );
        }
        let after = self.read_original(&state)?;
        if before != after || after.publication().is_none() {
            return Err(Error::CommitUncertain);
        }
        cut.require_fresh(super::super::now()?, PublicationAccess::Readback)?;
        selection
            .original_receipt_predecessors(super::super::now()?)
            .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        self.require_lifetime()?;
        if self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published {
            return Err(Error::ReadbackRequired);
        }
        Ok(original)
    }

    pub(super) fn build_original_evaluated_next_use_reader(
        &self,
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<OriginalNextUseReader, Error> {
        self.require_lifetime()?;
        if self.purpose != RetainedVersionPurposeV1::EvaluatedNoUpdate
            || self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published
        {
            return Err(Error::ReadbackRequired);
        }
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
        let original_context = selection.original_context();
        if original_context.snapshot() != evaluated.snapshot()
            || original_context.receipt_context_binding() != evaluated.receipt_context_binding()
        {
            return Err(Error::Binding(
                "same original Version T/E and Selection cut",
            ));
        }
        // for_original_next_use verifies full T/E/S signatures, the original
        // five-cut NextUse purpose and the retained baseline bundle again.
        let context =
            OriginalCircuitEvaluatedLearningReadContextV1::for_original_next_use(selection.clone())
                .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        let original = match state.phase.as_ref() {
            Some(
                RetainedVersionHostPhaseV1::Installed { original, .. }
                | RetainedVersionHostPhaseV1::Recovered(original),
            ) => original,
            _ => return Err(Error::ReadbackRequired),
        };
        let reader = OriginalCircuitLearningReadOwnerV1::from_original_evaluated_owners(
            original.cell.clone(),
            original.source.as_ref().clone(),
            original.identity.clone(),
            context,
        )
        .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        // The local reader is not exposed before this same-lock full second
        // read of D/T/E, Artifact/CURRENT and the actual installed C succeeds.
        let after = self.read_original(&state)?;
        if before != after || after.publication().is_none() {
            return Err(Error::CommitUncertain);
        }
        state
            .cut
            .as_ref()
            .ok_or(Error::Unavailable)?
            .require_fresh(super::super::now()?, PublicationAccess::Readback)?;
        selection
            .original_receipt_predecessors(super::super::now()?)
            .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        self.require_lifetime()?;
        if self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published {
            return Err(Error::ReadbackRequired);
        }
        Ok(reader)
    }
}

#[cfg(test)]
#[path = "circuit_evaluated_version_next_use_readback_support_tests.rs"]
mod fixture;
