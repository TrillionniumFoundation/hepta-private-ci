//! Purpose-fixed readback of an original published Circuit and TaskSource.
//! No writer, signer, publication grant or caller-supplied observation crosses
//! this boundary. Every read consults the same original owners again.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdRootAuthorityPeer;
use crate::CircuitTaskErrorV1;
use crate::LearningIterationCheckpointErrorV1;
use crate::OriginalCircuitEvaluatedRetentionContextV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[path = "circuit_learning_completion_readiness.rs"]
mod readiness;
pub(crate) use readiness::OriginalCircuitCompletionReadinessClientV1;

#[path = "circuit_learning_read_service.rs"]
mod serving;
#[path = "circuit_learning_read_wire.rs"]
mod wire;

pub use serving::OriginalCircuitLearningReadOwnerV1;

/// Exactly one original TrainingNoUpdate decision or its original Selection
/// extension. Full retained signatures, including their original windows,
/// remain part of this fixed read capability.
#[derive(Clone)]
pub struct OriginalCircuitLearningReadContextV1 {
    pub prefix: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub verifier: LearningEvidenceVerifierV1,
    pub training_evidence: SignedLearningEvidenceV1,
    pub selection_evidence: Option<SignedLearningEvidenceV1>,
}

// The legacy public input remains strict TrainingNoUpdate. Evaluated retention
// enters only through its opaque original proof, never through that input DTO.
struct ReadContext {
    prefix: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    verifier: LearningEvidenceVerifierV1,
    training_evidence: SignedLearningEvidenceV1,
    selection_evidence: Option<SignedLearningEvidenceV1>,
    evaluated: Option<OriginalCircuitEvaluatedRetentionContextV1>,
}

impl From<OriginalCircuitLearningReadContextV1> for ReadContext {
    fn from(value: OriginalCircuitLearningReadContextV1) -> Self {
        Self {
            prefix: value.prefix,
            scope: value.scope,
            verifier: value.verifier,
            training_evidence: value.training_evidence,
            selection_evidence: value.selection_evidence,
            evaluated: None,
        }
    }
}

