//! Exact-bound Codex App Server execution adapter.
//!
//! This crate does not execute a model and does not mint authority. It turns
//! typed App Server observations into a correlation-checked receipt that is
//! safe for a host-owned durable control plane to persist.
//!
//! Important invariants:
//! - `turn/completed` status is preserved exactly: completed, failed and
//!   interrupted never collapse into one success bit.
//! - thread, optional turn, protocol version and Agent/session generation are
//!   bound into the request digest and rechecked against observations.
//! - overload is a proven pre-admission rejection and is the only transport
//!   outcome marked safe for bounded backoff retry.
//! - timeout, disconnect and missing acknowledgement remain indeterminate and
//!   require reconciliation before any semantic replay.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;

use codex_app_server_client::AppServerEvent;
use codex_app_server_client::ObservedAppServerEvent;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnStatus;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub const APP_SERVER_V2_PROTOCOL_ID: &str = "codex.app-server.v2";
pub const APP_SERVER_OVERLOADED_ERROR_CODE: i64 = -32001;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexOperationIntent {
    pub operation_id: StableId,
    pub thread_id: StableId,
    /// None is valid only before `turn/start` returns a concrete turn.
    pub turn_id: Option<StableId>,
    pub method_id: StableId,
    pub protocol_version: StableId,
    pub session_generation: u64,
    pub payload_digest: Digest32,
    pub lease_payload_digest: Digest32,
    pub deadline_ms: u64,
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
    Unavailable,
    TimedOut,
    Indeterminate,
    Quarantined,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetryDisposition {
    Never,
    /// The App Server rejected before request admission. Retry must still be
    /// bounded and back off, but it cannot duplicate an admitted turn.
    BackoffSafe,
    /// The effect may have happened. Reconcile the exact operation before any
    /// new semantic dispatch.
    ReconcileBeforeRetry,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ObservationKind {
    Terminal(TerminalOutcome),
    Rejected,
    Overloaded,
    Unavailable,
    TimedOut,
    Indeterminate,
    Quarantined,
}

/// Opaque observation witness. Callers cannot directly set its fields.
///
/// This prevents the previous `terminal_observed: bool` footgun. Authenticity
/// still comes from the trusted App Server client/event stream owned by the
/// host; this type is a structural witness, not a cryptographic signature.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AppServerObservation {
    thread_id: StableId,
    turn_id: Option<StableId>,
    protocol_version: StableId,
    session_generation: u64,
    event_sequence: u64,
    kind: ObservationKind,
    response_digest: Option<Digest32>,
}

impl AppServerObservation {
    /// Converts only a transport-observed event into a terminal witness.
    ///
    /// A caller can construct protocol structs, but it cannot construct
    /// `ObservedAppServerEvent`; only `RemoteAppServerClient` can mint one
    /// while dequeuing its initialized connection.
    pub fn from_observed_event(
        protocol_version: StableId,
        session_generation: u64,
        observed: &ObservedAppServerEvent,
    ) -> Result<Option<Self>, Error> {
        match observed.event() {
            AppServerEvent::ServerNotification(notification) => match notification.as_ref() {
                codex_app_server_protocol::ServerNotification::TurnCompleted(completed) => {
                    Self::from_turn_completed(
                        protocol_version,
                        session_generation,
                        observed.sequence(),
                        completed,
                    )
                    .map(Some)
                }
                _ => Ok(None),
            },
            _ => Ok(None),
        }
    }

    fn from_turn_completed(
        protocol_version: StableId,
        session_generation: u64,
        event_sequence: u64,
        notification: &TurnCompletedNotification,
    ) -> Result<Self, Error> {
        validate_observation_coordinates(session_generation, event_sequence)?;
        let thread_id = stable_id(&notification.thread_id, "observation thread")?;
        let turn_id = stable_id(&notification.turn.id, "observation turn")?;
        let outcome = match notification.turn.status {
            TurnStatus::Completed => TerminalOutcome::Completed,
            TurnStatus::Failed => TerminalOutcome::Failed,
            TurnStatus::Interrupted => TerminalOutcome::Interrupted,
            TurnStatus::InProgress => return Err(Error::NonTerminalCompletion),
        };
        let response_digest = terminal_response_digest(notification, outcome);
        Ok(Self {
            thread_id,
            turn_id: Some(turn_id),
            protocol_version,
            session_generation,
            event_sequence,
            kind: ObservationKind::Terminal(outcome),
            response_digest: Some(response_digest),
        })
    }

    pub fn from_rpc_error(
        thread_id: StableId,
        turn_id: Option<StableId>,
        protocol_version: StableId,
        session_generation: u64,
        event_sequence: u64,
        error: &JSONRPCErrorError,
    ) -> Result<Self, Error> {
        validate_observation_coordinates(session_generation, event_sequence)?;
        let kind = match error.code {
            APP_SERVER_OVERLOADED_ERROR_CODE => ObservationKind::Overloaded,
            // JSON-RPC request/method/parameter rejection is established before
            // a valid turn can be admitted. Internal/custom server failures do
            // not carry that guarantee and remain indeterminate.
            -32602..=-32600 => ObservationKind::Rejected,
            _ => ObservationKind::Indeterminate,
        };
        Ok(Self {
            thread_id,
            turn_id,
            protocol_version,
            session_generation,
            event_sequence,
            kind,
            response_digest: Some(rpc_error_digest(error)),
        })
    }

    pub fn timed_out(
        thread_id: StableId,
        turn_id: Option<StableId>,
        protocol_version: StableId,
        session_generation: u64,
        event_sequence: u64,
    ) -> Result<Self, Error> {
        Self::nonterminal(
            thread_id,
            turn_id,
            protocol_version,
            session_generation,
            event_sequence,
            ObservationKind::TimedOut,
        )
    }

    pub fn unavailable(
        thread_id: StableId,
        turn_id: Option<StableId>,
        protocol_version: StableId,
        session_generation: u64,
        event_sequence: u64,
    ) -> Result<Self, Error> {
        Self::nonterminal(
            thread_id,
            turn_id,
            protocol_version,
            session_generation,
            event_sequence,
            ObservationKind::Unavailable,
        )
    }

    pub fn indeterminate(
        thread_id: StableId,
        turn_id: Option<StableId>,
        protocol_version: StableId,
        session_generation: u64,
        event_sequence: u64,
    ) -> Result<Self, Error> {
        Self::nonterminal(
            thread_id,
            turn_id,
            protocol_version,
            session_generation,
            event_sequence,
            ObservationKind::Indeterminate,
        )
    }

    pub fn quarantined(
        thread_id: StableId,
        turn_id: Option<StableId>,
        protocol_version: StableId,
        session_generation: u64,
        event_sequence: u64,
    ) -> Result<Self, Error> {
        Self::nonterminal(
            thread_id,
            turn_id,
            protocol_version,
            session_generation,
            event_sequence,
            ObservationKind::Quarantined,
        )
    }

    fn nonterminal(
        thread_id: StableId,
        turn_id: Option<StableId>,
        protocol_version: StableId,
        session_generation: u64,
        event_sequence: u64,
        kind: ObservationKind,
    ) -> Result<Self, Error> {
        validate_observation_coordinates(session_generation, event_sequence)?;
        Ok(Self {
            thread_id,
            turn_id,
            protocol_version,
            session_generation,
            event_sequence,
            kind,
            response_digest: None,
        })
    }

    pub fn event_sequence(&self) -> u64 {
        self.event_sequence
    }

    pub fn terminal_outcome(&self) -> Option<TerminalOutcome> {
        match self.kind {
            ObservationKind::Terminal(outcome) => Some(outcome),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexAdapterReceipt {
    pub operation_id: StableId,
    pub request_digest: Digest32,
    pub status: AdapterStatus,
    pub retry: RetryDisposition,
    pub response_digest: Option<Digest32>,
    pub terminal_outcome: Option<TerminalOutcome>,
    pub event_sequence: Option<u64>,
    pub model_authority: bool,
    pub provider_authority: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    PayloadBindingMismatch,
    DeadlineExpired,
    InvalidGeneration,
    InvalidSequence,
    InvalidObservationIdentity(&'static str),
    CorrelationMismatch(&'static str),
    NonTerminalCompletion,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn validate_for_dispatch(
    now_ms: u64,
    intent: &CodexOperationIntent,
) -> Result<(), Error> {
    validate_intent_binding(intent)?;
    if now_ms >= intent.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    Ok(())
}

/// Maps an observed App Server fact. A late terminal observation is still a
/// fact and must remain recordable after the original dispatch deadline; the
/// deadline gates dispatch through `validate_for_dispatch`, not reconciliation.
pub fn adapt(
    _now_ms: u64,
    intent: CodexOperationIntent,
    observation: Option<AppServerObservation>,
) -> Result<CodexAdapterReceipt, Error> {
    validate_intent_binding(&intent)?;

    let request_digest = request_digest(&intent);
    let (status, retry, response_digest, terminal_outcome, event_sequence) =
        match observation {
            None => (
                AdapterStatus::Indeterminate,
                RetryDisposition::ReconcileBeforeRetry,
                None,
                None,
                None,
            ),
            Some(value) => {
                validate_correlation(&intent, &value)?;
                let terminal_outcome = value.terminal_outcome();
                let (status, retry) = match value.kind {
                    ObservationKind::Terminal(TerminalOutcome::Completed) => {
                        (AdapterStatus::Succeeded, RetryDisposition::Never)
                    }
                    ObservationKind::Terminal(TerminalOutcome::Failed) => {
                        (AdapterStatus::Failed, RetryDisposition::Never)
                    }
                    ObservationKind::Terminal(TerminalOutcome::Interrupted) => {
                        (AdapterStatus::Interrupted, RetryDisposition::Never)
                    }
                    ObservationKind::Rejected => {
                        (AdapterStatus::Rejected, RetryDisposition::Never)
                    }
                    ObservationKind::Overloaded => {
                        (AdapterStatus::Overloaded, RetryDisposition::BackoffSafe)
                    }
                    ObservationKind::Unavailable => (
                        AdapterStatus::Unavailable,
                        RetryDisposition::ReconcileBeforeRetry,
                    ),
                    ObservationKind::TimedOut => (
                        AdapterStatus::TimedOut,
                        RetryDisposition::ReconcileBeforeRetry,
                    ),
                    ObservationKind::Indeterminate => (
                        AdapterStatus::Indeterminate,
                        RetryDisposition::ReconcileBeforeRetry,
                    ),
                    ObservationKind::Quarantined => (
                        AdapterStatus::Quarantined,
                        RetryDisposition::ReconcileBeforeRetry,
                    ),
                };
                (
                    status,
                    retry,
                    value.response_digest,
                    terminal_outcome,
                    Some(value.event_sequence),
                )
            }
        };

    Ok(CodexAdapterReceipt {
        operation_id: intent.operation_id,
        request_digest,
        status,
        retry,
        response_digest,
        terminal_outcome,
        event_sequence,
        model_authority: false,
        provider_authority: false,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[must_use]
pub fn request_digest(intent: &CodexOperationIntent) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.request.v2");
    push_id(&mut bytes, &intent.operation_id);
    push_id(&mut bytes, &intent.thread_id);
    push_optional_id(&mut bytes, intent.turn_id.as_ref());
    push_id(&mut bytes, &intent.method_id);
    push_id(&mut bytes, &intent.protocol_version);
    bytes.extend_from_slice(&intent.session_generation.to_be_bytes());
    bytes.extend_from_slice(intent.payload_digest.as_array());
    bytes.extend_from_slice(&intent.deadline_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn validate_intent_binding(intent: &CodexOperationIntent) -> Result<(), Error> {
    if intent.payload_digest.is_zero() || intent.lease_payload_digest.is_zero() {
        return Err(Error::EmptyDigest("payload"));
    }
    if intent.payload_digest != intent.lease_payload_digest {
        return Err(Error::PayloadBindingMismatch);
    }
    if intent.session_generation == 0 {
        return Err(Error::InvalidGeneration);
    }
    Ok(())
}

fn validate_correlation(
    intent: &CodexOperationIntent,
    observation: &AppServerObservation,
) -> Result<(), Error> {
    if observation.thread_id != intent.thread_id {
        return Err(Error::CorrelationMismatch("thread"));
    }
    if let Some(expected_turn) = intent.turn_id.as_ref()
        && observation.turn_id.as_ref() != Some(expected_turn)
    {
        return Err(Error::CorrelationMismatch("turn"));
    }
    if observation.protocol_version != intent.protocol_version {
        return Err(Error::CorrelationMismatch("protocol"));
    }
    if observation.session_generation != intent.session_generation {
        return Err(Error::CorrelationMismatch("generation"));
    }
    if matches!(observation.kind, ObservationKind::Terminal(_)) && observation.turn_id.is_none() {
        return Err(Error::CorrelationMismatch("terminal turn"));
    }
    Ok(())
}

fn validate_observation_coordinates(
    session_generation: u64,
    event_sequence: u64,
) -> Result<(), Error> {
    if session_generation == 0 {
        return Err(Error::InvalidGeneration);
    }
    if event_sequence == 0 {
        return Err(Error::InvalidSequence);
    }
    Ok(())
}

fn terminal_response_digest(
    notification: &TurnCompletedNotification,
    outcome: TerminalOutcome,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.terminal.v2");
    push_raw(&mut bytes, notification.thread_id.as_bytes());
    push_raw(&mut bytes, notification.turn.id.as_bytes());
    bytes.push(match outcome {
        TerminalOutcome::Completed => 0,
        TerminalOutcome::Failed => 1,
        TerminalOutcome::Interrupted => 2,
    });
    if let Some(error) = notification.turn.error.as_ref() {
        bytes.push(1);
        push_raw(&mut bytes, error.message.as_bytes());
    } else {
        bytes.push(0);
    }
    if let Some(started_at) = notification.turn.started_at {
        bytes.push(1);
        bytes.extend_from_slice(&started_at.to_be_bytes());
    } else {
        bytes.push(0);
    }
    if let Some(completed_at) = notification.turn.completed_at {
        bytes.push(1);
        bytes.extend_from_slice(&completed_at.to_be_bytes());
    } else {
        bytes.push(0);
    }
    if let Some(duration_ms) = notification.turn.duration_ms {
        bytes.push(1);
        bytes.extend_from_slice(&duration_ms.to_be_bytes());
    } else {
        bytes.push(0);
    }
    Digest32::of_bytes(&bytes)
}

fn rpc_error_digest(error: &JSONRPCErrorError) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.rpc-error.v2");
    bytes.extend_from_slice(&error.code.to_be_bytes());
    push_raw(&mut bytes, error.message.as_bytes());
    if let Some(data) = error.data.as_ref() {
        bytes.push(1);
        push_raw(&mut bytes, data.to_string().as_bytes());
    } else {
        bytes.push(0);
    }
    Digest32::of_bytes(&bytes)
}

fn stable_id(value: &str, field: &'static str) -> Result<StableId, Error> {
    StableId::new(value.to_string()).map_err(|_| Error::InvalidObservationIdentity(field))
}

fn push_optional_id(bytes: &mut Vec<u8>, value: Option<&StableId>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_id(bytes, value);
        }
        None => bytes.push(0),
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_raw(bytes, value.as_str().as_bytes());
}

fn push_raw(bytes: &mut Vec<u8>, raw: &[u8]) {
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "deadline_digest_tests.rs"]
mod deadline_digest_tests;
