//! Exact-bound Codex App Server request and observation adapter.
//!
//! Product terminality and retry-safe server rejection require process-local
//! evidence produced by the exact RemoteAppServerClient connection. A plain
//! protocol DTO or wire decode cannot be promoted into terminal success.

#![forbid(unsafe_code)]

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
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnStatus;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

mod wire;

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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AppServerRequestBinding {
    pub source_admission_digest: Digest32,
    pub agent_generation: Generation,
    /// App Server session identity returned by thread/start and bound into the
    /// exact request receipt before turn/start can cross the effect boundary.
    pub session_id: StableId,
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
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for Error {}

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
    let (status, retry_posture) = if observed.error().code == OVERLOADED_ERROR_CODE {
        (AdapterStatus::Overloaded, RetryPosture::SafeBeforeAdmission)
    } else {
        (AdapterStatus::Rejected, RetryPosture::Never)
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
    expected_turn_start: &TurnStartParams,
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

    let encoded_turn_start = serde_json::to_vec(expected_turn_start)
        .map_err(|_| Error::ObservationEncodingFailed)?;
    if Digest32::of_bytes(&encoded_turn_start) != intent.payload_digest {
        return Err(Error::CorrelationMismatch(
            "reconciliation turn/start payload",
        ));
    }
    if expected_turn_start.thread_id != intent.thread_id.as_str() {
        return Err(Error::CorrelationMismatch("reconciliation thread"));
    }
    let expected_client_id = expected_turn_start
        .client_user_message_id
        .as_deref()
        .filter(|value| !value.is_empty())
        .ok_or(Error::CorrelationMismatch(
            "reconciliation client user message id",
        ))?;

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
            if client_id != expected_client_id {
                continue;
            }
            if content != &expected_turn_start.input {
                return Err(Error::CorrelationMismatch(
                    "reconciliation user input",
                ));
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
                return Err(Error::CorrelationMismatch(
                    "reconciliation duplicate turn",
                ));
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
    let turn_id = StableId::new(turn.id.clone())
        .map_err(|_| Error::InvalidObservationIdentity("turn"))?;
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
    bytes.extend_from_slice(b"hepta.codex.adapter.request.v5");
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
            push_id(&mut bytes, &binding.protocol_id);
            push_text(&mut bytes, &binding.app_server_version);
            bytes.extend_from_slice(binding.codex_home_digest.as_array());
            bytes.extend_from_slice(&binding.connection_id.to_be_bytes());
        }
    }
    Digest32::of_bytes(&bytes)
}

fn adapt_turn_completed(
    intent: &CodexOperationIntent,
    expected_turn_id: &StableId,
    notification: &TurnCompletedNotification,
) -> Result<CodexAdapterReceipt, Error> {
    validate_intent_static(intent)?;
    let thread_id = StableId::new(notification.thread_id.clone())
        .map_err(|_| Error::InvalidObservationIdentity("thread"))?;
    let turn_id = StableId::new(notification.turn.id.clone())
        .map_err(|_| Error::InvalidObservationIdentity("turn"))?;
    if thread_id != intent.thread_id {
        return Err(Error::CorrelationMismatch("thread"));
    }
    if &turn_id != expected_turn_id {
        return Err(Error::CorrelationMismatch("turn"));
    }
    let outcome = match &notification.turn.status {
        TurnStatus::Completed => TerminalOutcome::Completed,
        TurnStatus::Failed => TerminalOutcome::Failed,
        TurnStatus::Interrupted => TerminalOutcome::Interrupted,
        TurnStatus::InProgress => return Err(Error::NonTerminalObservation),
    };
    let encoded = serde_json::to_vec(notification).map_err(|_| Error::ObservationEncodingFailed)?;
    let response_digest = Digest32::of_bytes(&encoded);
    if response_digest.is_zero() {
        return Err(Error::EmptyDigest("terminal response"));
    }
    let status = match outcome {
        TerminalOutcome::Completed => AdapterStatus::Succeeded,
        TerminalOutcome::Failed => AdapterStatus::Failed,
        TerminalOutcome::Interrupted => AdapterStatus::Interrupted,
    };
    let retry_posture = match outcome {
        TerminalOutcome::Interrupted => RetryPosture::ReconcileSameOperation,
        TerminalOutcome::Completed | TerminalOutcome::Failed => RetryPosture::Never,
    };
    let request_digest = request_digest(intent);
    let correlation_digest =
        terminal_correlation_digest(request_digest, &turn_id, outcome, response_digest);
    Ok(receipt(
        intent,
        request_digest,
        Some(turn_id),
        Some(correlation_digest),
        status,
        retry_posture,
        Some(response_digest),
    ))
}

