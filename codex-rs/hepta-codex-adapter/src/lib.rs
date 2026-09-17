//! Exact-bound Codex app-server request/observation adapter.
//!
//! The adapter translates an already-authorized intent and classifies an
//! observed App Server outcome. It never mints model/provider authority and it
//! never turns acknowledgement loss into permission to replay an effect.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

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
    Indeterminate,
}

/// A bounded observation of the exact App Server boundary.
///
/// Fields are private so callers cannot accidentally create internally
/// inconsistent terminal records. Provenance still belongs to the production
/// event consumer: constructing this type is not cryptographic authentication
/// that bytes came from an App Server process.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AppServerObservation {
    thread_id: StableId,
    turn_id: Option<StableId>,
    kind: ObservationKind,
    response_digest: Option<Digest32>,
}

impl AppServerObservation {
    pub fn terminal(
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

    /// A server response that proves `turn/start` was rejected before a turn
    /// handle was returned. The response itself is content-bound.
    pub fn admission_failure(
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
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetryDisposition {
    /// The operation reached a definitive terminal state or was intentionally
    /// cancelled. Replaying it as if no effect happened is invalid.
    DoNotRetry,
    /// A server response proves that no turn was admitted. A caller may retry
    /// under its own bounded retry policy and stable semantic identity.
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
    MissingTerminalResponse,
    MissingAdmissionResponse,
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

    Ok(PreparedCodexRequest {
        operation_id: intent.operation_id,
        thread_id: intent.thread_id,
        request_digest: request_digest(&intent),
    })
}

/// Settle a request from an exact App Server observation. Settlement does not
/// re-run the pre-dispatch clock gate; terminal events can legitimately arrive
/// after the original admission deadline.
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

/// Compatibility convenience for synchronous callers and tests. Production
/// asynchronous execution should use `prepare` before dispatch and `observe`
/// after the exact event is received.
pub fn adapt(
    now_ms: u64,
    intent: CodexOperationIntent,
    observation: Option<AppServerObservation>,
) -> Result<CodexAdapterReceipt, Error> {
    observe(prepare(now_ms, intent)?, observation)
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
        AdapterStatus::Indeterminate => 9,
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
