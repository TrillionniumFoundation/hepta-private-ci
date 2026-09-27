//! Exact-bound Codex App Server request and observation adapter.
//!
//! Product terminality and retry-safe server rejection require process-local
//! evidence produced by the exact RemoteAppServerClient connection. A plain
//! protocol DTO or wire decode cannot be promoted into terminal success.

#![forbid(unsafe_code)]

// Compatibility exports of the sole server-side extension implementation.
use codex_hepta_prompt_extension as runtime_prompt;
mod wire;

use std::error::Error as StdError;
use std::fmt;

use codex_app_server_client::AppServerEvent;
use codex_app_server_client::RemoteAppServerObservedEvent;
use codex_app_server_client::RemoteAppServerObservedResponse;
use codex_app_server_client::RemoteAppServerObservedServerError;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadReadResponse;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use codex_hepta_types::PromptDeliveryErrorV1;
pub use codex_hepta_types::PromptDeliveryObservationV1;
pub use codex_hepta_types::PromptDeliveryRejectReasonV1;
pub use wire::CODEX_OPERATION_INTENT_WIRE_PRODUCER_V2;

pub use runtime_prompt::ContextCompilerRuntimeAttachmentMetadataV2;
pub use runtime_prompt::ContextCompilerRuntimeAttachmentV2;
pub use runtime_prompt::ContextCompilerRuntimeDispatchFutureV2;
pub use runtime_prompt::ContextCompilerRuntimeDispatchV2;
pub use runtime_prompt::ContextCompilerRuntimeFinalUseFutureV2;
pub use runtime_prompt::ContextCompilerRuntimeFinalUseV2;
pub use runtime_prompt::ContextCompilerRuntimeHostErrorV2;
pub use runtime_prompt::ContextCompilerRuntimeHostV2;
pub use runtime_prompt::ContextCompilerRuntimePrepareFutureV2;
pub use runtime_prompt::ContextCompilerRuntimePrepareRequestV2;
pub use runtime_prompt::ContextCompilerRuntimeRecordFutureV2;
pub use runtime_prompt::ContextCompilerRuntimeTerminalV2;
pub use runtime_prompt::PromptRuntimeAttachmentV1;
pub use runtime_prompt::PromptRuntimeDeveloperFragmentV1;
pub use runtime_prompt::PromptRuntimeDispatchFuture;
pub use runtime_prompt::PromptRuntimeDispatchRecordV1;
pub use runtime_prompt::PromptRuntimeError;
pub use runtime_prompt::PromptRuntimeHost;
pub use runtime_prompt::PromptRuntimeHostError;
pub use runtime_prompt::PromptRuntimeMode;
pub use runtime_prompt::PromptRuntimePrepareFuture;
pub use runtime_prompt::PromptRuntimePrepareRequest;
pub use runtime_prompt::PromptRuntimeRecordFuture;
pub use runtime_prompt::PromptRuntimeTerminalOutcomeV1;
pub use runtime_prompt::PromptRuntimeTerminalRecordV1;
pub use runtime_prompt::install_prompt_runtime;
pub use wire::CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2;
pub use wire::CodexOperationIntentWireV2;
pub use wire::WireAdapterError;
pub use wire::adapt_wire_v2;
pub use wire::codex_operation_intent_wire_schema_v2;
pub use wire::decode_codex_operation_intent_wire_v2;
pub use wire::encode_codex_operation_intent_wire_v2;

