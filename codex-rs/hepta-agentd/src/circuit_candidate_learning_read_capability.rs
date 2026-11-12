//! Purpose-fixed readback of an original published Circuit and TaskSource.
//! No writer, signer, publication grant or caller-supplied observation crosses
//! this boundary. Every read consults the same original owners again.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
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
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdRootAuthorityPeer;
use crate::CircuitTaskErrorV1;
use crate::LearningIterationCheckpointErrorV1;
use crate::OriginalCellQ24ModelCommandReceiptV1;
use crate::OriginalCircuitModelPublicationContextV1;
use crate::OriginalCircuitModelSelectionCommandReceiptV1;
use crate::learning_owner_command_channel::original_owner_command_channel_v1;

#[path = "circuit_candidate_learning_completion_readiness.rs"]
mod readiness;
pub(crate) use readiness::OriginalCircuitCandidateCompletionReadinessClientV1;

#[path = "circuit_candidate_learning_read_service.rs"]
mod serving;
#[path = "circuit_candidate_learning_read_wire.rs"]
mod wire;

pub use serving::OriginalCircuitCandidateLearningReadOwnerV1;

/// One original positive Model cut, optionally extended by the actual original
/// Selector command result. This value is an immutable comparison pin. Every
/// use of the read client still performs actual original owner I/O.
#[derive(Clone)]
pub struct OriginalCircuitCandidateLearningReadContextV1 {
    prefix: LearningIterationSnapshotV1,
    publication: Arc<OriginalCircuitModelPublicationContextV1>,
    selection_evidence: Option<SignedLearningEvidenceV1>,
}

impl std::fmt::Debug for OriginalCircuitCandidateLearningReadContextV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.debug_struct("OriginalCircuitCandidateLearningReadContextV1")
            .field("prefix", &self.prefix)
            .field("model", self.model())
            .field("scope_binding", &self.scope().binding())
            .field("selection_evidence", &self.selection_evidence)
            .finish()
    }
}

impl PartialEq for OriginalCircuitCandidateLearningReadContextV1 {
    fn eq(&self, other: &Self) -> bool {
        self.same_original_context(other)
    }
}
impl Eq for OriginalCircuitCandidateLearningReadContextV1 {}

impl OriginalCircuitCandidateLearningReadContextV1 {
    /// The publication context can only be produced by an actual Model read.
    /// No public constructor accepts a future snapshot or a Model record DTO.
    pub fn from_original_model(
        publication: OriginalCircuitModelPublicationContextV1,
    ) -> Result<Self, Error> {
        let context = Self {
            prefix: publication.decision().clone(),
            publication: Arc::new(publication),
            selection_evidence: None,
        };
        wire::context_binding(&context, now()?)?;
        Ok(context)
    }

    /// Preserve the exact original Model pin while extending it by the opaque
    /// result of the original positive Selector command.
    pub fn from_original_selection(
        original: &OriginalCircuitModelSelectionCommandReceiptV1,
    ) -> Result<Self, Error> {
        let source = original.original_publication_context();
        if wire::mode(source)? != wire::Mode::Selection
            || source.model() != original.model()
        {
            return Err(Error::Binding("same original positive Model before Selection"));
        }
        let mut coordinator =
            codex_hepta_learning_artifacts::LearningIterationCoordinatorV1::from_snapshot(
                source.prefix.clone(),
            )?;
        coordinator.record(
            original.receipt().clone(),
            original.receipt().observed_unix_seconds,
        )?;
        if coordinator.snapshot() != original.snapshot() {
            return Err(Error::Binding("one actual original positive Selection extension"));
        }
        let context = Self {
            prefix: original.snapshot().clone(),
            publication: Arc::clone(&source.publication),
            selection_evidence: Some(original.attestation().clone()),
        };
        wire::context_binding(&context, now()?)?;
        Ok(context)
    }

    pub fn prefix(&self) -> &LearningIterationSnapshotV1 {
        &self.prefix
    }

    pub fn decision(&self) -> &LearningIterationSnapshotV1 {
        self.publication.decision()
    }

    pub fn model(&self) -> &OriginalCellQ24ModelCommandReceiptV1 {
        self.publication.model()
    }

    pub fn scope(&self) -> &FrozenLearningScopeV2 {
        self.publication.scope()
    }

    pub fn verifier(&self) -> &LearningEvidenceVerifierV1 {
        self.publication.verifier()
    }

    pub(crate) fn model_publication_context(&self) -> &OriginalCircuitModelPublicationContextV1 {
        self.publication.as_ref()
    }

