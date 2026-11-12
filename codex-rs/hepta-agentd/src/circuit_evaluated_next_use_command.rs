//! Purpose-fixed commands for actual completed evaluated-retention C. The original
//! Observer keeps its signing custody; replies carry only authenticated results.
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

use super::LearningIterationEvidencePeerV1;
use super::wire as evidence_wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationCheckpointErrorV1;
use crate::OriginalCircuitEvaluatedNextUseReceiptV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitNextUseReceiptErrorV1;
use crate::OriginalCircuitRetainedPublicationErrorV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[path = "circuit_evaluated_next_use_command_context.rs"]
mod context;
use context::Context;
#[path = "circuit_evaluated_next_use_command_service.rs"]
mod serving;
#[path = "circuit_evaluated_next_use_command_wire.rs"]
mod wire;
pub use serving::OriginalCircuitEvaluatedNextUseCommandOwnerV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitEvaluatedNextUseCommandErrorV1 {
    #[error("original evaluated C Observer command binding: {0}")]
    Binding(&'static str),
    #[error("original evaluated C Observer command is unavailable")]
    Unavailable,
    #[error("original evaluated C Observer completion is uncertain; read the same operation")]
    CommitUncertain,
    #[error("original evaluated C Observer Execute was already requested; readback only")]
    ReadbackRequired,
    #[error("original evaluated C Observer is occupied")]
    Busy,
    #[error("original evaluated C Observer operation is missing")]
    Missing,
    #[error("original evaluated C Observer operation is pending")]
    Pending,
    #[error("original evaluated C Observer new work deadline expired")]
    DeadlineExceeded,
    #[error("original evaluated C Observer transport: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original evaluated C Observer owner: {0}")]
    Owner(#[from] OriginalCircuitNextUseReceiptErrorV1),
    #[error("original evaluated retention: {0}")]
    Retention(#[from] OriginalCircuitRetainedPublicationErrorV1),
    #[error("original evaluated C Observer iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original evaluated C Observer evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original evaluated C Observer snapshot codec: {0}")]
    Checkpoint(#[from] LearningIterationCheckpointErrorV1),
    #[error("original evaluated C Observer encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}
type Error = OriginalCircuitEvaluatedNextUseCommandErrorV1;

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
    Readback(OriginalCircuitEvaluatedNextUseReceiptV1),
    Executed(OriginalCircuitEvaluatedNextUseReceiptV1),
}

impl Retained {
    fn original(&self) -> &OriginalCircuitEvaluatedNextUseReceiptV1 {
        match self {
            Self::Readback(original) | Self::Executed(original) => original,
        }
    }

    fn execution_confirmed(&self) -> bool {
        matches!(self, Self::Executed(_))
    }
}

pub struct OriginalCircuitEvaluatedNextUseCommandClientV1 {
    channel: Mutex<Option<Channel>>,
    context: Context,
    binding: Digest32,
    retained: Mutex<Option<Retained>>,
}

impl OriginalCircuitEvaluatedNextUseCommandClientV1 {
    /// The original host delivers this connected stream and held pidfd. All
    /// original T/B/S results are already authenticated; no future C is supplied.
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        original: OriginalCircuitEvaluatedSelectionReceiptV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        original
            .original_context()
            .require_new_original_receipt(now()?)?;
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
        original: OriginalCircuitEvaluatedSelectionReceiptV1,
        expected: Option<OriginalCircuitEvaluatedNextUseReceiptV1>,
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
                    return Err(Error::Binding("same original cold evaluated NextUse"));
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
        retained: Option<OriginalCircuitEvaluatedNextUseReceiptV1>,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let binding = context.binding(started_at)?;
        if peer.actor_id != context.selection.snapshot().owners.next_use_observer {
            return Err(Error::Binding("original evaluated C Observer process"));
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
            context
                .selection
                .original_context()
                .require_new_original_receipt(current)?;
        }
        if let Some(saved) = &retained {
            let checked = wire::authenticate_completed(
                &context,
                saved.snapshot().clone(),
                saved.attestation().clone(),
                current,
            )?;
            if !wire::same_original(saved, &checked) {
                return Err(Error::Binding("unchanged cold evaluated NextUse"));
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

    pub async fn attest_completed_task(
        &self,
    ) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
        if now()?
            >= self
                .context
                .selection
                .snapshot()
                .request
                .envelope
                .expiry_unix_seconds
        {
            return Err(Error::DeadlineExceeded);
        }
        self.exchange(wire::Action::Execute).await
    }

    pub async fn readback(&self) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
        self.exchange(wire::Action::Readback).await
    }

    pub async fn receipt_attestation(
        &self,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let original = OriginalCircuitEvaluatedNextUseCommandClientV1::readback(self).await?;
        if original.receipt() != expected {
            return Err(Error::Binding("exact original evaluated NextUse receipt"));
        }
        Ok(original.attestation().clone())
    }

    async fn exchange(
        &self,
        action: wire::Action,
    ) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
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
                .selection
                .original_context()
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
                let context = self.context.selection.clone();
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
                        "unchanged original evaluated NextUse attestation",
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
            "original evaluated C Observer clock moved backwards",
        ));
    }
    Ok(())
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("original evaluated C Observer system clock"))
}

#[cfg(test)]
pub(crate) use serving::command_test_support;
