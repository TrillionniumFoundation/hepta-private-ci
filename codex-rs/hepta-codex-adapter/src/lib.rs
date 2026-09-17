//! Exact-bound Codex App Server request/observation adapter.
//!
//! The adapter translates an already-authorized intent and classifies the
//! exact App Server protocol outcome. It never mints model/provider authority
//! and it never turns acknowledgement loss into permission to replay an
//! effect. Production callers should feed real [`AppServerEvent`] values into
//! [`observe_app_server_event`] rather than constructing outcome claims.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;

use codex_app_server_client::AppServerEvent;
use codex_app_server_client::TypedRequestError;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnStatus;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const JSON_RPC_INVALID_REQUEST: i64 = -32_600;
const JSON_RPC_INVALID_PARAMS: i64 = -32_602;
const JSON_RPC_OVERLOADED: i64 = -32_001;
const TURN_START_METHOD: &str = "turn/start";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexOperationIntent {
    pub operation_id: StableId,
    pub thread_id: StableId,
    pub method_id: StableId,
    pub payload_digest: Digest32,
    pub lease_payload_digest: Digest32,
    pub deadline_ms: u64,
}

/// Result of the synchronous checked gate immediately before the asynchronous
/// App Server effect seam. A prepared request can be observed later without
/// incorrectly re-applying its admission deadline to terminal settlement.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedCodexRequest {
    operation_id: StableId,
    thread_id: StableId,
    request_digest: Digest32,
}

impl PreparedCodexRequest {
    pub fn operation_id(&self) -> &StableId {
        &self.operation_id
    }

    pub fn thread_id(&self) -> &StableId {
        &self.thread_id
    }

    pub fn request_digest(&self) -> Digest32 {
        self.request_digest
    }

