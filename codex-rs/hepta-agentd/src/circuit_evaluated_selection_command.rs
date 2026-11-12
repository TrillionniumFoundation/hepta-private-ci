//! Purpose-fixed commands for actual evaluated NoUpdate S. The original
//! Selector keeps its signing custody; replies carry only authenticated results.
//! Cold construction permanently attenuates the original context to readback.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use super::super::LearningIterationEvidencePeerV1;
use super::super::wire as evidence_wire;
use super::binding as readback_binding;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationCheckpointErrorV1;
use crate::OriginalCircuitEvaluatedRetentionContextV1;
use crate::OriginalCircuitEvaluatedSelectionReadbackErrorV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitRetainedPublicationErrorV1;
use crate::OriginalCircuitSelectionReceiptErrorV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[path = "circuit_evaluated_selection_command_context.rs"]
mod context;
use context::Context;
#[path = "circuit_evaluated_selection_command_service.rs"]
mod serving;
#[path = "circuit_evaluated_selection_command_wire.rs"]
mod wire;
pub use serving::OriginalCircuitEvaluatedSelectionCommandOwnerV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitEvaluatedSelectionCommandErrorV1 {
    #[error("original evaluated Selector command binding: {0}")]
    Binding(&'static str),
    #[error("original evaluated Selector command is unavailable")]
    Unavailable,
    #[error("original evaluated Selector completion is uncertain; read the same operation")]
    CommitUncertain,
    #[error("original evaluated Selector Execute was already requested; readback only")]
    ReadbackRequired,
    #[error("original evaluated Selector is occupied")]
    Busy,
    #[error("original evaluated Selector operation is missing")]
    Missing,
    #[error("original evaluated Selector operation is pending")]
    Pending,
    #[error("original evaluated Selector new work deadline expired")]
    DeadlineExceeded,
    #[error("original evaluated Selector transport: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original evaluated Selector owner: {0}")]
    Owner(#[from] OriginalCircuitSelectionReceiptErrorV1),
    #[error("original evaluated retention: {0}")]
    Retention(#[from] OriginalCircuitRetainedPublicationErrorV1),
    #[error("original evaluated Selector evidence readback: {0}")]
    Readback(#[from] OriginalCircuitEvaluatedSelectionReadbackErrorV1),
    #[error("original evaluated Selector iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original evaluated Selector evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original evaluated Selector snapshot codec: {0}")]
    Checkpoint(#[from] LearningIterationCheckpointErrorV1),
    #[error("original evaluated Selector encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}
type Error = OriginalCircuitEvaluatedSelectionCommandErrorV1;

struct Channel {
    peer: HostAuthorityPeerChannel,
    next_request_id: u64,
    execution_requested: bool,
}

struct QueuedExecuteFence {
    abandoned: Arc<AtomicBool>,
}
impl Drop for QueuedExecuteFence {
    fn drop(&mut self) {
        self.abandoned.store(true, Ordering::Release);
    }
}

// Only a complete authenticated Execute ACK from this client can retain new
// work provenance. Supplied cold pins and first Readback replies cannot do so.
enum Retained {
    Readback(OriginalCircuitEvaluatedSelectionReceiptV1),
    Executed(OriginalCircuitEvaluatedSelectionReceiptV1),
}

impl Retained {
    fn original(&self) -> &OriginalCircuitEvaluatedSelectionReceiptV1 {
        match self {
            Self::Readback(original) | Self::Executed(original) => original,
        }
    }

    fn execution_confirmed(&self) -> bool {
        matches!(self, Self::Executed(_))
    }
}

pub struct OriginalCircuitEvaluatedSelectionCommandClientV1 {
    channel: Mutex<Option<Channel>>,
    context: Context,
    binding: Digest32,
    retained: Mutex<Option<Retained>>,
}

impl OriginalCircuitEvaluatedSelectionCommandClientV1 {
    /// The original host delivers this connected stream and held pidfd. Both
    /// original T/B results are already authenticated; no future S is supplied.
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        original: OriginalCircuitEvaluatedRetentionContextV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        original.require_new_original_receipt(now()?)?;
        Self::bind_original_stream(
            stream,
            peer,
            original_owner_pidfd,
            Context::from_original(original)?,
            timeout,
            lifetime,
            false,
            None,
        )
    }

    /// Read the exact original operation after an unknown ACK. Even a supplied
    /// fresh predecessor is consumed into permanent Readback before binding.
    pub fn recover_from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        original: OriginalCircuitEvaluatedRetentionContextV1,
        expected: Option<OriginalCircuitEvaluatedSelectionReceiptV1>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let context = Context::from_original(original.into_original_receipt_readback())?;
        let retained = expected
            .map(|saved| {
                let checked = wire::authenticate_completed(
                    &context,
                    saved.snapshot().clone(),
                    saved.attestation().clone(),
                    now()?,
                )?;
                if !wire::same_original(&saved, &checked) {
                    return Err(Error::Binding("same original cold evaluated Selection"));
                }
                Ok(checked)
            })
            .transpose()?;
        Self::bind_original_stream(
            stream,
            peer,
            original_owner_pidfd,
            context,
            timeout,
            lifetime,
            true,
            retained,
        )
    }

    fn bind_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        context: Context,
        timeout: Duration,
        lifetime: Duration,
        execution_requested: bool,
        retained: Option<OriginalCircuitEvaluatedSelectionReceiptV1>,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let binding = context.binding(started_at)?;
        if peer.actor_id != context.original.snapshot().owners.selector {
            return Err(Error::Binding("original evaluated Selector process"));
        }
        let channel = original_owner_command_channel_v1(
            stream,
            AgentdRootAuthorityPeer {
                pid: peer.pid,
                boot_id: peer.boot_id,
                process_start_ticks: peer.process_start_ticks,
            },
            peer.uid,
            original_owner_pidfd,
            timeout,
            lifetime,
        )?;
        let current = now()?;
        require_clock(started_at, current)?;
        context.authenticate(current)?;
        if !execution_requested {
            context.original.require_new_original_receipt(current)?;
        }
        if let Some(saved) = &retained {
            let checked = wire::authenticate_completed(
                &context,
                saved.snapshot().clone(),
                saved.attestation().clone(),
                current,
            )?;
            if !wire::same_original(saved, &checked) {
                return Err(Error::Binding("unchanged cold evaluated Selection"));
            }
        }
        Ok(Self {
            channel: Mutex::new(Some(Channel {
                peer: channel,
                next_request_id: 1,
                execution_requested,
            })),
            context,
            binding,
            retained: Mutex::new(retained.map(Retained::Readback)),
        })
    }

    pub async fn execute_selection(
        &self,
    ) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        if now()?
            >= self
                .context
                .original
                .snapshot()
                .request
                .envelope
                .expiry_unix_seconds
        {
            return Err(Error::DeadlineExceeded);
        }
        self.exchange(wire::Action::Execute).await
    }

    pub async fn readback(&self) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        self.exchange(wire::Action::Readback).await
    }

    pub async fn receipt_attestation(
        &self,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let original = OriginalCircuitEvaluatedSelectionCommandClientV1::readback(self).await?;
        if original.receipt() != expected {
            return Err(Error::Binding("exact original evaluated Selection receipt"));
        }
        Ok(original.attestation().clone())
    }

    async fn exchange(
        &self,
        action: wire::Action,
    ) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        let started_at = now()?;
        let mut channel = {
            let mut slot = self.channel.try_lock().map_err(|_| Error::Unavailable)?;
            if action == wire::Action::Execute
                && slot
                    .as_ref()
                    .is_some_and(|channel| channel.execution_requested)
            {
                return Err(Error::ReadbackRequired);
            }
            let mut channel = slot.take().ok_or(Error::Unavailable)?;
            if action == wire::Action::Execute {
                channel.execution_requested = true;
            }
            channel
        };
        self.context.authenticate(started_at)?;
        if action == wire::Action::Execute {
            self.context
                .original
                .require_new_original_receipt(started_at)?;
        }
        let request_id = channel.next_request_id;
        if !(1..=128).contains(&request_id) {
            return Err(Error::Unavailable);
        }
        channel.next_request_id = request_id.checked_add(1).ok_or(Error::Unavailable)?;
        let request = wire::Request::new(&self.context, self.binding, request_id, action);
        let encoded = serde_json::to_vec(&request)?;
        let abandoned = Arc::new(AtomicBool::new(false));
        let queued_execute_fence = QueuedExecuteFence {
            abandoned: Arc::clone(&abandoned),
        };
        let (channel, bytes) = tokio::task::spawn_blocking(move || {
            if action == wire::Action::Execute && abandoned.load(Ordering::Acquire) {
                return Err(Error::Unavailable);
            }
            let bytes = channel
                .peer
                .request(&encoded)
                .map_err(|_| Error::CommitUncertain)?;
            Ok::<_, Error>((channel, bytes))
        })
        .await
        .map_err(|_| Error::CommitUncertain)??;
        drop(queued_execute_fence);
        let response: wire::Response = serde_json::from_slice(&bytes)?;
        response.require_request(&request)?;
        channel.peer.check_peer_lifetime()?;
        let current = now()?;
        require_clock(started_at, current)?;
        self.context.authenticate(current)?;
        let result = match response.result {
            wire::CommandResult::Completed { snapshot, evidence } => {
                let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
                let execution_confirmed = action == wire::Action::Execute
                    || retained.as_ref().is_some_and(Retained::execution_confirmed);
                let context = self.context.original.clone_for_original_receipt();
                let response_context = Context::from_original(if execution_confirmed {
                    context
                } else {
                    context.into_original_receipt_readback()
                })?;
                let original =
                    wire::decode_completed(&response_context, snapshot, evidence, current)?;
                if retained
                    .as_ref()
                    .is_some_and(|saved| !wire::same_original(saved.original(), &original))
                {
                    return Err(Error::Binding(
                        "unchanged original evaluated Selection attestation",
                    ));
                }
                *retained = Some(if execution_confirmed {
                    Retained::Executed(original.clone())
                } else {
                    Retained::Readback(original.clone())
                });
                Ok(original)
            }
            wire::CommandResult::Missing => Err(Error::Missing),
            wire::CommandResult::Pending => Err(Error::Pending),
            wire::CommandResult::Busy => Err(Error::Busy),
            wire::CommandResult::Expired => Err(Error::DeadlineExceeded),
            wire::CommandResult::ReadbackRequired => Err(Error::ReadbackRequired),
            wire::CommandResult::Uncertain => return Err(Error::CommitUncertain),
            wire::CommandResult::Unavailable => return Err(Error::Unavailable),
        };
        *self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel);
        result
    }
}

fn require_clock(started_at: u64, current: u64) -> Result<(), Error> {
    if current < started_at {
        return Err(Error::Binding(
            "original evaluated Selector clock moved backwards",
        ));
    }
    Ok(())
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("original evaluated Selector system clock"))
}

#[cfg(test)]
pub(crate) use serving::command_test_support;
