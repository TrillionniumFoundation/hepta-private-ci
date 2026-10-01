//! Read-only cognitive delivery evidence from the existing native journal.
//!
//! A write-ahead dispatch is not acceptance. This adapter neither appends a
//! second journal nor grants execution/training authority. Its opaque result
//! borrows the existing owner; callers cannot manufacture it from a JSON row.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::durable_control::DurableInferenceControl;
use crate::durable_control::native::NativeCognitivePreparation;
use crate::durable_control::native::NativeRequest;
use crate::durable_control::native::NativeRunRecord;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CognitiveContextDeliveryStateV1 {
    /// The live owner durably proved that the payload did not cross the effect boundary.
    NotSent,
    /// The App Server received the request but refused turn admission. This is
    /// not proof that context bytes were never transmitted or disclosed.
    RejectedBeforeTurn,
    /// Dispatch exists, but no exact turn was durably observed. Reconcile only.
    AcceptanceUnknown,
    /// The exact App Server turn was observed. Terminal outcome is separate.
    TurnAccepted,
    /// An exact, correlated terminal observation is in the same journal.
    TerminalObserved,
}

/// Evidence about one committed native journal revision, not a new capability.
/// This is intentionally not Clone, Deserialize, or a public field bag.
pub struct CognitiveContextDeliveryV1<'owner> {
    record: &'owner NativeRunRecord,
    context_digest: Digest32,
    state: CognitiveContextDeliveryStateV1,
    binding_digest: Digest32,
}

impl fmt::Debug for CognitiveContextDeliveryV1<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CognitiveContextDeliveryV1")
            .field("state", &self.state)
            .field("journal_revision", &self.record.revision)
            .finish_non_exhaustive()
    }
}

impl CognitiveContextDeliveryV1<'_> {
    pub fn state(&self) -> CognitiveContextDeliveryStateV1 {
        self.state
    }

    pub fn context_digest(&self) -> Digest32 {
        self.context_digest
    }

    pub fn journal_revision(&self) -> u64 {
        self.record.revision
    }

    pub fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    /// Identifies the exact native attempt; it is not a cross-request permit.
    pub fn request(&self) -> &NativeRequest {
        &self.record.request
    }

    /// The persisted ordinary-read identity. Missing historical receipts do
    /// not establish absence of exposure or permit an owner preparation join.
    pub fn preparation(&self) -> Option<&NativeCognitivePreparation> {
        self.record
            .dispatch
            .as_ref()
            .and_then(|dispatch| dispatch.cognitive_preparation.as_ref())
    }

    pub fn turn_id(&self) -> Option<&str> {
        self.record.turn_id.as_deref()
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    /// Acceptance remains a historical fact even if later authority is lost.
    /// It does not prove completion, reward, token usage, or training consent.
    pub fn accepted_by_app_server(&self) -> bool {
        matches!(
            self.state,
            CognitiveContextDeliveryStateV1::TurnAccepted
                | CognitiveContextDeliveryStateV1::TerminalObserved
        )
    }
}

impl DurableInferenceControl {
    /// Join an independently pinned native request and exact published context
    /// to this owner's committed record. None means no context-bound dispatch;
    /// it must not be interpreted as a negative exposure observation.
    ///
    /// A future journal revision requires a fresh call. Historical evidence is
    /// not current execution authority or proof that a poisoned writer can resume.
    pub fn cognitive_context_delivery(
        &self,
        expected_request: &NativeRequest,
        expected_context_digest: Digest32,
    ) -> Result<Option<CognitiveContextDeliveryV1<'_>>, CognitiveContextDeliveryError> {
        if expected_context_digest.is_zero() {
            return Err(CognitiveContextDeliveryError::InvalidDigest);
        }
        let record = self
            .native_record(&expected_request.request_id)
            .ok_or(CognitiveContextDeliveryError::RequestNotFound)?;
        if &record.request != expected_request {
            return Err(CognitiveContextDeliveryError::RequestMismatch);
        }
        let Some(dispatch) = record.dispatch.as_ref() else {
            return Ok(None);
        };
        let context_digest = required_digest(dispatch.owner_context_digest.as_deref())?;
        if context_digest != expected_context_digest {
            return Err(CognitiveContextDeliveryError::ContextMismatch);
        }
        // Historical, incompletely bound dispatches remain readable by the
        // journal but cannot become modern delivery evidence through this API.
        let admission = required_digest(dispatch.codex_source_admission_digest.as_deref())?;
        if admission != required_digest(Some(&expected_request.payload_digest))? {
            return Err(CognitiveContextDeliveryError::RequestMismatch);
        }
        for digest in [
            Some(dispatch.context_digest.as_str()),
            dispatch.codex_payload_digest.as_deref(),
            dispatch.codex_request_digest.as_deref(),
            dispatch.codex_home_digest.as_deref(),
            dispatch.codex_revocation_head_sha256.as_deref(),
            dispatch.codex_authority_witness_sha256.as_deref(),
        ] {
            required_digest(digest)?;
        }
        if dispatch.protocol_id.as_deref() != Some("codex.app-server.v2")
            || dispatch
                .app_server_version
                .as_deref()
                .is_none_or(str::is_empty)
            || dispatch
                .codex_session_id
                .as_deref()
                .is_none_or(str::is_empty)
            || dispatch.codex_connection_id.is_none()
            || dispatch.codex_deadline_ms.is_none_or(|value| value == 0)
            || dispatch.codex_authority_epoch.is_none()
            || dispatch.codex_revocation_revision.is_none()
        {
            return Err(CognitiveContextDeliveryError::IncompleteDispatch);
        }

