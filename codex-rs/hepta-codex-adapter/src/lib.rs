//! Exact-bound Codex App Server request/observation adapter.
//!
//! The adapter binds one already-authorized request to the owning App Server
//! session/thread/generation/protocol tuple and converts typed App Server
//! outcomes into durable, non-authorizing receipts. It never mints model,
//! provider, tool, external-effect, promotion, or release authority.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;

use codex_app_server_protocol::CodexErrorInfo;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnStatus;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub const APP_SERVER_PROTOCOL_V2: u16 = 2;
pub const TURN_START_METHOD_ID: &str = "turn:start";
pub const OVERLOADED_ERROR_CODE: i64 = -32001;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexOperationIntent {
    pub operation_id: StableId,
    pub session_id: StableId,
    pub thread_id: StableId,
    pub method_id: StableId,
    pub payload_digest: Digest32,
    pub lease_payload_digest: Digest32,
    pub owner_generation: u64,
    pub protocol_version: u16,
    pub deadline_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TerminalOutcome {
    Completed,
    Failed,
    Interrupted,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FailureKind {
    ContextWindowExceeded,
    SessionBudgetExceeded,
    UsageLimitExceeded,
    ServerOverloaded,
    CyberPolicy,
    MisalignmentPolicyViolation,
    HttpConnectionFailed,
    ResponseStreamConnectionFailed,
    InternalServerError,
    Unauthorized,
    BadRequest,
    ThreadRollbackFailed,
    SandboxError,
    ResponseStreamDisconnected,
    ResponseTooManyFailedAttempts,
    ActiveTurnNotSteerable,
    JsonRpcRejected,
    Other,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObservationKind {
    Terminal(TerminalOutcome),
    RequestRejected,
    TimedOut,
    TransportLost,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AdapterStatus {
    Succeeded,
    Failed,
    Interrupted,
    Rejected,
    Overloaded,
    TimedOut,
    Unavailable,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReplayDisposition {
    /// The App Server returned a definitive request-level rejection before a
    /// turn was admitted. Re-issuing a new request cannot duplicate that turn.
    SafeToRetry,
    /// A request may have crossed the effect boundary. Reconcile the exact
    /// operation/turn before considering any new dispatch.
    ReconcileOnly,
    /// A terminal turn was observed; a new turn would be a distinct effect.
    NotRetryable,
}

/// Opaque, exact-request-bound observation.
///
/// Fields are deliberately private: callers cannot set a boolean terminal bit
/// or inject a response digest directly. Construction goes through typed App
/// Server protocol outcomes or explicit local transport observations.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AppServerObservation {
    request_digest: Digest32,
    kind: ObservationKind,
    turn_id: Option<StableId>,
    response_digest: Option<Digest32>,
    failure_kind: Option<FailureKind>,
}

impl AppServerObservation {
    pub fn from_turn_completed(
        intent: &CodexOperationIntent,
        expected_turn_id: &StableId,
        notification: &TurnCompletedNotification,
    ) -> Result<Self, Error> {
        let request_digest = request_digest(intent)?;
        let notification_thread = StableId::new(notification.thread_id.clone())
            .map_err(|_| Error::InvalidIdentity("thread"))?;
        let notification_turn = StableId::new(notification.turn.id.clone())
            .map_err(|_| Error::InvalidIdentity("turn"))?;
        if notification_thread != intent.thread_id {
            return Err(Error::CorrelationMismatch("thread"));
        }
        if &notification_turn != expected_turn_id {
            return Err(Error::CorrelationMismatch("turn"));
        }

        let (outcome, failure_kind) = match notification.turn.status {
            TurnStatus::Completed => (TerminalOutcome::Completed, None),
            TurnStatus::Failed => (
                TerminalOutcome::Failed,
                notification
                    .turn
                    .error
                    .as_ref()
                    .and_then(|error| error.codex_error_info.as_ref())
                    .map(FailureKind::from_codex),
            ),
            TurnStatus::Interrupted => (TerminalOutcome::Interrupted, None),
            TurnStatus::InProgress => return Err(Error::NonTerminalCompletion),
        };
        let response_digest = terminal_response_digest(
            &notification_thread,
            &notification_turn,
            outcome,
            failure_kind,
            notification
                .turn
                .error
                .as_ref()
                .map(|error| error.message.as_str()),
        );
        Ok(Self {
            request_digest,
            kind: ObservationKind::Terminal(outcome),
            turn_id: Some(notification_turn),
            response_digest: Some(response_digest),
            failure_kind,
        })
    }

    pub fn from_request_error(
        intent: &CodexOperationIntent,
        error: &JSONRPCErrorError,
    ) -> Result<Self, Error> {
        let request_digest = request_digest(intent)?;
        if intent.method_id.as_str() != TURN_START_METHOD_ID {
            return Err(Error::UnsupportedRequestObservation);
        }
        let failure_kind = if error.code == OVERLOADED_ERROR_CODE {
            FailureKind::ServerOverloaded
        } else {
            FailureKind::JsonRpcRejected
        };
        let response_digest = request_error_digest(error.code, &error.message, failure_kind);
        Ok(Self {
            request_digest,
            kind: ObservationKind::RequestRejected,
            turn_id: None,
            response_digest: Some(response_digest),
            failure_kind: Some(failure_kind),
        })
    }

    pub fn timed_out(intent: &CodexOperationIntent) -> Result<Self, Error> {
        Ok(Self {
            request_digest: request_digest(intent)?,
            kind: ObservationKind::TimedOut,
            turn_id: None,
            response_digest: None,
            failure_kind: None,
        })
    }

    pub fn transport_lost(intent: &CodexOperationIntent) -> Result<Self, Error> {
        Ok(Self {
            request_digest: request_digest(intent)?,
            kind: ObservationKind::TransportLost,
            turn_id: None,
            response_digest: None,
            failure_kind: None,
        })
    }

    pub const fn kind(&self) -> ObservationKind {
        self.kind
    }

    pub fn turn_id(&self) -> Option<&StableId> {
        self.turn_id.as_ref()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexAdapterReceipt {
    pub operation_id: StableId,
    pub session_id: StableId,
    pub thread_id: StableId,
    pub turn_id: Option<StableId>,
    pub request_digest: Digest32,
    pub receipt_digest: Digest32,
    pub status: AdapterStatus,
    pub replay: ReplayDisposition,
    pub response_digest: Option<Digest32>,
    pub failure_kind: Option<FailureKind>,
    pub model_authority: bool,
    pub provider_authority: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    PayloadBindingMismatch,
    InvalidOwnerGeneration,
    UnsupportedProtocol(u16),
    InvalidIdentity(&'static str),
    CorrelationMismatch(&'static str),
    ObservationBindingMismatch,
    NonTerminalCompletion,
    UnsupportedRequestObservation,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn adapt(
    now_ms: u64,
    intent: CodexOperationIntent,
    observation: Option<AppServerObservation>,
) -> Result<CodexAdapterReceipt, Error> {
    let request_digest = request_digest(&intent)?;
    if observation
        .as_ref()
        .is_some_and(|value| value.request_digest != request_digest)
    {
        return Err(Error::ObservationBindingMismatch);
    }

    let (status, replay, turn_id, response_digest, failure_kind) = match observation {
        Some(value) => match value.kind {
            ObservationKind::Terminal(TerminalOutcome::Completed) => (
                AdapterStatus::Succeeded,
                ReplayDisposition::NotRetryable,
                value.turn_id,
                value.response_digest,
                value.failure_kind,
            ),
            ObservationKind::Terminal(TerminalOutcome::Failed) => (
                AdapterStatus::Failed,
                ReplayDisposition::NotRetryable,
                value.turn_id,
                value.response_digest,
                value.failure_kind,
            ),
            ObservationKind::Terminal(TerminalOutcome::Interrupted) => (
                AdapterStatus::Interrupted,
                ReplayDisposition::NotRetryable,
                value.turn_id,
                value.response_digest,
                value.failure_kind,
            ),
            ObservationKind::RequestRejected => {
                let status = if value.failure_kind == Some(FailureKind::ServerOverloaded) {
                    AdapterStatus::Overloaded
                } else {
                    AdapterStatus::Rejected
                };
                (
                    status,
                    ReplayDisposition::SafeToRetry,
                    None,
                    value.response_digest,
                    value.failure_kind,
                )
            }
            ObservationKind::TimedOut => (
                AdapterStatus::TimedOut,
                ReplayDisposition::ReconcileOnly,
                None,
                None,
                None,
            ),
            ObservationKind::TransportLost => (
                AdapterStatus::Unavailable,
                ReplayDisposition::ReconcileOnly,
                None,
                None,
                None,
            ),
        },
        None if now_ms >= intent.deadline_ms => (
            AdapterStatus::TimedOut,
            ReplayDisposition::ReconcileOnly,
            None,
            None,
            None,
        ),
        None => (
            AdapterStatus::Indeterminate,
            ReplayDisposition::ReconcileOnly,
            None,
            None,
            None,
        ),
    };

    let receipt_digest = receipt_digest(
        request_digest,
        status,
        replay,
        turn_id.as_ref(),
        response_digest,
        failure_kind,
    );
    Ok(CodexAdapterReceipt {
        operation_id: intent.operation_id,
        session_id: intent.session_id,
        thread_id: intent.thread_id,
        turn_id,
        request_digest,
        receipt_digest,
        status,
        replay,
        response_digest,
        failure_kind,
        model_authority: false,
        provider_authority: false,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn request_digest(intent: &CodexOperationIntent) -> Result<Digest32, Error> {
    validate_intent(intent)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.request.v2");
    push_id(&mut bytes, &intent.operation_id);
    push_id(&mut bytes, &intent.session_id);
    push_id(&mut bytes, &intent.thread_id);
    push_id(&mut bytes, &intent.method_id);
    bytes.extend_from_slice(intent.payload_digest.as_array());
    bytes.extend_from_slice(&intent.owner_generation.to_be_bytes());
    bytes.extend_from_slice(&intent.protocol_version.to_be_bytes());
    bytes.extend_from_slice(&intent.deadline_ms.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_intent(intent: &CodexOperationIntent) -> Result<(), Error> {
    if intent.payload_digest.is_zero() || intent.lease_payload_digest.is_zero() {
        return Err(Error::EmptyDigest("payload"));
    }
    if intent.payload_digest != intent.lease_payload_digest {
        return Err(Error::PayloadBindingMismatch);
    }
    if intent.owner_generation == 0 {
        return Err(Error::InvalidOwnerGeneration);
    }
    if intent.protocol_version != APP_SERVER_PROTOCOL_V2 {
        return Err(Error::UnsupportedProtocol(intent.protocol_version));
    }
    Ok(())
}

impl FailureKind {
    fn from_codex(value: &CodexErrorInfo) -> Self {
        match value {
            CodexErrorInfo::ContextWindowExceeded => Self::ContextWindowExceeded,
            CodexErrorInfo::SessionBudgetExceeded => Self::SessionBudgetExceeded,
            CodexErrorInfo::UsageLimitExceeded => Self::UsageLimitExceeded,
            CodexErrorInfo::ServerOverloaded => Self::ServerOverloaded,
            CodexErrorInfo::CyberPolicy => Self::CyberPolicy,
            CodexErrorInfo::MisalignmentPolicyViolation => Self::MisalignmentPolicyViolation,
            CodexErrorInfo::HttpConnectionFailed { .. } => Self::HttpConnectionFailed,
            CodexErrorInfo::ResponseStreamConnectionFailed { .. } => {
                Self::ResponseStreamConnectionFailed
            }
            CodexErrorInfo::InternalServerError => Self::InternalServerError,
            CodexErrorInfo::Unauthorized => Self::Unauthorized,
            CodexErrorInfo::BadRequest => Self::BadRequest,
            CodexErrorInfo::ThreadRollbackFailed => Self::ThreadRollbackFailed,
            CodexErrorInfo::SandboxError => Self::SandboxError,
            CodexErrorInfo::ResponseStreamDisconnected { .. } => Self::ResponseStreamDisconnected,
            CodexErrorInfo::ResponseTooManyFailedAttempts { .. } => {
                Self::ResponseTooManyFailedAttempts
            }
            CodexErrorInfo::ActiveTurnNotSteerable { .. } => Self::ActiveTurnNotSteerable,
            CodexErrorInfo::Other => Self::Other,
        }
    }

    const fn tag(self) -> u8 {
        match self {
            Self::ContextWindowExceeded => 0,
            Self::SessionBudgetExceeded => 1,
            Self::UsageLimitExceeded => 2,
            Self::ServerOverloaded => 3,
            Self::CyberPolicy => 4,
            Self::MisalignmentPolicyViolation => 5,
            Self::HttpConnectionFailed => 6,
            Self::ResponseStreamConnectionFailed => 7,
            Self::InternalServerError => 8,
            Self::Unauthorized => 9,
            Self::BadRequest => 10,
            Self::ThreadRollbackFailed => 11,
            Self::SandboxError => 12,
            Self::ResponseStreamDisconnected => 13,
            Self::ResponseTooManyFailedAttempts => 14,
            Self::ActiveTurnNotSteerable => 15,
            Self::JsonRpcRejected => 16,
            Self::Other => 17,
        }
    }
}

fn terminal_response_digest(
    thread_id: &StableId,
    turn_id: &StableId,
    outcome: TerminalOutcome,
    failure_kind: Option<FailureKind>,
    message: Option<&str>,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.terminal.v2");
    push_id(&mut bytes, thread_id);
    push_id(&mut bytes, turn_id);
    bytes.push(match outcome {
        TerminalOutcome::Completed => 0,
        TerminalOutcome::Failed => 1,
        TerminalOutcome::Interrupted => 2,
    });
    push_failure(&mut bytes, failure_kind);
    push_bytes(&mut bytes, message.unwrap_or_default().as_bytes());
    Digest32::of_bytes(&bytes)
}

fn request_error_digest(code: i64, message: &str, failure_kind: FailureKind) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.request-error.v2");
    bytes.extend_from_slice(&code.to_be_bytes());
    bytes.push(failure_kind.tag());
    push_bytes(&mut bytes, message.as_bytes());
    Digest32::of_bytes(&bytes)
}

fn receipt_digest(
    request_digest: Digest32,
    status: AdapterStatus,
    replay: ReplayDisposition,
    turn_id: Option<&StableId>,
    response_digest: Option<Digest32>,
    failure_kind: Option<FailureKind>,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.receipt.v2");
    bytes.extend_from_slice(request_digest.as_array());
    bytes.push(match status {
        AdapterStatus::Succeeded => 0,
        AdapterStatus::Failed => 1,
        AdapterStatus::Interrupted => 2,
        AdapterStatus::Rejected => 3,
        AdapterStatus::Overloaded => 4,
        AdapterStatus::TimedOut => 5,
        AdapterStatus::Unavailable => 6,
        AdapterStatus::Indeterminate => 7,
    });
    bytes.push(match replay {
        ReplayDisposition::SafeToRetry => 0,
        ReplayDisposition::ReconcileOnly => 1,
        ReplayDisposition::NotRetryable => 2,
    });
    match turn_id {
        Some(value) => {
            bytes.push(1);
            push_id(&mut bytes, value);
        }
        None => bytes.push(0),
    }
    match response_digest {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
    push_failure(&mut bytes, failure_kind);
    Digest32::of_bytes(&bytes)
}

fn push_failure(bytes: &mut Vec<u8>, failure_kind: Option<FailureKind>) {
    match failure_kind {
        Some(value) => {
            bytes.push(1);
            bytes.push(value.tag());
        }
        None => bytes.push(0),
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_bytes(bytes, value.as_str().as_bytes());
}

fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "deadline_digest_tests.rs"]
mod deadline_digest_tests;
