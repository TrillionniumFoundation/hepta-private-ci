//! Once-only transport of an externally provided original ObjectiveStart.
//!
//! Enabled explicitly by `objective-transport` on Linux. This module performs
//! structural validation, not signature authentication or objective admission.
//! Only an independently trusted host may provide the endpoint, peer PID,
//! request ID and original issuer envelope. No renderer/Session command, signer,
//! retry, RunStatus reconciliation, authority allocator or effect owner lives
//! here. See `OBJECTIVE_TRANSPORT.md` for the fixed original source and limits.

mod wire;

#[cfg(feature = "objective-history")]
pub mod history;

use crate::client::{require_blocking_context, validate_socket};
use crate::{EndpointConfig, ObserverError, MAX_FRAME_BYTES, POLL_TIMEOUT_MS};
use serde_json::value::RawValue;
use std::fmt;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::net::UnixStream;
use tokio::runtime::{Builder, Runtime};
use tokio::sync::Semaphore;
use tokio::time::timeout;

/// Metadata retained from the supplied envelope. These values have only passed
/// structural checks; none proves an authenticated issuer or granted authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveIdentity {
    pub issuer_id: String,
    pub key_epoch: u64,
    pub message_id: String,
    pub sequence: u64,
    pub expires_at_ms: u64,
    pub spawn_generation: u64,
    pub run_id: String,
    pub objective_revision: u64,
    pub authority_epoch: u64,
    pub runtime_body_digest: String,
    pub preference_state_digest: String,
    pub model_tuple_digest: String,
    pub prompt_registry_digest: String,
    pub artifact_set_digest: String,
}

/// Original raw issuer envelope, structurally checked but NOT authenticated.
///
/// Accepts a single JSON object with no outer whitespace or literal CR/LF;
/// escaped newlines inside strings remain valid. This narrow framing profile
/// preserves the supplied bytes, including source JSON, signature, field order
/// and internal spaces. It never normalizes or re-signs an envelope.
///
/// Deliberately has no Clone, Debug, Display, Serialize or raw-payload getter.
/// The result of an attempt keeps ownership of this same value, including when
/// delivery is unknown. This is in-memory retention, not a durable ledger.
///
/// ```compile_fail
/// use hepta_os_observer::objective::ProvidedObjective;
/// fn cannot_log_raw_envelope(value: ProvidedObjective) {
///     println!("{value:?}");
/// }
/// ```
pub struct ProvidedObjective {
    raw: Box<RawValue>,
    identity: ObjectiveIdentity,
}

impl ProvidedObjective {
    pub fn parse_json(raw: String) -> Result<Self, EnvelopeError> {
        let identity = wire::validate_envelope(&raw)?;
        let raw = RawValue::from_string(raw).map_err(|_| EnvelopeError::MalformedEnvelope)?;
        Ok(Self { raw, identity })
    }

    pub fn identity(&self) -> &ObjectiveIdentity {
        &self.identity
    }

    /// Compare against an independently retained original without exposing it.
    pub fn matches_original_json(&self, original: &[u8]) -> bool {
        self.raw.get().as_bytes() == original
    }
}

/// Finite structural diagnostics. Never contains source JSON or signature data.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EnvelopeError {
    FrameBound,
    FramingProfile,
    MalformedEnvelope,
    InvalidIdentity,
    InvalidNumber,
    InvalidSignatureShape,
    InvalidDigest,
    SourceBound,
    BodyBound,
}

impl EnvelopeError {
    pub fn code(self) -> &'static str {
        match self {
            Self::FrameBound => "objective_frame_bound",
            Self::FramingProfile => "objective_framing_profile",
            Self::MalformedEnvelope => "objective_malformed_envelope",
            Self::InvalidIdentity => "objective_invalid_identity",
            Self::InvalidNumber => "objective_invalid_number",
            Self::InvalidSignatureShape => "objective_invalid_signature_shape",
            Self::InvalidDigest => "objective_invalid_digest",
            Self::SourceBound => "objective_source_bound",
            Self::BodyBound => "objective_body_bound",
        }
    }
}

impl fmt::Display for EnvelopeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}

impl std::error::Error for EnvelopeError {}