    pub(crate) fn original_predecessors(&self) -> &[SignedLearningEvidenceV1; 4] {
        self.publication.signatures()
    }

    pub(crate) fn training_attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.publication.signatures()[2]
    }

    pub(crate) fn evaluation_attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.publication.signatures()[3]
    }

    pub(crate) fn selection_attestation(&self) -> Option<&SignedLearningEvidenceV1> {
        self.selection_evidence.as_ref()
    }

    pub(crate) fn authenticate(&self, current: u64) -> Result<Vec<VerifiedLearningEvidenceV1>, Error> {
        wire::authenticate(self, current)
    }

    pub(crate) fn binding(&self, current: u64) -> Result<Digest32, Error> {
        wire::context_binding(self, current)
    }

    pub(crate) fn same_original_context(&self, other: &Self) -> bool {
        self.prefix == other.prefix
            && self.model() == other.model()
            && self.scope() == other.scope()
            && self.verifier().trust_digest() == other.verifier().trust_digest()
            && self.verifier().scope_digest() == other.verifier().scope_digest()
            && self.verifier().objective_digest() == other.verifier().objective_digest()
            && self.selection_evidence == other.selection_evidence
    }
}

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitCandidateLearningReadErrorV1 {
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
type Error = OriginalCircuitCandidateLearningReadErrorV1;

/// An instant's verified original read. Keeping this value is not a lease,
/// authority, permission to execute, or evidence of a later CURRENT.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitCandidateLearningReadbackV1 {
    observation: LearningIterationObservationV1,
    publication: Digest32,
    source_input: Digest32,
    source_publication: Option<Digest32>,
}

impl OriginalCircuitCandidateLearningReadbackV1 {
    pub fn observation(&self) -> &LearningIterationObservationV1 {
        &self.observation
    }
    pub fn publication_digest(&self) -> Digest32 {
        self.publication
    }
    pub fn source_input_digest(&self) -> Digest32 {
        self.source_input
    }
    pub fn source_publication_digest(&self) -> Option<Digest32> {
        self.source_publication
    }
}

struct Channel {
    peer: HostAuthorityPeerChannel,
    next_request_id: u64,
}

/// The host supplies the connected original task process and its already-held
/// pidfd. This constructor cannot discover/reconnect an owner, deserialize a
/// capability from a receipt, or upgrade a read to a command.
pub struct OriginalCircuitCandidateLearningReadClientV1 {
    context: OriginalCircuitCandidateLearningReadContextV1,
    binding: Digest32,
    channel: Mutex<Option<Channel>>,
    retained: Mutex<Option<OriginalCircuitCandidateLearningReadbackV1>>,
}

impl OriginalCircuitCandidateLearningReadClientV1 {
    /// Late bind only the already-held original channel. No reconnect, new
    /// pidfd, renewed deadline, role upgrade or future observation is accepted.
    pub(crate) fn bind_original_stage_channel(
        peer: HostAuthorityPeerChannel,
        context: OriginalCircuitCandidateLearningReadContextV1,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let binding = wire::context_binding(&context, started_at)?;
        peer.check_peer_lifetime()?;
        let fresh = now()?;
        if fresh < started_at || wire::context_binding(&context, fresh)? != binding {
            return Err(Error::Binding("same original positive read late binding"));
        }
        Ok(Self {
            context,
            binding,
            channel: Mutex::new(Some(Channel { peer, next_request_id: 1 })),
            retained: Mutex::new(None),
        })
    }

    pub fn from_original_stream(
        stream: UnixStream,
        original_task_process: AgentdRootAuthorityPeer,
        original_task_uid: u32,
        original_task_pidfd: OwnedFd,
        context: OriginalCircuitCandidateLearningReadContextV1,
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
    pub async fn read_current(&self) -> Result<OriginalCircuitCandidateLearningReadbackV1, Error> {
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
        if response.is_empty() || response.len() > 16_384 {
            return Err(Error::Binding("bounded original positive read response"));
        }
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

    pub(crate) fn original_context(&self) -> &OriginalCircuitCandidateLearningReadContextV1 {
        &self.context
    }

    /// Compare complete opaque Model and Selector pins; this does not replace
    /// the actual read which the original receipt owner performs next.
    pub(crate) fn require_original_context(
        &self,
        expected: &OriginalCircuitCandidateLearningReadContextV1,
    ) -> Result<(), Error> {
        if !self.context.same_original_context(expected) {
            return Err(Error::Binding("same original positive published read context"));
        }
        wire::context_binding(&self.context, now()?)?;
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