        let state = if let Some(output) = record.observation.as_ref()
            && output.terminal_observed
        {
            if output.thread_id != dispatch.thread_id
                || output.model_provider != dispatch.model_provider
                || output.model != expected_request.model
                || record.turn_id.as_deref() != Some(output.turn_id.as_str())
            {
                return Err(CognitiveContextDeliveryError::TerminalMismatch);
            }
            required_digest(output.codex_terminal_correlation_digest.as_deref())?;
            CognitiveContextDeliveryStateV1::TerminalObserved
        } else if record.turn_id.is_some() {
            CognitiveContextDeliveryStateV1::TurnAccepted
        } else if record.pre_dispatch_stop.is_some() {
            CognitiveContextDeliveryStateV1::NotSent
        } else if record.dispatch_rejection.is_some() {
            CognitiveContextDeliveryStateV1::RejectedBeforeTurn
        } else {
            // A cancellation intent, timeout, or recovered dispatch is not a
            // proof of non-delivery. Do not use reservation state as a shortcut.
            CognitiveContextDeliveryStateV1::AcceptanceUnknown
        };
        let tag = match state {
            CognitiveContextDeliveryStateV1::NotSent => 0_u8,
            CognitiveContextDeliveryStateV1::AcceptanceUnknown => 1,
            CognitiveContextDeliveryStateV1::TurnAccepted => 2,
            CognitiveContextDeliveryStateV1::TerminalObserved => 3,
            CognitiveContextDeliveryStateV1::RejectedBeforeTurn => 4,
        };
        // No raw prompt, memory, model output, or stop reason enters this
        // projection. Its digest is integrity evidence, not a signature.
        let observation = record.observation.as_ref().map(|output| {
            (
                output.status,
                output.boundary_status,
                output.terminal_observed,
                &output.codex_terminal_correlation_digest,
                output.observed_output_tokens,
                output.succeeded(),
            )
        });
        let bytes = serde_json::to_vec(&(
            "hepta.inference.cognitive-delivery.v1",
            &record.request,
            dispatch,
            record.revision,
            &record.turn_id,
            tag,
            context_digest.to_string(),
            record.cancel_requested,
            observation,
        ))
        .map_err(|_| CognitiveContextDeliveryError::Encoding)?;
        Ok(Some(CognitiveContextDeliveryV1 {
            record,
            context_digest,
            state,
            binding_digest: Digest32::of_bytes(&bytes),
        }))
    }
}

fn required_digest(value: Option<&str>) -> Result<Digest32, CognitiveContextDeliveryError> {
    let value = value.ok_or(CognitiveContextDeliveryError::IncompleteDispatch)?;
    if value.len() != 64 {
        return Err(CognitiveContextDeliveryError::InvalidDigest);
    }
    let digest: Digest32 = value
        .parse()
        .map_err(|_| CognitiveContextDeliveryError::InvalidDigest)?;
    if digest.is_zero() {
        return Err(CognitiveContextDeliveryError::InvalidDigest);
    }
    Ok(digest)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CognitiveContextDeliveryError {
    RequestNotFound,
    RequestMismatch,
    ContextMismatch,
    IncompleteDispatch,
    InvalidDigest,
    TerminalMismatch,
    Encoding,
}

impl fmt::Display for CognitiveContextDeliveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CognitiveContextDeliveryError {}

#[cfg(test)]
#[path = "cognitive_delivery_tests.rs"]
mod tests;
