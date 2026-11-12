//! Positive Model Selector commands. No request carries a snapshot, result,
//! signing payload, key, qualification seal or grant. NoUpdate is separate.

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
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use super::LearningIterationEvidencePeerV1;
use super::wire as evidence_wire;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationCheckpointErrorV1;
use crate::OriginalCellQ24ModelCommandReceiptV1;
use crate::OriginalCircuitCandidateLearningReadContextV1;
use crate::OriginalCircuitCandidateLearningReadErrorV1;
use crate::OriginalCircuitModelSelectionReceiptErrorV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[path = "circuit_model_selection_command_service.rs"]
mod serving;
#[path = "circuit_model_selection_command_wire.rs"]
mod wire;
pub use serving::OriginalCircuitModelSelectionCommandOwnerV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitModelSelectionCommandErrorV1 {
    #[error("original Model Selector binding: {0}")]
    Binding(&'static str),
    #[error("original Model Selector channel is unavailable")]
    Unavailable,
    #[error("original Model Selector completion is uncertain")]
    CommitUncertain,
    #[error("original Model Selector is readback only")]
    ReadbackRequired,
    #[error("original Model Selector lane is occupied")]
    Busy,
    #[error("original Model Selector record is missing")]
    Missing,
    #[error("original Model Selector claim is pending")]
    Pending,
    #[error("original Model Selector work deadline expired")]
    DeadlineExceeded,
    #[error("original Model Selector transport: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original Model Selector owner: {0}")]
    Owner(#[from] OriginalCircuitModelSelectionReceiptErrorV1),
    #[error("original Model Selector iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Model Selector evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original Model Selector checkpoint: {0}")]
    Checkpoint(#[from] LearningIterationCheckpointErrorV1),
    #[error("original positive publication: {0}")]
    Published(#[from] OriginalCircuitCandidateLearningReadErrorV1),
    #[error("original Model Selector encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}
type Error = OriginalCircuitModelSelectionCommandErrorV1;

/// Only the original command decoder can construct this completed extension.
/// It is comparison data; independent reads always contact the original owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitModelSelectionCommandReceiptV1 {
    snapshot: LearningIterationSnapshotV1,
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
    context: OriginalCircuitCandidateLearningReadContextV1,
}
impl OriginalCircuitModelSelectionCommandReceiptV1 {
    pub fn snapshot(&self) -> &LearningIterationSnapshotV1 { &self.snapshot }
    pub fn receipt(&self) -> &LearningIterationReceiptV1 { &self.receipt }
    pub fn attestation(&self) -> &SignedLearningEvidenceV1 { &self.attestation }
    pub fn model(&self) -> &OriginalCellQ24ModelCommandReceiptV1 { self.context.model() }
    pub(crate) fn original_publication_context(&self) -> &OriginalCircuitCandidateLearningReadContextV1 {
        &self.context
    }
}

// A dropped async caller cannot authorize a still-queued Execute. This flag
// belongs only to one exchange; it never restores the consumed channel or once bit.
struct QueuedExecuteFence {
    abandoned: Arc<AtomicBool>,
}

impl Drop for QueuedExecuteFence {
    fn drop(&mut self) {
        self.abandoned.store(/*val*/ true, Ordering::Release);
    }
}

struct Channel {
    peer: HostAuthorityPeerChannel,
    next_request_id: u64,
    execution_requested: bool,
}
pub struct OriginalCircuitModelSelectionCommandClientV1 {
    channel: Mutex<Option<Channel>>,
    context: OriginalCircuitCandidateLearningReadContextV1,
    binding: Digest32,
    retained: Mutex<Option<OriginalCircuitModelSelectionCommandReceiptV1>>,
}

impl OriginalCircuitModelSelectionCommandClientV1 {
    /// Original-host supplied connected stream and held pidfd only. Bootstrap
    /// is synchronous bounded I/O and belongs on the host's blocking lane.
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        context: OriginalCircuitCandidateLearningReadContextV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(
            stream,
            peer,
            original_owner_pidfd,
            context,
            timeout,
            lifetime,
            /*execution_requested*/ false,
            None,
        )
    }

    /// An actual opaque Model context may restore only this original readback
    /// channel. It does not grant a recovered receipt owner execution.
    pub fn recover_from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        context: OriginalCircuitCandidateLearningReadContextV1,
        expected: Option<OriginalCircuitModelSelectionCommandReceiptV1>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(
            stream, peer, original_owner_pidfd, context, timeout, lifetime, /*execution_requested*/ true, expected,
        )
    }

    /// Consume the initially delivered channel once. Its peer, nonce origin
    /// and absolute deadline are retained, with no future result or reconnect.
    pub(crate) fn bind_original_stage_channel(
        peer: HostAuthorityPeerChannel,
        context: OriginalCircuitCandidateLearningReadContextV1,
        readback_only: bool,
        expected: Option<OriginalCircuitModelSelectionCommandReceiptV1>,
    ) -> Result<Self, Error> {
        let started = now()?;
        wire::require_selection_context(&context, started)?;
        let binding = context.binding(started)?;
        peer.check_peer_lifetime()?;
        let fresh = now()?;
        require_clock(started, fresh)?;
        if context.binding(fresh)? != binding {
            return Err(Error::Binding("same original positive Selector context"));
        }
        if let Some(original) = &expected {
            if wire::authenticate_completed(&context, original.snapshot.clone(), original.attestation.clone(), fresh)? != *original {
                return Err(Error::Binding("same original positive Selector recovery"));
            }
        }
        Ok(Self {
            channel: Mutex::new(Some(Channel {
                peer, next_request_id: 1, execution_requested: readback_only,
            })),
            context, binding, retained: Mutex::new(expected),
        })
    }

    fn bind_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        context: OriginalCircuitCandidateLearningReadContextV1,
        timeout: Duration,
        lifetime: Duration,
        execution_requested: bool,
        retained: Option<OriginalCircuitModelSelectionCommandReceiptV1>,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        wire::require_selection_context(&context, started_at)?;
        let binding = context.binding(started_at)?;
        if peer.actor_id != context.decision().owners.selector {
            return Err(Error::Binding("original Selector process"));
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
        if let Some(expected) = &retained {
            if wire::authenticate_completed(
                &context,
                expected.snapshot.clone(),
                expected.attestation.clone(),
                current,
            )? != *expected
            {
                return Err(Error::Binding("exact cold original Selection"));
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
            retained: Mutex::new(retained),
        })
    }

    /// One dispatch only. Timeout, cancellation of this future, Busy or an
    /// unknown ACK never causes automatic execution replay or a new operation.
    pub async fn execute_selection(
        &self,
    ) -> Result<OriginalCircuitModelSelectionCommandReceiptV1, Error> {
        if now()? >= self.context.decision().request.envelope.expiry_unix_seconds {
            return Err(Error::DeadlineExceeded);
        }
        self.exchange(wire::Action::Execute).await
    }

    pub async fn readback(&self) -> Result<OriginalCircuitModelSelectionCommandReceiptV1, Error> {
        self.exchange(wire::Action::Readback).await
    }

    pub async fn receipt_attestation(
        &self,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let original = OriginalCircuitModelSelectionCommandClientV1::readback(self).await?;
        if &original.receipt != expected {
            return Err(Error::Binding("exact original Selection receipt"));
        }
        Ok(original.attestation)
    }

    async fn exchange(
        &self,
        action: wire::Action,
    ) -> Result<OriginalCircuitModelSelectionCommandReceiptV1, Error> {
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
        OriginalCircuitCandidateLearningReadContextV1::authenticate(&self.context, started_at)?;
        let request_id = channel.next_request_id;
        if !(1..=128).contains(&request_id) {
            return Err(Error::Unavailable);
        }
        channel.next_request_id = request_id.checked_add(1).ok_or(Error::Unavailable)?;
        let request = wire::Request::new(&self.context, self.binding, request_id, action);
        let encoded = serde_json::to_vec(&request)?;
        if encoded.len() > 16_384 { return Err(Error::Binding("bounded positive Selector request")); }
        let abandoned = Arc::new(AtomicBool::new(/*v*/ false));
        let queued_execute_fence = QueuedExecuteFence {
            abandoned: Arc::clone(&abandoned),
        };
        let (channel, bytes) = tokio::task::spawn_blocking(move || {
            // The original peer remains moved into this one task. Once the
            // request has started, a cancelled waiter still has an unknown ACK.
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
        if bytes.len() > 16_384 { return Err(Error::Binding("bounded positive Selector response")); }
        let response: wire::Response = serde_json::from_slice(&bytes)?;
        response.require_request(&request)?;
        channel.peer.check_peer_lifetime()?;
        let current = now()?;
        require_clock(started_at, current)?;
        OriginalCircuitCandidateLearningReadContextV1::authenticate(&self.context, current)?;
        let result = match response.result {
            wire::CommandResult::Completed { snapshot, evidence } => {
                let original = wire::decode_completed(&self.context, snapshot, evidence, current)?;
                let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
                if retained
                    .as_ref()
                    .is_some_and(|previous| previous != &original)
                {
                    return Err(Error::Binding("unchanged original Selection attestation"));
                }
                *retained = Some(original.clone());
                Ok(original)
            }
            wire::CommandResult::Missing | wire::CommandResult::Pending
                if self.retained.try_lock().map_err(|_| Error::Unavailable)?.is_some() => {
                    return Err(Error::CommitUncertain);
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
            "original Selector command clock moved backwards",
        ));
    }
    Ok(())
}
fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("original Selector system clock"))
}