/// The exact configured transport identity and original envelope metadata.
/// Source/signature bytes remain privately attached to the attempt itself.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SubmissionIdentity {
    pub request_id: u64,
    pub agent_id: String,
    pub spawn_generation: u64,
    pub expected_peer_uid: u32,
    pub expected_peer_pid: u32,
    pub objective: ObjectiveIdentity,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AdmissionDisposition {
    Compiled,
    ExplicitAbstain,
    CanonicalReady,
    CanonicalAbstained,
    CanonicalSlowPath,
}

/// A validated original publication response, never a device-effect receipt.
/// An abstention need not create a runtime run. Response generation is the
/// owner's captured response field, not a fresh health/lifecycle observation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmissionReceipt {
    pub run_id: String,
    pub objective_digest: String,
    pub hard_constraint_digest: String,
    pub publication_digest: String,
    pub chain_digest: String,
    pub disposition: AdmissionDisposition,
    pub idempotent: bool,
    pub response_generation: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ConflictReceipt {
    pub run_id: String,
    pub conflict_digest: String,
    pub response_generation: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PrePublicationRefusal {
    ObjectiveUnavailable,
    UnsupportedSchema,
}

/// Finite diagnostics only. Raw owner errors and transport paths are discarded.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SubmissionIssue {
    InvalidExecutionContext,
    GenerationFenced,
    FrameBound,
    Unavailable,
    PeerDenied,
    DeadlineElapsed,
    WriteFailed,
    ReadFailed,
    ProtocolMismatch,
    OwnerRequestRejected,
    OwnerError,
    Overloaded,
}

impl SubmissionIssue {
    pub fn code(self) -> &'static str {
        match self {
            Self::InvalidExecutionContext => "objective_invalid_execution_context",
            Self::GenerationFenced => "objective_generation_fenced",
            Self::FrameBound => "objective_frame_bound",
            Self::Unavailable => "objective_unavailable_transport",
            Self::PeerDenied => "objective_peer_denied",
            Self::DeadlineElapsed => "objective_deadline_elapsed",
            Self::WriteFailed => "objective_write_failed",
            Self::ReadFailed => "objective_read_failed",
            Self::ProtocolMismatch => "objective_protocol_mismatch",
            Self::OwnerRequestRejected => "objective_owner_request_rejected",
            Self::OwnerError => "objective_owner_error",
            Self::Overloaded => "objective_overloaded",
        }
    }
}

impl fmt::Display for SubmissionIssue {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}

impl std::error::Error for SubmissionIssue {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SubmissionStatus {
    /// Exactly zero request bytes were written in this attempt.
    NotSent(SubmissionIssue),
    /// Some bytes were written, but no admissible original result was obtained.
    /// Retain the original identity/source. Never infer absence from RunStatus.
    SubmitUnknown(SubmissionIssue),
    /// This one sent attempt received a strictly matched pre-dispatch refusal.
    /// It cannot clear uncertainty from any earlier attempt of this objective.
    RefusedBeforePublication {
        reason: PrePublicationRefusal,
        response_generation: u64,
    },
    Admitted(AdmissionReceipt),
    Conflict(ConflictReceipt),
}

/// Immutable in-memory attempt; contains the original envelope even on error.
/// No extraction, resubmit, rebind, retry or RunStatus-update method is exposed.
pub struct SubmissionAttempt {
    identity: SubmissionIdentity,
    objective: ProvidedObjective,
    status: SubmissionStatus,
    bytes_written: usize,
    frame_bytes: Option<usize>,
}

impl SubmissionAttempt {
    pub fn identity(&self) -> &SubmissionIdentity {
        &self.identity
    }

    pub fn status(&self) -> &SubmissionStatus {
        &self.status
    }

    /// Bytes accepted by this socket's write calls, not an owner-delivery ACK.
    pub fn bytes_written(&self) -> usize {
        self.bytes_written
    }

    pub fn request_frame_bytes(&self) -> Option<usize> {
        self.frame_bytes
    }

