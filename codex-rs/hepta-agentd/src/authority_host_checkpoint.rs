//! Root-protected publication of the original CognitiveStore recovery head.
//! This stores no operations, grants or nonces. Runtime has no genesis/reset API.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::COGNITIVE_CHECKPOINT_FRAME_LIMIT;
use codex_hepta_memory::CognitiveCheckpointCommand;
use codex_hepta_memory::CognitiveCheckpointHead;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_memory::CognitiveCheckpointProposal;
use codex_hepta_memory::CognitiveCheckpointReason;
use codex_hepta_memory::CognitiveCheckpointRequest;
use codex_hepta_memory::CognitiveCheckpointResponse;
use codex_hepta_memory::CognitiveCheckpointRetainedProposal;
use codex_hepta_memory::CognitiveCheckpointRetainedRequest;
use codex_hepta_memory::CognitiveCheckpointStatus;
use codex_hepta_memory::CognitiveCheckpointToken;
use codex_hepta_memory::CognitiveCheckpointWriterBinding;
use codex_hepta_memory::CognitiveRecoveryAnchor;

#[path = "authority_host_checkpoint_state.rs"]
mod state;
use state::advance;
use state::request_sequence;
use state::response;
use state::token_for;
use state::validate_cut;
use state::validate_head;
use state::validate_registration;

const STORE_OWNER: &str = "root-cognitive-checkpoint-v1";
const OPERATION: &str = "runtime.cognitive.checkpoint.v1";

#[path = "authority_host_checkpoint_publisher.rs"]
mod publisher;
pub use publisher::RetainedCheckpointPublisher;
pub use publisher::RetiredCheckpointPublisher;

#[path = "authority_host_checkpoint_adoption.rs"]
mod adoption;

/// Actual trusted launcher registration. The peer cannot replace these fields.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HostCognitiveCheckpointRegistration {
    pub owner_agent_id: AgentId,
    pub publisher_epoch: u64,
    pub writer_binding: CognitiveCheckpointWriterBinding,
    pub peer_lifetime: CognitiveCheckpointPeerLifetime,
}

/// A single fixed publisher's existing protected head. SO_PEERCRED, retained
/// pidfd and the original live AuthorityLease dispatch fence remain mandatory
/// at the surrounding service. A hash of a local/suspect DB cannot initialize it.
pub struct HostCognitiveCheckpoint {
    registration: HostCognitiveCheckpointRegistration,
    store: HostAuthorityFrontierStore<CognitiveCheckpointHead>,
    clock: Arc<dyn AuthorityClock>,
    closed: AtomicBool,
    exchange_lock: Mutex<()>,
}