impl ReadContext {
    fn from_evaluated(original: OriginalCircuitEvaluatedRetentionContextV1) -> Result<Self, Error> {
        let proof =
            OriginalCircuitEvaluatedRetentionContextV1::original_read_proof(&original, now()?)
                .map_err(|_| Error::Binding("original evaluated retention read proof"))?;
        Ok(Self {
            prefix: original.snapshot().clone(),
            scope: proof.scope.clone(),
            verifier: proof.verifier.clone(),
            training_evidence: proof.training.clone(),
            selection_evidence: None,
            evaluated: Some(original),
        })
    }
}

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitLearningReadErrorV1 {
    #[error("original published Circuit read binding: {0}")]
    Binding(&'static str),
    #[error("original published Circuit read capability unavailable")]
    Unavailable,
    #[error("original published Circuit read: {0}")]
    Owner(#[from] AgentdError),
    #[error("original TaskSource read: {0}")]
    Source(#[from] CircuitTaskErrorV1),
    #[error("original learning iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original retained evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original read transport: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original cut encoding: {0}")]
    Checkpoint(#[from] LearningIterationCheckpointErrorV1),
    #[error("original read wire encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}
type Error = OriginalCircuitLearningReadErrorV1;

/// An instant's verified original read. Keeping this value is not a lease,
/// authority, permission to execute, or evidence of a later CURRENT.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitLearningReadbackV1 {
    observation: LearningIterationObservationV1,
    publication: Digest32,
    source_input: Digest32,
    source_publication: Option<Digest32>,
}

impl OriginalCircuitLearningReadbackV1 {
    pub fn observation(&self) -> &LearningIterationObservationV1 {
        &self.observation
    }
}

struct Channel {
    peer: HostAuthorityPeerChannel,
    next_request_id: u64,
}

/// The host supplies the connected original task process and its already-held
/// pidfd. This constructor cannot discover/reconnect an owner, deserialize a
/// capability from a receipt, or upgrade a read to a command.
pub struct OriginalCircuitLearningReadClientV1 {
    context: ReadContext,
    binding: Digest32,
    channel: Mutex<Option<Channel>>,
    retained: Mutex<Option<OriginalCircuitLearningReadbackV1>>,
}

impl OriginalCircuitLearningReadClientV1 {
    pub fn from_original_stream(
        stream: UnixStream,
        original_task_process: AgentdRootAuthorityPeer,
        original_task_uid: u32,
        original_task_pidfd: OwnedFd,
        context: OriginalCircuitLearningReadContextV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(
            stream,
            original_task_process,
            original_task_uid,
            original_task_pidfd,
            context.into(),
            timeout,
            lifetime,
        )
    }

    /// Read Selection CURRENT for a real four-cut negative evaluation. The
    /// consumed proof grants no publication, Selector or C execution right.
    pub fn from_original_evaluated_stream(
        stream: UnixStream,
        original_task_process: AgentdRootAuthorityPeer,
        original_task_uid: u32,
        original_task_pidfd: OwnedFd,
        context: OriginalCircuitEvaluatedRetentionContextV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        Self::bind_original_stream(
            stream,
            original_task_process,
            original_task_uid,
            original_task_pidfd,
            ReadContext::from_evaluated(context)?,
            timeout,
            lifetime,
        )
    }

    fn bind_original_stream(
        stream: UnixStream,
        original_task_process: AgentdRootAuthorityPeer,
        original_task_uid: u32,
        original_task_pidfd: OwnedFd,
        context: ReadContext,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        require_timing(timeout, lifetime)?;
        let started_at = now()?;
        let binding = wire::context_binding(&context, started_at)?;
        let channel = original_owner_command_channel_v1(
            stream,
            original_task_process,
            original_task_uid,
            original_task_pidfd,
            timeout,
            lifetime,
        )?;
        let fresh = now()?;
        if fresh < started_at || wire::context_binding(&context, fresh)? != binding {
            return Err(Error::Binding("original read bootstrap clock"));
        }
        Ok(Self {
            context,
            binding,
            channel: Mutex::new(Some(Channel {
                peer: channel,
                next_request_id: 1,
            })),
            retained: Mutex::new(None),
        })
    }

    /// Each invocation performs original owner I/O. Failed or cancelled reads
    /// consume this connection. A historical successful read cannot satisfy it.
    pub async fn read_current(&self) -> Result<OriginalCircuitLearningReadbackV1, Error> {
        let mut channel = self
            .channel
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .take()
            .ok_or(Error::Unavailable)?;
        let started_at = now()?;
        if wire::context_binding(&self.context, started_at)? != self.binding {
            return Err(Error::Binding("original fixed read context"));
        }
        if channel.next_request_id > 128 {
            return Err(Error::Unavailable);
        }
        let request = wire::Request::new(&self.context, self.binding, channel.next_request_id)?;
        channel.next_request_id = channel
            .next_request_id
            .checked_add(1)
            .ok_or(Error::Unavailable)?;
        let bytes = serde_json::to_vec(&request)?;
        let (channel, response) = tokio::task::spawn_blocking(move || {
            let response = channel.peer.request(&bytes)?;
            Ok::<_, Error>((channel, response))
        })
        .await
        .map_err(|_| Error::Unavailable)??;
        let response: wire::Response = serde_json::from_slice(&response)?;
        response.require_request(&request)?;
        let current = response.read.decode(&self.context)?;
        channel.peer.check_peer_lifetime()?;
        let fresh = now()?;
        if fresh < started_at || wire::context_binding(&self.context, fresh)? != self.binding {
            return Err(Error::Binding("original read clock moved backwards"));
        }
        {
            let mut retained = self.retained.try_lock().map_err(|_| Error::Unavailable)?;
            if retained.as_ref().is_some_and(|prior| prior != &current) {
                return Err(Error::Binding("original published read changed"));
            }
            *retained = Some(current.clone());
        }
        *self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel);
        Ok(current)
    }

    /// Used only by the original receipt owners before their actual remote
    /// read. Full signature equality prevents a renewed window or other cut
    /// from satisfying the original journal binding.
    pub(crate) fn require_original_context(
        &self,
        prefix: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        verifier: &LearningEvidenceVerifierV1,
        training: &SignedLearningEvidenceV1,
        selection: Option<&SignedLearningEvidenceV1>,
    ) -> Result<(), Error> {
        if self.context.evaluated.is_some()
            || &self.context.prefix != prefix
            || self.context.scope.binding() != scope.binding()
            || self.context.verifier.trust_digest() != verifier.trust_digest()
            || self.context.verifier.scope_digest() != verifier.scope_digest()
            || self.context.verifier.objective_digest() != verifier.objective_digest()
            || &self.context.training_evidence != training
            || self.context.selection_evidence.as_ref() != selection
        {
            return Err(Error::Binding("same original Observer read context"));
        }
        Ok(())
    }
}

fn require_timing(timeout: Duration, lifetime: Duration) -> Result<(), Error> {
    if timeout.is_zero()
        || timeout > Duration::from_millis(500)
        || lifetime.is_zero()
        || lifetime > Duration::from_secs(300)
    {
        return Err(Error::Binding("bounded original read timing"));
    }
    Ok(())
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("original published read clock"))
}

#[cfg(test)]
#[path = "circuit_learning_read_support_tests.rs"]
pub(crate) mod fixture;

#[cfg(test)]
pub(crate) use readiness::fixture as readiness_fixture;

#[cfg(test)]
#[path = "circuit_evaluated_current_read_tests.rs"]
mod evaluated_tests;
#[cfg(test)]
pub(crate) use evaluated_tests::check_evaluated_profiles;