    pub fn matches_original_json(&self, original: &[u8]) -> bool {
        self.objective.matches_original_json(original)
    }
}

/// A dedicated-worker blocking facade for exactly one transport attempt.
///
/// `new` requires an independently trusted PID as well as EndpointConfig's
/// AgentId/spawn/UID. Request IDs come from the trusted caller; this boundary
/// allocates none. `submit_once` consumes both this facade and the envelope.
/// It opens at most one connection and never retries any semantic request.
///
/// This API is not crash-durable. An embedding host must retain pending intent
/// before invoking it, and treat loss of an in-flight result as unknown using
/// the existing owner's recovery contract. It must not create a second ledger
/// or infer permission to retry from constructing another facade.
///
/// ```compile_fail
/// use hepta_os_observer::objective::{ObjectiveTransport, ProvidedObjective};
/// fn cannot_send_twice(t: ObjectiveTransport, a: ProvidedObjective, b: ProvidedObjective) {
///     let _first = t.submit_once(a);
///     let _second = t.submit_once(b);
/// }
/// ```
pub struct ObjectiveTransport {
    config: EndpointConfig,
    expected_peer_pid: u32,
    request_id: u64,
    runtime: Option<Runtime>,
    metadata_gate: Arc<Semaphore>,
}

impl ObjectiveTransport {
    pub fn new(
        config: EndpointConfig,
        expected_peer_pid: u32,
        request_id: u64,
    ) -> Result<Self, ObserverError> {
        require_blocking_context()?;
        if expected_peer_pid == 0 || expected_peer_pid > i32::MAX as u32 || request_id == 0 {
            return Err(ObserverError::InvalidRequest);
        }
        let runtime = Builder::new_current_thread()
            .enable_io()
            .enable_time()
            .max_blocking_threads(1)
            .build()
            .map_err(|_| ObserverError::Unavailable)?;
        Ok(Self {
            config,
            expected_peer_pid,
            request_id,
            runtime: Some(runtime),
            metadata_gate: Arc::new(Semaphore::new(1)),
        })
    }