impl HostCognitiveCheckpoint {
    /// Trusted root bootstrap only, before releasing a genuinely fresh original
    /// DB to its writer. `initial_cut` must come from that DB's original owner.
    /// An existing/partial protected head is never replaced. This function is
    /// deliberately absent from the runtime wire protocol.
    pub fn initialize_fresh(
        directory: Arc<RootAuthorityDirectory>,
        registration: HostCognitiveCheckpointRegistration,
        initial_cut: CognitiveRecoveryAnchor,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, AuthorityTrustError> {
        validate_registration(&registration)?;
        validate_cut(&registration, &initial_cut)?;
        if clock.now_unix_ms()? >= registration.writer_binding.expires_at_unix_seconds * 1000 {
            return Err(AuthorityTrustError::Invalid);
        }
        let head = CognitiveCheckpointHead {
            schema_version: 1,
            owner_agent_id: registration.owner_agent_id.clone(),
            publisher_epoch: registration.publisher_epoch,
            counter: 1,
            last_mutation_sequence: 0,
            writer_binding: registration.writer_binding.clone(),
            peer_lifetime: registration.peer_lifetime.clone(),
            phase: CognitiveCheckpointPhase::Current,
            last_current: initial_cut,
            proposal: None,
            last_request: None,
        };
        let store = HostAuthorityFrontierStore::initialize(directory, STORE_OWNER.into(), head)?;
        let result = Self {
            registration,
            store,
            clock,
            closed: AtomicBool::new(false),
            exchange_lock: Mutex::new(()),
        };
        result.load()?;
        if !result.within_expiry()? {
            return Err(result.close());
        }
        Ok(result)
    }

    /// Runtime open only. Missing state, identity drift and a different
    /// publisher are errors, never implicit genesis or previous-Current fallback.
    pub fn open(
        directory: Arc<RootAuthorityDirectory>,
        registration: HostCognitiveCheckpointRegistration,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, AuthorityTrustError> {
        validate_registration(&registration)?;
        let result = Self {
            registration,
            store: HostAuthorityFrontierStore::open(directory, STORE_OWNER.into())?,
            clock,
            closed: AtomicBool::new(false),
            exchange_lock: Mutex::new(()),
        };
        result.load()?;
        Ok(result)
    }

    /// Process exactly one bounded original request. ACK requires the original
    /// durable CAS, durable readback and a post-I/O time check. Any uncertain
    /// outcome closes this publisher object permanently. The transport performs
    /// its original owner/deadline checks before sending a response prefix.
    pub fn exchange(&self, bytes: &[u8]) -> Result<Vec<u8>, AuthorityTrustError> {
        if bytes.is_empty() || bytes.len() > COGNITIVE_CHECKPOINT_FRAME_LIMIT {
            return Err(AuthorityTrustError::Invalid);
        }
        let request: CognitiveCheckpointRequest =
            serde_json::from_slice(bytes).map_err(|_| AuthorityTrustError::Invalid)?;
        let _guard = self
            .exchange_lock
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let response = self.handle(&request, bytes);
        let encoded = serde_json::to_vec(&response).map_err(|_| self.close())?;
        if encoded.len() > COGNITIVE_CHECKPOINT_FRAME_LIMIT {
            return Err(self.close());
        }
        Ok(encoded)
    }

    fn handle(
        &self,
        request: &CognitiveCheckpointRequest,
        raw: &[u8],
    ) -> CognitiveCheckpointResponse {
        let refused = |reason| response(request, CognitiveCheckpointStatus::Refused, Some(reason));
        let unknown = || {
            response(
                request,
                CognitiveCheckpointStatus::Unknown,
                Some(CognitiveCheckpointReason::Unavailable),
            )
        };
        if self.closed.load(Ordering::Acquire) {
            return unknown();
        }
        let Some((epoch, sequence)) = request_sequence(&request.request_id) else {
            return refused(CognitiveCheckpointReason::Invalid);
        };
        if request.schema_version != 1 || request.operation != OPERATION {
            return refused(CognitiveCheckpointReason::Invalid);
        }
        if epoch != self.registration.publisher_epoch {
            return refused(CognitiveCheckpointReason::StalePublisher);
        }
        match self.within_expiry() {
            Ok(true) => {}
            Ok(false) => return refused(CognitiveCheckpointReason::AuthorityDenied),
            Err(_) => {
                self.close();
                return unknown();
            }
        }
        let current = match self.load() {
            Ok(current) => current,
            // The original nonblocking publication lock can be busy before
            // this request has mutated anything. That is a definite refusal;
            // post-CAS readback failure below remains permanently Unknown.
            Err(AuthorityTrustError::Conflict) => {
                return refused(CognitiveCheckpointReason::Conflict);
            }
            Err(_) => {
                self.close();
                return unknown();
            }
        };
        if request.command == CognitiveCheckpointCommand::ReadHead {
            if request.expected.is_some() || request.proposal.is_some() {
                return refused(CognitiveCheckpointReason::Invalid);
            }
            return self.ack_after_io(request, current);
        }
        let digest = Sha256Digest::for_bytes(raw);
        if let Some(last) = current.last_request.as_ref()
            && last.request_id == request.request_id
        {
            if last.request_sha256 != digest
                || last.command != request.command
                || request.expected.as_ref() != Some(&last.predecessor_token)
            {
                return refused(CognitiveCheckpointReason::Invalid);
            }
            return self.ack_after_io(request, current);
        }
        if sequence <= current.last_mutation_sequence {
            return refused(CognitiveCheckpointReason::StalePublisher);
        }
        let predecessor = match token_for(&current) {
            Ok(token) => token,
            Err(_) => {
                self.close();
                return unknown();
            }
        };
        if request.expected.as_ref() != Some(&predecessor) {
            return refused(CognitiveCheckpointReason::Conflict);
        }
        let next = match advance(
            &self.registration,
            &current,
            request,
            digest,
            predecessor,
            sequence,
        ) {
            Ok(next) => next,
            Err(reason) => return refused(reason),
        };
        match self.store.compare_and_set(STORE_OWNER, &current, &next) {
            Ok(()) => {}
            Err(AuthorityTrustError::Conflict) => {
                return refused(CognitiveCheckpointReason::Conflict);
            }
            Err(_) => {
                self.close();
                return unknown();
            }
        }
        // This concrete original store returns Ok only after file+directory
        // sync and exact next readback under the same publication lock. A new
        // public load would redundantly sync and introduce a separate busy-lock
        // window after the successful mutation. Time is still checked after
        // the complete original durable CAS, before any ACK is constructed.
        self.ack_after_io(request, next)
    }

    fn ack_after_io(
        &self,
        request: &CognitiveCheckpointRequest,
        head: CognitiveCheckpointHead,
    ) -> CognitiveCheckpointResponse {
        match self.within_expiry().and_then(|valid| {
            if valid {
                token_for(&head)
            } else {
                Err(AuthorityTrustError::Unavailable)
            }
        }) {
            Ok(token) => CognitiveCheckpointResponse {
                schema_version: 1,
                request_id: request.request_id.clone(),
                status: CognitiveCheckpointStatus::Ack,
                reason: None,
                token: Some(token),
                head: Some(head),
            },
            Err(_) => {
                self.close();
                response(
                    request,
                    CognitiveCheckpointStatus::Unknown,
                    Some(CognitiveCheckpointReason::Unavailable),
                )
            }
        }
    }

    fn load(&self) -> Result<CognitiveCheckpointHead, AuthorityTrustError> {
        let head = self.store.load(STORE_OWNER)?;
        validate_head(&self.registration, &head)?;
        Ok(head)
    }

    fn within_expiry(&self) -> Result<bool, AuthorityTrustError> {
        Ok(self.clock.now_unix_ms()?
            < self.registration.writer_binding.expires_at_unix_seconds * 1000)
    }

    fn close(&self) -> AuthorityTrustError {
        self.closed.store(true, Ordering::Release);
        AuthorityTrustError::Unavailable
    }
}

#[cfg(test)]
#[path = "authority_host_checkpoint_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "authority_host_checkpoint_fresh_tests.rs"]
mod fresh_tests;