const MAX_APP_SERVER_VERSION_BYTES: usize = 128;
pub const APP_SERVER_V2_PROTOCOL_ID: &str = "codex.app-server.v2";
pub const TURN_START_METHOD_ID: &str = "turn.start";
pub const TURN_START_RPC_METHOD: &str = "turn/start";
pub const THREAD_READ_RPC_METHOD: &str = "thread/read";
pub const OVERLOADED_ERROR_CODE: i64 = -32_001;
pub const INVALID_REQUEST_ERROR_CODE: i64 = -32_600;
pub const METHOD_NOT_FOUND_ERROR_CODE: i64 = -32_601;
pub const INVALID_PARAMS_ERROR_CODE: i64 = -32_602;
pub const INTERNAL_ERROR_CODE: i64 = -32_603;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AppServerRequestBinding {
    pub source_admission_digest: Digest32,
    pub agent_generation: Generation,
    /// App Server session identity returned by thread/start and bound into the
    /// exact request receipt before turn/start can cross the effect boundary.
    pub session_id: StableId,
    /// Stable product-provided user-message identity used for crash recovery.
    pub client_user_message_id: StableId,
    /// Digest of the exact user input submitted with turn/start.
    pub user_input_digest: Digest32,
    pub protocol_id: StableId,
    pub app_server_version: String,
    pub codex_home_digest: Digest32,
    pub connection_id: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexOperationIntent {
    pub operation_id: StableId,
    pub thread_id: StableId,
    pub method_id: StableId,
    pub payload_digest: Digest32,
    pub lease_payload_digest: Digest32,
    pub deadline_ms: u64,
    pub app_server_binding: Option<AppServerRequestBinding>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TerminalOutcome {
    Completed,
    Failed,
    Interrupted,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptProviderTerminalObservationV1 {
    pub terminal_observed: bool,
    pub observed_provider_request_digest: Digest32,
    pub delivered: bool,
    pub rejected_reason: Option<PromptDeliveryRejectReasonV1>,
    pub observed_token_positions: Option<Vec<u32>>,
    pub truncation_observed: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AdapterStatus {
    Succeeded,
    Failed,
    Interrupted,
    Rejected,
    Overloaded,
    TimedOut,
    Cancelled,
    Indeterminate,
    Quarantined,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetryPosture {
    Never,
    SafeBeforeAdmission,
    ReconcileSameOperation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexAdapterReceipt {
    pub operation_id: StableId,
    pub request_digest: Digest32,
    pub turn_id: Option<StableId>,
    pub correlation_digest: Option<Digest32>,
    pub status: AdapterStatus,
    pub retry_posture: RetryPosture,
    pub response_digest: Option<Digest32>,
    pub model_authority: bool,
    pub provider_authority: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryBoundaryInputV1 {
    pub compilation_id: StableId,
    pub expected_payload_digest: Digest32,
    pub terminal_observed: bool,
    pub delivered: bool,
    pub rejected_reason: Option<PromptDeliveryRejectReasonV1>,
    pub observed_token_positions: Option<Vec<u32>>,
    pub truncation_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    PayloadBindingMismatch,
    DeadlineExpired,
    ProductBindingRequired,
    InvalidAppServerVersion,
    UnsupportedProtocol,
    InvalidObservationIdentity(&'static str),
    CorrelationMismatch(&'static str),
    NonTerminalObservation,
    ObservationEncodingFailed,
    MissingTerminalResponse,
    InvalidPromptDeliveryObservation,
    PromptDeliveryNotTerminal,
    InvalidPromptDeliveryDisposition,
    TokenPositionLimitExceeded,
    NonCanonicalTokenPositions,
    PromptDeliveryContract(PromptDeliveryErrorV1),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for Error {}

pub fn observe_prompt_delivery_v1(
    now_ms: u64,
    intent: &CodexOperationIntent,
    compilation_id: StableId,
    observation: PromptProviderTerminalObservationV1,
) -> Result<PromptDeliveryObservationV1, Error> {
    validate_intent_static(intent)?;
    if now_ms >= intent.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    if !observation.terminal_observed {
        return Err(Error::MissingTerminalResponse);
    }
    if observation.observed_provider_request_digest.is_zero()
        || observation.observed_provider_request_digest != intent.payload_digest
    {
        return Err(Error::PayloadBindingMismatch);
    }
    let result = PromptDeliveryObservationV1 {
        compilation_id,
        provider_request_digest: observation.observed_provider_request_digest,
        delivered: observation.delivered,
        rejected_reason: observation.rejected_reason,
        observed_token_positions: observation.observed_token_positions,
        truncation_observed: observation.truncation_observed,
    };
    result
        .validate()
        .map_err(|_| Error::InvalidPromptDeliveryObservation)?;
    Ok(result)
}

pub fn adapt_request(
    now_ms: u64,
    intent: CodexOperationIntent,
) -> Result<CodexAdapterReceipt, Error> {
    validate_intent_static(&intent)?;
    if now_ms >= intent.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    let request_digest = request_digest(&intent);
    Ok(receipt(
        &intent,
        request_digest,
        None,
        None,
        AdapterStatus::Indeterminate,
        RetryPosture::ReconcileSameOperation,
        None,
    ))
}

pub fn adapt_observed_event(
    intent: &CodexOperationIntent,
    expected_turn_id: &StableId,
    observed: &RemoteAppServerObservedEvent,
) -> Result<Option<CodexAdapterReceipt>, Error> {
    validate_product_transport_binding(
        intent,
        observed.connection_id(),
        observed.server_version(),
        observed.codex_home(),
    )?;
    let AppServerEvent::ServerNotification(notification) = observed.event() else {
        return Ok(None);
    };
    let ServerNotification::TurnCompleted(completed) = notification.as_ref() else {
        return Ok(None);
    };
    adapt_turn_completed(intent, expected_turn_id, completed).map(Some)
}

pub fn adapt_observed_server_rejection(
    intent: &CodexOperationIntent,
    observed: &RemoteAppServerObservedServerError,
) -> Result<CodexAdapterReceipt, Error> {
    validate_product_transport_binding(
        intent,
        observed.connection_id(),
        observed.server_version(),
        observed.codex_home(),
    )?;
    if intent.method_id.as_str() != TURN_START_METHOD_ID
        || observed.method() != TURN_START_RPC_METHOD
    {
        return Err(Error::CorrelationMismatch("method"));
    }
    let request_digest = request_digest(intent);
    let response_digest = server_error_digest(observed.error());
    let (status, retry_posture) = match observed.error().code {
        OVERLOADED_ERROR_CODE => (AdapterStatus::Overloaded, RetryPosture::SafeBeforeAdmission),
        INVALID_REQUEST_ERROR_CODE | METHOD_NOT_FOUND_ERROR_CODE | INVALID_PARAMS_ERROR_CODE => {
            (AdapterStatus::Rejected, RetryPosture::Never)
        }
        // App Server can synthesize an internal error after awaiting Core turn
        // submission. Without a stronger admission-phase witness, that response
        // is accepted-or-unknown and must be reconciled instead of released.
        _ => (
            AdapterStatus::Indeterminate,
            RetryPosture::ReconcileSameOperation,
        ),
    };
    Ok(receipt(
        intent,
        request_digest,
        None,
        None,
        status,
        retry_posture,
        Some(response_digest),
    ))
}

pub fn adapt_observed_thread_read_reconciliation(
    intent: &CodexOperationIntent,
    expected_client_user_message_id: &str,
    expected_input: &[UserInput],
    observed: &RemoteAppServerObservedResponse<ThreadReadResponse>,
) -> Result<Option<CodexAdapterReceipt>, Error> {
    validate_intent_static(intent)?;
    let binding = intent
        .app_server_binding
        .as_ref()
        .ok_or(Error::ProductBindingRequired)?;
    if observed.method() != THREAD_READ_RPC_METHOD {
        return Err(Error::CorrelationMismatch("reconciliation method"));
    }
    if observed.connection_id() == 0 {
        return Err(Error::InvalidObservationIdentity(
            "reconciliation connection",
        ));
    }
    if observed.server_version() != Some(binding.app_server_version.as_str()) {
        return Err(Error::CorrelationMismatch(
            "reconciliation app server version",
        ));
    }
    let observed_home = observed
        .codex_home()
        .ok_or(Error::CorrelationMismatch("reconciliation codex home"))?;
    if Digest32::of_bytes(observed_home.as_bytes()) != binding.codex_home_digest {
        return Err(Error::CorrelationMismatch("reconciliation codex home"));
    }

    let expected_client_id = StableId::new(expected_client_user_message_id.to_string())
        .map_err(|_| Error::InvalidObservationIdentity("reconciliation client user message id"))?;
    if expected_client_id != binding.client_user_message_id {
        return Err(Error::CorrelationMismatch(
            "reconciliation client user message id",
        ));
    }
    let encoded_input =
        serde_json::to_vec(expected_input).map_err(|_| Error::ObservationEncodingFailed)?;
    if Digest32::of_bytes(&encoded_input) != binding.user_input_digest {
        return Err(Error::CorrelationMismatch("reconciliation user input"));
    }

    let response = observed.response();
    if response.thread.id != intent.thread_id.as_str() {
        return Err(Error::CorrelationMismatch("reconciliation thread"));
    }
    if response.thread.session_id != binding.session_id.as_str() {
        return Err(Error::CorrelationMismatch("reconciliation session"));
    }

    let mut matched_turn = None;
    for turn in &response.thread.turns {
        let mut saw_exact = false;
        for item in &turn.items {
            let ThreadItem::UserMessage {
                client_id: Some(client_id),
                content,
                ..
            } = item
            else {
                continue;
            };
            if client_id != expected_client_id.as_str() {
                continue;
            }
            if content.as_slice() != expected_input {
                return Err(Error::CorrelationMismatch("reconciliation user input"));
            }
            if saw_exact {
                return Err(Error::CorrelationMismatch(
                    "reconciliation duplicate user message",
                ));
            }
            saw_exact = true;
        }
        if saw_exact {
            if matched_turn.is_some() {
                return Err(Error::CorrelationMismatch("reconciliation duplicate turn"));
            }
            matched_turn = Some(turn);
        }
    }
    let Some(turn) = matched_turn else {
        return Ok(None);
    };
    let outcome = match turn.status {
        TurnStatus::Completed => TerminalOutcome::Completed,
        TurnStatus::Failed => TerminalOutcome::Failed,
        TurnStatus::Interrupted => TerminalOutcome::Interrupted,
        TurnStatus::InProgress => return Ok(None),
    };
    let turn_id =
        StableId::new(turn.id.clone()).map_err(|_| Error::InvalidObservationIdentity("turn"))?;
    let response_digest = reconciled_turn_response_digest(observed, turn)?;
    let request_digest = request_digest(intent);
    let correlation_digest =
        terminal_correlation_digest(request_digest, &turn_id, outcome, response_digest);
    let status = match outcome {
        TerminalOutcome::Completed => AdapterStatus::Succeeded,
        TerminalOutcome::Failed => AdapterStatus::Failed,
        TerminalOutcome::Interrupted => AdapterStatus::Interrupted,
    };
    let retry_posture = match outcome {
        TerminalOutcome::Interrupted => RetryPosture::ReconcileSameOperation,
        TerminalOutcome::Completed | TerminalOutcome::Failed => RetryPosture::Never,
    };
    Ok(Some(receipt(
        intent,
        request_digest,
        Some(turn_id),
        Some(correlation_digest),
        status,
        retry_posture,
        Some(response_digest),
    )))
}

#[must_use]
pub fn request_digest(intent: &CodexOperationIntent) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.request.v6");
    push_id(&mut bytes, &intent.operation_id);
    push_id(&mut bytes, &intent.thread_id);
    push_id(&mut bytes, &intent.method_id);
    bytes.extend_from_slice(intent.payload_digest.as_array());
    bytes.extend_from_slice(intent.lease_payload_digest.as_array());
    bytes.extend_from_slice(&intent.deadline_ms.to_be_bytes());
    match &intent.app_server_binding {
        None => bytes.push(0),
        Some(binding) => {
            bytes.push(1);
            bytes.extend_from_slice(binding.source_admission_digest.as_array());
            bytes.extend_from_slice(&binding.agent_generation.get().to_be_bytes());
            push_id(&mut bytes, &binding.session_id);
            push_id(&mut bytes, &binding.client_user_message_id);
            bytes.extend_from_slice(binding.user_input_digest.as_array());
            push_id(&mut bytes, &binding.protocol_id);
            push_text(&mut bytes, &binding.app_server_version);
            bytes.extend_from_slice(binding.codex_home_digest.as_array());
            bytes.extend_from_slice(&binding.connection_id.to_be_bytes());
        }
    }
    Digest32::of_bytes(&bytes)
}

fn validate_intent_static(intent: &CodexOperationIntent) -> Result<(), Error> {
    for (label, digest) in [
        ("payload", intent.payload_digest),
        ("lease payload", intent.lease_payload_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(label));
        }
    }
    if intent.method_id.as_str() == TURN_START_METHOD_ID {
        validate_app_server_binding(intent)?;
    }
    Ok(())
}

fn validate_app_server_binding(intent: &CodexOperationIntent) -> Result<(), Error> {
    let binding = intent
        .app_server_binding
        .as_ref()
        .ok_or(Error::ProductBindingRequired)?;
    if binding.source_admission_digest.is_zero()
        || binding.user_input_digest.is_zero()
        || binding.codex_home_digest.is_zero()
        || binding.connection_id == 0
    {
        return Err(Error::EmptyDigest("app server binding"));
    }
    if binding.protocol_id.as_str() != APP_SERVER_V2_PROTOCOL_ID {
        return Err(Error::UnsupportedProtocol);
    }
    if binding.app_server_version.is_empty()
        || binding.app_server_version.len() > MAX_APP_SERVER_VERSION_BYTES
        || binding.app_server_version.as_bytes().contains(&0)
    {
        return Err(Error::InvalidAppServerVersion);
    }
    Ok(())
}

fn validate_product_transport_binding(
    intent: &CodexOperationIntent,
    connection_id: u64,
    server_version: Option<&str>,
    codex_home: Option<&str>,
) -> Result<(), Error> {
    validate_intent_static(intent)?;
    let binding = intent
        .app_server_binding
        .as_ref()
        .ok_or(Error::ProductBindingRequired)?;
    if connection_id != binding.connection_id {
        return Err(Error::CorrelationMismatch("connection"));
    }
    if server_version != Some(binding.app_server_version.as_str()) {
        return Err(Error::CorrelationMismatch("app server version"));
    }
    let observed_home = codex_home.ok_or(Error::CorrelationMismatch("codex home"))?;
    if Digest32::of_bytes(observed_home.as_bytes()) != binding.codex_home_digest {
        return Err(Error::CorrelationMismatch("codex home"));
    }
    Ok(())
}

fn adapt_turn_completed(
    intent: &CodexOperationIntent,
    expected_turn_id: &StableId,
    completed: &TurnCompletedNotification,
) -> Result<CodexAdapterReceipt, Error> {
    let observed_turn_id = StableId::new(completed.turn.id.clone())
        .map_err(|_| Error::InvalidObservationIdentity("turn"))?;
    if &observed_turn_id != expected_turn_id {
        return Err(Error::CorrelationMismatch("turn"));
    }
    let outcome = match completed.turn.status {
        TurnStatus::Completed => TerminalOutcome::Completed,
        TurnStatus::Failed => TerminalOutcome::Failed,
        TurnStatus::Interrupted => TerminalOutcome::Interrupted,
        TurnStatus::InProgress => return Err(Error::NonTerminalObservation),
    };
    let response_digest = terminal_response_digest(completed)?;
    let request_digest = request_digest(intent);
    let correlation_digest =
        terminal_correlation_digest(request_digest, &observed_turn_id, outcome, response_digest);
    let status = match outcome {
        TerminalOutcome::Completed => AdapterStatus::Succeeded,
        TerminalOutcome::Failed => AdapterStatus::Failed,
        TerminalOutcome::Interrupted => AdapterStatus::Interrupted,
    };
    let retry_posture = match outcome {
        TerminalOutcome::Interrupted => RetryPosture::ReconcileSameOperation,
        TerminalOutcome::Completed | TerminalOutcome::Failed => RetryPosture::Never,
    };
    Ok(receipt(
        intent,
        request_digest,
        Some(observed_turn_id),
        Some(correlation_digest),
        status,
        retry_posture,
        Some(response_digest),
    ))
}

fn terminal_response_digest(completed: &TurnCompletedNotification) -> Result<Digest32, Error> {
    let bytes = serde_json::to_vec(&completed.turn).map_err(|_| Error::ObservationEncodingFailed)?;
    Ok(Digest32::of_bytes(&bytes))
}

fn reconciled_turn_response_digest(
    observed: &RemoteAppServerObservedResponse<ThreadReadResponse>,
    turn: &codex_app_server_protocol::Thread,
) -> Result<Digest32, Error> {
    let mut bytes = b"hepta.codex.adapter.reconciled-turn.v1".to_vec();
    push_text(&mut bytes, observed.method());
    push_text(&mut bytes, observed.server_version().unwrap_or_default());
    push_text(&mut bytes, observed.codex_home().unwrap_or_default());
    bytes.extend_from_slice(&observed.connection_id().to_be_bytes());
    bytes.extend_from_slice(
        &serde_json::to_vec(turn).map_err(|_| Error::ObservationEncodingFailed)?,
    );
    Ok(Digest32::of_bytes(&bytes))
}

fn server_error_digest(error: &JSONRPCErrorError) -> Digest32 {
    let mut bytes = b"hepta.codex.adapter.server-error.v1".to_vec();
    bytes.extend_from_slice(&error.code.to_be_bytes());
    push_text(&mut bytes, &error.message);
    match &error.data {
        None => bytes.push(0),
        Some(data) => {
            bytes.push(1);
            bytes.extend_from_slice(&serde_json::to_vec(data).unwrap_or_default());
        }
    }
    Digest32::of_bytes(&bytes)
}

fn terminal_correlation_digest(
    request_digest: Digest32,
    turn_id: &StableId,
    outcome: TerminalOutcome,
    response_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.codex.adapter.terminal.v3".to_vec();
    bytes.extend_from_slice(request_digest.as_array());
    push_id(&mut bytes, turn_id);
    bytes.push(match outcome {
        TerminalOutcome::Completed => 0,
        TerminalOutcome::Failed => 1,
        TerminalOutcome::Interrupted => 2,
    });
    bytes.extend_from_slice(response_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn receipt(
    intent: &CodexOperationIntent,
    request_digest: Digest32,
    turn_id: Option<StableId>,
    correlation_digest: Option<Digest32>,
    status: AdapterStatus,
    retry_posture: RetryPosture,
    response_digest: Option<Digest32>,
) -> CodexAdapterReceipt {
    CodexAdapterReceipt {
        operation_id: intent.operation_id.clone(),
        request_digest,
        turn_id,
        correlation_digest,
        status,
        retry_posture,
        response_digest,
        model_authority: false,
        provider_authority: false,
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    push_text(bytes, id.as_str());
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