fn validate_intent_static(intent: &CodexOperationIntent) -> Result<(), Error> {
    if intent.payload_digest.is_zero() || intent.lease_payload_digest.is_zero() {
        return Err(Error::EmptyDigest("payload"));
    }
    if intent.payload_digest != intent.lease_payload_digest {
        return Err(Error::PayloadBindingMismatch);
    }
    if intent.deadline_ms == 0 {
        return Err(Error::DeadlineExpired);
    }
    if let Some(binding) = &intent.app_server_binding {
        if binding.source_admission_digest.is_zero() {
            return Err(Error::EmptyDigest("source admission"));
        }
        if binding.codex_home_digest.is_zero() {
            return Err(Error::EmptyDigest("codex home"));
        }
        if binding.connection_id == 0 {
            return Err(Error::InvalidObservationIdentity("connection"));
        }
        if binding.protocol_id.as_str() != APP_SERVER_V2_PROTOCOL_ID {
            return Err(Error::UnsupportedProtocol);
        }
        if binding.app_server_version.is_empty()
            || binding.app_server_version.len() > MAX_APP_SERVER_VERSION_BYTES
            || binding
                .app_server_version
                .bytes()
                .any(|b| b.is_ascii_control())
        {
            return Err(Error::InvalidAppServerVersion);
        }
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
    let codex_home = codex_home.ok_or(Error::CorrelationMismatch("codex home"))?;
    if Digest32::of_bytes(codex_home.as_bytes()) != binding.codex_home_digest {
        return Err(Error::CorrelationMismatch("codex home"));
    }
    Ok(())
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

fn terminal_correlation_digest(
    request_digest: Digest32,
    turn_id: &StableId,
    outcome: TerminalOutcome,
    response_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.terminal-correlation.v2");
    bytes.extend_from_slice(request_digest.as_array());
    push_id(&mut bytes, turn_id);
    bytes.push(match outcome {
        TerminalOutcome::Completed => 1,
        TerminalOutcome::Failed => 2,
        TerminalOutcome::Interrupted => 3,
    });
    bytes.extend_from_slice(response_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn reconciled_turn_response_digest(
    observed: &RemoteAppServerObservedResponse<ThreadReadResponse>,
    turn: &codex_app_server_protocol::Turn,
) -> Result<Digest32, Error> {
    let encoded_turn =
        serde_json::to_vec(turn).map_err(|_| Error::ObservationEncodingFailed)?;
    let encoded_request_id = serde_json::to_vec(observed.request_id())
        .map_err(|_| Error::ObservationEncodingFailed)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.reconciled-turn.v1");
    push_text(&mut bytes, observed.method());
    push_bytes(&mut bytes, &encoded_request_id);
    bytes.extend_from_slice(&observed.connection_id().to_be_bytes());
    push_text(
        &mut bytes,
        observed
            .server_version()
            .ok_or(Error::CorrelationMismatch(
                "reconciliation app server version",
            ))?,
    );
    push_text(
        &mut bytes,
        observed
            .codex_home()
            .ok_or(Error::CorrelationMismatch("reconciliation codex home"))?,
    );
    push_bytes(&mut bytes, &encoded_turn);
    Ok(Digest32::of_bytes(&bytes))
}

fn server_error_digest(error: &JSONRPCErrorError) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.server-error.v1");
    bytes.extend_from_slice(&error.code.to_be_bytes());
    push_text(&mut bytes, &error.message);
    if let Some(data) = &error.data
        && let Ok(encoded) = serde_json::to_vec(data)
    {
        push_bytes(&mut bytes, &encoded);
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_bytes(bytes, value.as_str().as_bytes());
}
fn push_text(bytes: &mut Vec<u8>, value: &str) {
    push_bytes(bytes, value.as_bytes());
}
fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) {
    let length = u32::try_from(value.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value);
}

#[cfg(test)]
#[path = "deadline_digest_tests.rs"]
mod deadline_digest_tests;
#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