    pub fn submit_once(self, objective: ProvidedObjective) -> SubmissionAttempt {
        let identity = SubmissionIdentity {
            request_id: self.request_id,
            agent_id: self.config.expected_agent_id.clone(),
            spawn_generation: self.config.spawn_generation,
            expected_peer_uid: self.config.expected_peer_uid,
            expected_peer_pid: self.expected_peer_pid,
            objective: objective.identity.clone(),
        };
        let mut bytes_written = 0;
        let mut frame_bytes = None;
        let result = (|| {
            require_blocking_context().map_err(|_| SubmissionIssue::InvalidExecutionContext)?;
            if objective.identity.spawn_generation != self.config.spawn_generation {
                return Err(SubmissionIssue::GenerationFenced);
            }
            let frame = wire::request_frame(&objective, self.request_id, &self.config)?;
            frame_bytes = Some(frame.len());
            self.runtime
                .as_ref()
                .expect("live runtime")
                .block_on(async {
                    timeout(
                        Duration::from_millis(POLL_TIMEOUT_MS),
                        exchange(
                            &self.config,
                            self.expected_peer_pid,
                            self.request_id,
                            &objective.identity.run_id,
                            &self.metadata_gate,
                            &frame,
                            &mut bytes_written,
                        ),
                    )
                    .await
                    .map_err(|_| SubmissionIssue::DeadlineElapsed)?
                })
        })();
        let status = result.unwrap_or_else(|issue| failure_status(bytes_written, issue));
        SubmissionAttempt {
            identity,
            objective,
            status,
            bytes_written,
            frame_bytes,
        }
    }
}

impl Drop for ObjectiveTransport {
    fn drop(&mut self) {
        if let Some(runtime) = self.runtime.take() {
            // Like ObserverClient, a timed-out filesystem syscall cannot make
            // runtime destruction block the dedicated host worker forever.
            runtime.shutdown_background();
        }
    }
}

fn failure_status(bytes_written: usize, issue: SubmissionIssue) -> SubmissionStatus {
    if bytes_written == 0 {
        SubmissionStatus::NotSent(issue)
    } else {
        SubmissionStatus::SubmitUnknown(issue)
    }
}

async fn exchange(
    config: &EndpointConfig,
    expected_peer_pid: u32,
    request_id: u64,
    run_id: &str,
    metadata_gate: &Arc<Semaphore>,
    frame: &[u8],
    bytes_written: &mut usize,
) -> Result<SubmissionStatus, SubmissionIssue> {
    let response = exchange_raw(
        config,
        expected_peer_pid,
        metadata_gate,
        frame,
        bytes_written,
    )
    .await?;
    wire::classify_response(&response, config, request_id, run_id)
}

async fn exchange_raw(
    config: &EndpointConfig,
    expected_peer_pid: u32,
    metadata_gate: &Arc<Semaphore>,
    frame: &[u8],
    bytes_written: &mut usize,
) -> Result<Vec<u8>, SubmissionIssue> {
    validate_socket(config, metadata_gate)
        .await
        .map_err(|error| match error {
            ObserverError::PeerDenied => SubmissionIssue::PeerDenied,
            _ => SubmissionIssue::Unavailable,
        })?;
    let mut stream = UnixStream::connect(&config.socket_path)
        .await
        .map_err(|_| SubmissionIssue::Unavailable)?;
    let credentials = stream
        .peer_cred()
        .map_err(|_| SubmissionIssue::PeerDenied)?;
    let peer_pid = credentials.pid().and_then(|pid| u32::try_from(pid).ok());
    if credentials.uid() != config.expected_peer_uid || peer_pid != Some(expected_peer_pid) {
        return Err(SubmissionIssue::PeerDenied);
    }
    write_frame(&mut stream, frame, bytes_written).await?;
    // The fixed original server shuts down its write half after exactly one
    // frame. Require that EOF within the shared deadline, so a valid-looking
    // prefix followed by another frame cannot establish a certain result.
    let mut reader = stream.take(MAX_FRAME_BYTES + 1);
    let mut response = Vec::new();
    let count = reader
        .read_to_end(&mut response)
        .await
        .map_err(|_| SubmissionIssue::ReadFailed)?;
    if count == 0
        || count as u64 > MAX_FRAME_BYTES
        || !response.ends_with(b"\n")
        || response[..count - 1].contains(&b'\n')
    {
        return Err(SubmissionIssue::ProtocolMismatch);
    }
    Ok(response)
}

async fn write_frame<W: AsyncWrite + Unpin>(
    stream: &mut W,
    frame: &[u8],
    bytes_written: &mut usize,
) -> Result<(), SubmissionIssue> {
    while *bytes_written < frame.len() {
        let count = stream
            .write(&frame[*bytes_written..])
            .await
            .map_err(|_| SubmissionIssue::WriteFailed)?;
        if count == 0 {
            return Err(SubmissionIssue::WriteFailed);
        }
        // No await between the cancellation-safe write's result and recording
        // progress. Cancelling a later write/read retains every completed byte.
        // Completing one frame through partial writes is not a request retry.
        *bytes_written += count;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cancellation_after_a_real_partial_buffer_write_retains_unknown() {
        // A three-byte in-memory Tokio transport forces actual partial writes.
        // This tests cancellation accounting, not original Agentd admission or
        // kernel UDS behavior (covered separately by disposable socket tests).
        let runtime = Builder::new_current_thread().enable_time().build().unwrap();
        let (mut writer, reader) = tokio::io::duplex(3);
        let mut written = 0;
        runtime.block_on(async {
            let result = timeout(
                Duration::from_millis(20),
                write_frame(&mut writer, b"bounded frame\n", &mut written),
            )
            .await;
            assert!(result.is_err());
        });
        assert_eq!(written, 3);
        assert_eq!(
            failure_status(written, SubmissionIssue::DeadlineElapsed),
            SubmissionStatus::SubmitUnknown(SubmissionIssue::DeadlineElapsed)
        );
        drop(reader);
        assert_eq!(
            runtime.block_on(write_frame(&mut writer, b"bounded frame\n", &mut written)),
            Err(SubmissionIssue::WriteFailed)
        );
        assert_eq!(written, 3);
        assert_eq!(
            failure_status(written, SubmissionIssue::WriteFailed),
            SubmissionStatus::SubmitUnknown(SubmissionIssue::WriteFailed)
        );
    }
}