    /// Settle from a bounded internal observation. Product code should prefer
    /// [`observe_app_server_event`] so terminality is derived from the v2
    /// protocol event rather than declared by the caller.
    pub fn observe(
        self,
        observation: Option<AppServerObservation>,
    ) -> Result<CodexAdapterReceipt, Error> {
        observe(self, observation)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TerminalOutcome {
    Completed,
    Failed,
    Interrupted,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AdmissionFailure {
    Rejected,
    Overloaded,
    Unavailable,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ObservationKind {
    Terminal(TerminalOutcome),
    AdmissionFailure(AdmissionFailure),
    TimedOut,
    Cancelled,
    Quarantined,
    Indeterminate,
}

/// A bounded observation after correlation to one prepared request.
///
/// Terminal and pre-admission constructors are crate-private. External callers
/// cannot directly claim `Completed`, `Failed`, `Interrupted` or a retry-safe
/// rejection; those claims are produced by protocol mappers in this crate.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AppServerObservation {
    thread_id: StableId,
    turn_id: Option<StableId>,
    kind: ObservationKind,
    response_digest: Option<Digest32>,
}

impl AppServerObservation {
    fn terminal(
        thread_id: StableId,
        turn_id: StableId,
        outcome: TerminalOutcome,
        response_digest: Digest32,
    ) -> Result<Self, Error> {
        if response_digest.is_zero() {
            return Err(Error::MissingTerminalResponse);
        }
        Ok(Self {
            thread_id,
            turn_id: Some(turn_id),
            kind: ObservationKind::Terminal(outcome),
            response_digest: Some(response_digest),
        })
    }

    fn admission_failure(
        thread_id: StableId,
        failure: AdmissionFailure,
        response_digest: Digest32,
    ) -> Result<Self, Error> {
        if response_digest.is_zero() {
            return Err(Error::MissingAdmissionResponse);
        }
        Ok(Self {
            thread_id,
            turn_id: None,
            kind: ObservationKind::AdmissionFailure(failure),
            response_digest: Some(response_digest),
        })
    }

    /// A timeout after the request may have crossed the admission seam. This is
    /// deliberately not retry-safe; reconciliation is required first.
    pub fn timed_out(thread_id: StableId, turn_id: Option<StableId>) -> Self {
        Self {
            thread_id,
            turn_id,
            kind: ObservationKind::TimedOut,
            response_digest: None,
        }
    }

    /// Cancellation intent without a matching terminal App Server event.
    /// Interrupt acknowledgement is not terminality.
    pub fn cancelled(thread_id: StableId, turn_id: Option<StableId>) -> Self {
        Self {
            thread_id,
            turn_id,
            kind: ObservationKind::Cancelled,
            response_digest: None,
        }
    }

    /// A local policy/security owner has quarantined this attempt. A quarantine
    /// is terminal for this operation identity and never authorizes replay.
    pub fn quarantined(thread_id: StableId, turn_id: Option<StableId>) -> Self {
        Self {
            thread_id,
            turn_id,
            kind: ObservationKind::Quarantined,
            response_digest: None,
        }
    }

    /// Transport loss, event loss, decode ambiguity, or any other state where
    /// the effect may have happened but exact terminality is not known.
    pub fn indeterminate(thread_id: StableId, turn_id: Option<StableId>) -> Self {
        Self {
            thread_id,
            turn_id,
            kind: ObservationKind::Indeterminate,
            response_digest: None,
        }
    }

    fn indeterminate_with_response(
        thread_id: StableId,
        turn_id: Option<StableId>,
        response_digest: Digest32,
    ) -> Self {
        Self {
            thread_id,
            turn_id,
            kind: ObservationKind::Indeterminate,
            response_digest: Some(response_digest),
        }
    }

    pub fn thread_id(&self) -> &StableId {
        &self.thread_id
    }

    pub fn turn_id(&self) -> Option<&StableId> {
        self.turn_id.as_ref()
    }

    pub fn response_digest(&self) -> Option<Digest32> {
        self.response_digest
    }
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
    Cancelled,
    Quarantined,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetryDisposition {
    /// The operation reached a definitive terminal state or was intentionally
    /// cancelled/quarantined. Replaying it as if no effect happened is invalid.
    DoNotRetry,
    /// The App Server response proves the request was rejected before the
    /// effect/admission seam. A caller may retry under its own bounded policy.
    RetrySafe,
    /// The request may have crossed the effect seam. Reconcile exact state
    /// before any replay.
    ReconcileBeforeRetry,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexAdapterReceipt {
    pub operation_id: StableId,
    pub thread_id: StableId,
    pub turn_id: Option<StableId>,
    pub request_digest: Digest32,
    pub status: AdapterStatus,
    pub retry: RetryDisposition,
    pub response_digest: Option<Digest32>,
    pub receipt_digest: Digest32,
    pub model_authority: bool,
    pub provider_authority: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    PayloadBindingMismatch,
    DeadlineExpired,
    ThreadBindingMismatch,
    InvalidIdentifier(&'static str),
    MissingTerminalResponse,
    MissingAdmissionResponse,
    NonTerminalCompletion,
    UnexpectedMethod,
    ProtocolEncoding,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

/// Validate the final request binding and admission deadline immediately before
/// dispatch. This is the only API that evaluates `deadline_ms`.
pub fn prepare(
    now_ms: u64,
    intent: CodexOperationIntent,
) -> Result<PreparedCodexRequest, Error> {
    if intent.payload_digest.is_zero() {
        return Err(Error::EmptyDigest("payload"));
    }
    if intent.lease_payload_digest.is_zero() {
        return Err(Error::EmptyDigest("lease_payload"));
    }
    if intent.payload_digest != intent.lease_payload_digest {
        return Err(Error::PayloadBindingMismatch);
    }
    if now_ms >= intent.deadline_ms {
        return Err(Error::DeadlineExpired);
    }

    let request_digest = request_digest(&intent);
    Ok(PreparedCodexRequest {
        operation_id: intent.operation_id,
        thread_id: intent.thread_id,
        request_digest,
    })
}

/// Derive a terminal receipt from an actual v2 App Server notification.
/// Unrelated notifications are ignored. A `turn/completed` notification with
/// `InProgress` is a protocol violation rather than a success.
pub fn observe_server_notification(
    prepared: &PreparedCodexRequest,
    notification: &ServerNotification,
) -> Result<Option<CodexAdapterReceipt>, Error> {
    let ServerNotification::TurnCompleted(completed) = notification else {
        return Ok(None);
    };
    if completed.thread_id != prepared.thread_id.as_str() {
        return Ok(None);
    }
    terminal_receipt(prepared, completed).map(Some)
}

/// Derive settlement from the bounded client event stream. Lag/disconnect mean
/// the request may have executed while the observer lost facts, so they are
/// always `Indeterminate/ReconcileBeforeRetry`. Server requests and unrelated
/// notifications are nonterminal and return `None`.
pub fn observe_app_server_event(
    prepared: &PreparedCodexRequest,
    event: &AppServerEvent,
) -> Result<Option<CodexAdapterReceipt>, Error> {
    match event {
        AppServerEvent::ServerNotification(notification) => {
            observe_server_notification(prepared, notification.as_ref())
        }
        AppServerEvent::Lagged { .. } | AppServerEvent::Disconnected { .. } => prepared
            .clone()
            .observe(Some(AppServerObservation::indeterminate(
                prepared.thread_id.clone(),
                None,
            )))
            .map(Some),
        AppServerEvent::ServerRequest(_) => Ok(None),
    }
}

/// Classify a `turn/start` request failure without inventing safe replay.
/// Only transport-ingress overload (`-32001`) and closed invalid-request/
/// invalid-params responses are treated as proven pre-admission rejection.
/// Other server, transport, and decode failures remain indeterminate.
pub fn observe_turn_start_error(
    prepared: &PreparedCodexRequest,
    error: &TypedRequestError,
) -> Result<CodexAdapterReceipt, Error> {
    let method = match error {
        TypedRequestError::Transport { method, .. }
        | TypedRequestError::Server { method, .. }
        | TypedRequestError::Deserialize { method, .. } => method,
    };
    if method != TURN_START_METHOD {
        return Err(Error::UnexpectedMethod);
    }

    let observation = match error {
        TypedRequestError::Server { source, .. } if source.code == JSON_RPC_OVERLOADED => {
            AppServerObservation::admission_failure(
                prepared.thread_id.clone(),
                AdmissionFailure::Overloaded,
                json_rpc_error_digest(source.code, &source.message, source.data.as_ref())?,
            )?
        }
        TypedRequestError::Server { source, .. }
            if matches!(source.code, JSON_RPC_INVALID_REQUEST | JSON_RPC_INVALID_PARAMS) =>
        {
            AppServerObservation::admission_failure(
                prepared.thread_id.clone(),
                AdmissionFailure::Rejected,
                json_rpc_error_digest(source.code, &source.message, source.data.as_ref())?,
            )?
        }
        TypedRequestError::Server { source, .. } => {
            AppServerObservation::indeterminate_with_response(
                prepared.thread_id.clone(),
                None,
                json_rpc_error_digest(source.code, &source.message, source.data.as_ref())?,
            )
        }
        TypedRequestError::Transport { .. } | TypedRequestError::Deserialize { .. } => {
            AppServerObservation::indeterminate(prepared.thread_id.clone(), None)
        }
    };
    prepared.clone().observe(Some(observation))
}

/// Settle a request from one already-correlated observation. Settlement does
/// not re-run the pre-dispatch clock gate; terminal events can legitimately
/// arrive after the original admission deadline.
pub fn observe(
    prepared: PreparedCodexRequest,
    observation: Option<AppServerObservation>,
) -> Result<CodexAdapterReceipt, Error> {
    let (thread_id, turn_id, status, retry, response_digest) = match observation {
        None => (
            prepared.thread_id.clone(),
            None,
            AdapterStatus::Indeterminate,
            RetryDisposition::ReconcileBeforeRetry,
            None,
        ),
        Some(value) => {
            if value.thread_id != prepared.thread_id {
                return Err(Error::ThreadBindingMismatch);
            }
            let (status, retry) = match value.kind {
                ObservationKind::Terminal(TerminalOutcome::Completed) => {
                    (AdapterStatus::Succeeded, RetryDisposition::DoNotRetry)
                }
                ObservationKind::Terminal(TerminalOutcome::Failed) => {
                    (AdapterStatus::Failed, RetryDisposition::DoNotRetry)
                }
                ObservationKind::Terminal(TerminalOutcome::Interrupted) => {
                    (AdapterStatus::Interrupted, RetryDisposition::DoNotRetry)
                }
                ObservationKind::AdmissionFailure(AdmissionFailure::Rejected) => {
                    (AdapterStatus::Rejected, RetryDisposition::RetrySafe)
                }
                ObservationKind::AdmissionFailure(AdmissionFailure::Overloaded) => {
                    (AdapterStatus::Overloaded, RetryDisposition::RetrySafe)
                }
                ObservationKind::AdmissionFailure(AdmissionFailure::Unavailable) => {
                    (AdapterStatus::Unavailable, RetryDisposition::RetrySafe)
                }
                ObservationKind::TimedOut => (
                    AdapterStatus::TimedOut,
                    RetryDisposition::ReconcileBeforeRetry,
                ),
                ObservationKind::Cancelled => {
                    (AdapterStatus::Cancelled, RetryDisposition::DoNotRetry)
                }
                ObservationKind::Quarantined => {
                    (AdapterStatus::Quarantined, RetryDisposition::DoNotRetry)
                }
                ObservationKind::Indeterminate => (
                    AdapterStatus::Indeterminate,
                    RetryDisposition::ReconcileBeforeRetry,
                ),
            };
            (
                value.thread_id,
                value.turn_id,
                status,
                retry,
                value.response_digest,
            )
        }
    };

    let receipt_digest = receipt_digest(
        &prepared.operation_id,
        &thread_id,
        turn_id.as_ref(),
        prepared.request_digest,
        status,
        retry,
        response_digest,
    );
    Ok(CodexAdapterReceipt {
        operation_id: prepared.operation_id,
        thread_id,
        turn_id,
        request_digest: prepared.request_digest,
        status,
        retry,
        response_digest,
        receipt_digest,
        model_authority: false,
        provider_authority: false,
        authority: AuthorityPosture::DENY_ALL,
    })
}

/// Compatibility convenience for deterministic callers and tests. Production
/// event consumers should use `prepare` then the protocol mappers above.
pub fn adapt(
    now_ms: u64,
    intent: CodexOperationIntent,
    observation: Option<AppServerObservation>,
) -> Result<CodexAdapterReceipt, Error> {
    observe(prepare(now_ms, intent)?, observation)
}

fn terminal_receipt(
    prepared: &PreparedCodexRequest,
    completed: &TurnCompletedNotification,
) -> Result<CodexAdapterReceipt, Error> {
    let outcome = match completed.turn.status {
        TurnStatus::Completed => TerminalOutcome::Completed,
        TurnStatus::Failed => TerminalOutcome::Failed,
        TurnStatus::Interrupted => TerminalOutcome::Interrupted,
        TurnStatus::InProgress => return Err(Error::NonTerminalCompletion),
    };
    let turn_id = StableId::new(completed.turn.id.clone())
        .map_err(|_| Error::InvalidIdentifier("turn_id"))?;
    let response = serde_json::to_vec(completed).map_err(|_| Error::ProtocolEncoding)?;
    let observation = AppServerObservation::terminal(
        prepared.thread_id.clone(),
        turn_id,
        outcome,
        Digest32::of_bytes(&response),
    )?;
    prepared.clone().observe(Some(observation))
}

fn json_rpc_error_digest(
    code: i64,
    message: &str,
    data: Option<&serde_json::Value>,
) -> Result<Digest32, Error> {
    let value = serde_json::json!({
        "code": code,
        "message": message,
        "data": data,
    });
    let bytes = serde_json::to_vec(&value).map_err(|_| Error::ProtocolEncoding)?;
    Ok(Digest32::of_bytes(&bytes))
}

fn request_digest(intent: &CodexOperationIntent) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.request.v2");
    push_id(&mut bytes, &intent.operation_id);
    push_id(&mut bytes, &intent.thread_id);
    push_id(&mut bytes, &intent.method_id);
    bytes.extend_from_slice(intent.payload_digest.as_array());
    bytes.extend_from_slice(intent.lease_payload_digest.as_array());
    bytes.extend_from_slice(&intent.deadline_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn receipt_digest(
    operation_id: &StableId,
    thread_id: &StableId,
    turn_id: Option<&StableId>,
    request_digest: Digest32,
    status: AdapterStatus,
    retry: RetryDisposition,
    response_digest: Option<Digest32>,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.receipt.v2");
    push_id(&mut bytes, operation_id);
    push_id(&mut bytes, thread_id);
    push_optional_id(&mut bytes, turn_id);
    bytes.extend_from_slice(request_digest.as_array());
    bytes.push(status_code(status));
    bytes.push(retry_code(retry));
    push_optional_digest(&mut bytes, response_digest);
    // The adapter is deliberately non-authoritative. Bind those two false
    // claims into the receipt format rather than leaving them implicit.
    bytes.extend_from_slice(&[0, 0]);
    Digest32::of_bytes(&bytes)
}

fn status_code(status: AdapterStatus) -> u8 {
    match status {
        AdapterStatus::Succeeded => 1,
        AdapterStatus::Failed => 2,
        AdapterStatus::Interrupted => 3,
        AdapterStatus::Rejected => 4,
        AdapterStatus::Overloaded => 5,
        AdapterStatus::Unavailable => 6,
        AdapterStatus::TimedOut => 7,
        AdapterStatus::Cancelled => 8,
        AdapterStatus::Quarantined => 9,
        AdapterStatus::Indeterminate => 10,
    }
}

fn retry_code(retry: RetryDisposition) -> u8 {
    match retry {
        RetryDisposition::DoNotRetry => 1,
        RetryDisposition::RetrySafe => 2,
        RetryDisposition::ReconcileBeforeRetry => 3,
    }
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
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
