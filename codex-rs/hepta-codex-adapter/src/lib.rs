//! Exact-bound Codex App Server execution adapter.
//!
//! The pre-dispatch intent binds an exact `turn/start` payload to the owning
//! Agent generation and final-use authority. A real App Server turn id only
//! exists after admission, so terminal correlation is a separate dispatched
//! binding. Terminal truth is accepted only from an opaque witness minted by
//! `codex-app-server-client` from a real `turn/completed` notification.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;
use std::io::ErrorKind;

use codex_app_server_client::RemoteAppServerRequestHandle;
use codex_app_server_client::RemotePendingRequest;
use codex_app_server_client::TerminalTurnWitness;
use codex_app_server_client::TypedRequestError;
pub use codex_app_server_client::TerminalTurnOutcome as TerminalOutcome;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const TURN_START_METHOD: &str = "turn/start";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexOperationIntent {
    pub operation_id: StableId,
    pub subject_id: StableId,
    pub destination_id: StableId,
    pub thread_id: StableId,
    pub client_message_id: StableId,
    pub method_id: StableId,
    pub payload_digest: Digest32,
    pub lease_payload_digest: Digest32,
    pub scope_digest: Digest32,
    pub authority_epoch: u64,
    pub session_generation: u64,
    pub protocol_version: u32,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchedCodexOperation {
    pub intent: CodexOperationIntent,
    pub turn_id: StableId,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AdapterStatus {
    Succeeded,
    Failed,
    Interrupted,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexAdapterReceipt {
    pub operation_id: StableId,
    pub thread_id: StableId,
    pub turn_id: StableId,
    pub session_generation: u64,
    pub protocol_version: u32,
    pub request_digest: Digest32,
    pub status: AdapterStatus,
    pub response_digest: Option<Digest32>,
    pub model_authority: bool,
    pub provider_authority: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    PayloadBindingMismatch,
    TurnStartPayloadMismatch,
    ThreadBindingMismatch,
    ClientMessageBindingMismatch,
    MethodBindingMismatch,
    InvalidAuthorityEpoch,
    InvalidSessionGeneration,
    InvalidProtocolVersion,
    DeadlineExpired,
    InvalidTurnIdentity,
    ObservationCorrelationMismatch,
    ObservationProtocolMismatch,
    MissingTerminalResponse,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AdmissionFailure {
    InvalidIntent,
    AuthorityDenied,
    OverloadedBeforeAdmission,
    UnavailableBeforeAdmission,
}

#[derive(Debug)]
pub struct DispatchAdmissionError {
    pub disposition: AdmissionFailure,
    pub reason: String,
}

impl fmt::Display for DispatchAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{:?}: {}", self.disposition, self.reason)
    }
}

impl StdError for DispatchAdmissionError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TurnStartOutcome {
    Started(DispatchedCodexOperation),
    Rejected {
        code: i64,
        message: String,
    },
    /// The request was synchronously admitted, but the response path was lost.
    /// This is never a safe automatic replay signal.
    Indeterminate {
        reason: String,
    },
    /// The server returned bytes that violate the typed App Server contract.
    Quarantined {
        reason: String,
    },
}

pub struct PendingCodexTurn {
    intent: CodexOperationIntent,
    pending: RemotePendingRequest,
}

impl PendingCodexTurn {
    pub async fn wait(self) -> TurnStartOutcome {
        match self.pending.wait_typed::<TurnStartResponse>().await {
            Ok(response) => match StableId::new(response.turn.id) {
                Ok(turn_id) => TurnStartOutcome::Started(DispatchedCodexOperation {
                    intent: self.intent,
                    turn_id,
                }),
                Err(_) => TurnStartOutcome::Quarantined {
                    reason: "App Server returned an invalid turn identity".to_string(),
                },
            },
            Err(TypedRequestError::Server { source, .. }) => TurnStartOutcome::Rejected {
                code: source.code,
                message: source.message.chars().take(1024).collect(),
            },
            Err(TypedRequestError::Transport { source, .. }) => TurnStartOutcome::Indeterminate {
                reason: source.to_string().chars().take(1024).collect(),
            },
            Err(TypedRequestError::Deserialize { source, .. }) => TurnStartOutcome::Quarantined {
                reason: source.to_string().chars().take(1024).collect(),
            },
        }
    }
}

/// Hash the exact final `turn/start` params that the authority grant and
/// adapter must bind. JSON field names and optional values are part of the
/// payload identity.
pub fn turn_start_payload_digest(params: &TurnStartParams) -> Digest32 {
    let bytes = serde_json::to_vec(params)
        .expect("typed TurnStartParams must serialize to canonical JSON bytes");
    Digest32::of_bytes(&bytes)
}

/// Compute the authority request binding for a structurally valid intent.
pub fn final_use_binding(
    now_ms: u64,
    intent: &CodexOperationIntent,
) -> Result<FinalUseBinding, Error> {
    validate_intent(now_ms, intent)?;
    Ok(FinalUseBinding {
        subject_id: intent.subject_id.as_str().to_string(),
        destination_id: intent.destination_id.as_str().to_string(),
        request_sha256: *request_digest(intent).as_array(),
        scope_sha256: *intent.scope_digest.as_array(),
        payload_sha256: *intent.payload_digest.as_array(),
    })
}

/// Consume one kernel-authority final-use token exactly at the real remote
/// App Server command-queue admission seam.
///
/// A full/closed queue fails before request admission. Once this returns a
/// `PendingCodexTurn`, later timeout or transport loss is indeterminate and
/// callers must reconcile rather than minting a duplicate turn.
pub fn admit_verified_turn(
    now_ms: u64,
    authority: &FinalUseAuthority,
    token: VerifiedUseToken,
    intent: CodexOperationIntent,
    request_id: RequestId,
    params: TurnStartParams,
    handle: &RemoteAppServerRequestHandle,
) -> Result<PendingCodexTurn, DispatchAdmissionError> {
    validate_turn_start(now_ms, &intent, &params).map_err(invalid_intent)?;
    let binding = final_use_binding(now_ms, &intent).map_err(invalid_intent)?;
    let request = ClientRequest::TurnStart { request_id, params };

    let admitted = authority
        .with_verified_use(token, &binding, || handle.try_begin_request(request))
        .map_err(authority_error)?;
    let pending = admitted.map_err(|source| {
        let disposition = if source.kind() == ErrorKind::WouldBlock {
            AdmissionFailure::OverloadedBeforeAdmission
        } else {
            AdmissionFailure::UnavailableBeforeAdmission
        };
        DispatchAdmissionError {
            disposition,
            reason: source.to_string().chars().take(1024).collect(),
        }
    })?;

    Ok(PendingCodexTurn { intent, pending })
}

/// Adapt a dispatched operation using an optional trusted terminal witness.
pub fn adapt(
    now_ms: u64,
    dispatched: &DispatchedCodexOperation,
    witness: Option<&TerminalTurnWitness>,
) -> Result<CodexAdapterReceipt, Error> {
    let observation = witness.map(|value| TerminalObservation {
        thread_id: value.thread_id().to_string(),
        turn_id: value.turn_id().to_string(),
        outcome: value.outcome(),
        protocol_version: value.protocol_version(),
        response_digest: Digest32::of_bytes(value.observation_bytes()),
    });
    adapt_observation(now_ms, dispatched, observation)
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct TerminalObservation {
    thread_id: String,
    turn_id: String,
    outcome: TerminalOutcome,
    protocol_version: u32,
    response_digest: Digest32,
}

fn adapt_observation(
    now_ms: u64,
    dispatched: &DispatchedCodexOperation,
    observation: Option<TerminalObservation>,
) -> Result<CodexAdapterReceipt, Error> {
    validate_intent(now_ms, &dispatched.intent)?;
    if dispatched.turn_id.as_str().is_empty() {
        return Err(Error::InvalidTurnIdentity);
    }

    let (status, response_digest) = match observation {
        None => (AdapterStatus::Indeterminate, None),
        Some(value) => {
            if value.thread_id != dispatched.intent.thread_id.as_str()
                || value.turn_id != dispatched.turn_id.as_str()
            {
                return Err(Error::ObservationCorrelationMismatch);
            }
            if value.protocol_version != dispatched.intent.protocol_version {
                return Err(Error::ObservationProtocolMismatch);
            }
            if value.response_digest.is_zero() {
                return Err(Error::MissingTerminalResponse);
            }
            let status = match value.outcome {
                TerminalOutcome::Completed => AdapterStatus::Succeeded,
                TerminalOutcome::Failed => AdapterStatus::Failed,
                TerminalOutcome::Interrupted => AdapterStatus::Interrupted,
            };
            (status, Some(value.response_digest))
        }
    };

    Ok(CodexAdapterReceipt {
        operation_id: dispatched.intent.operation_id.clone(),
        thread_id: dispatched.intent.thread_id.clone(),
        turn_id: dispatched.turn_id.clone(),
        session_generation: dispatched.intent.session_generation,
        protocol_version: dispatched.intent.protocol_version,
        request_digest: request_digest(&dispatched.intent),
        status,
        response_digest,
        model_authority: false,
        provider_authority: false,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_turn_start(
    now_ms: u64,
    intent: &CodexOperationIntent,
    params: &TurnStartParams,
) -> Result<(), Error> {
    validate_intent(now_ms, intent)?;
    if intent.method_id.as_str() != TURN_START_METHOD {
        return Err(Error::MethodBindingMismatch);
    }
    if params.thread_id != intent.thread_id.as_str() {
        return Err(Error::ThreadBindingMismatch);
    }
    if params.client_user_message_id.as_deref() != Some(intent.client_message_id.as_str()) {
        return Err(Error::ClientMessageBindingMismatch);
    }
    if turn_start_payload_digest(params) != intent.payload_digest {
        return Err(Error::TurnStartPayloadMismatch);
    }
    Ok(())
}

fn validate_intent(now_ms: u64, intent: &CodexOperationIntent) -> Result<(), Error> {
    if intent.payload_digest.is_zero()
        || intent.lease_payload_digest.is_zero()
        || intent.scope_digest.is_zero()
    {
        return Err(Error::EmptyDigest("payload/scope"));
    }
    if intent.payload_digest != intent.lease_payload_digest {
        return Err(Error::PayloadBindingMismatch);
    }
    if intent.authority_epoch == 0 {
        return Err(Error::InvalidAuthorityEpoch);
    }
    if intent.session_generation == 0 {
        return Err(Error::InvalidSessionGeneration);
    }
    if intent.protocol_version == 0 {
        return Err(Error::InvalidProtocolVersion);
    }
    if now_ms >= intent.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    Ok(())
}

fn request_digest(intent: &CodexOperationIntent) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.request.v3");
    push_id(&mut bytes, &intent.operation_id);
    push_id(&mut bytes, &intent.subject_id);
    push_id(&mut bytes, &intent.destination_id);
    push_id(&mut bytes, &intent.thread_id);
    push_id(&mut bytes, &intent.client_message_id);
    push_id(&mut bytes, &intent.method_id);
    bytes.extend_from_slice(intent.payload_digest.as_array());
    bytes.extend_from_slice(intent.scope_digest.as_array());
    bytes.extend_from_slice(&intent.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&intent.session_generation.to_be_bytes());
    bytes.extend_from_slice(&intent.protocol_version.to_be_bytes());
    bytes.extend_from_slice(&intent.deadline_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn invalid_intent(error: Error) -> DispatchAdmissionError {
    DispatchAdmissionError {
        disposition: AdmissionFailure::InvalidIntent,
        reason: error.to_string(),
    }
}

fn authority_error(error: FinalUseError) -> DispatchAdmissionError {
    DispatchAdmissionError {
        disposition: AdmissionFailure::AuthorityDenied,
        reason: error.to_string(),
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "deadline_digest_tests.rs"]
mod deadline_digest_tests;
