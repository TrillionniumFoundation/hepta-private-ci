//! Product composition between the durable native App Server driver and
//! `runtime.codex`.
//!
//! The native control journal is the source of the frozen request payload and
//! dispatch identity. This module never creates provider/model authority. It
//! converts an already-observed, journal-bound run into the exact
//! `runtime.codex` receipt and fails closed on identity drift.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_codex_adapter::AdapterStatus;
use codex_hepta_codex_adapter::AppServerObservation;
use codex_hepta_codex_adapter::AppServerOutcome;
use codex_hepta_codex_adapter::CodexAdapterReceipt;
use codex_hepta_codex_adapter::CodexOperationIntent;
use codex_hepta_codex_adapter::Error as AdapterError;
use codex_hepta_codex_adapter::adapt;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const APP_SERVER_PROTOCOL_VERSION: u32 = 2;
const TURN_START_METHOD_ID: &str = "app-server.v2.turn-start";

#[derive(Debug)]
pub enum BindError {
    MissingDispatch,
    AssignmentMismatch(&'static str),
    InvalidIdentity(&'static str),
    InvalidPayloadDigest,
    InvalidDeadline,
    InvalidTerminalState,
    EncodeObservation,
    Adapter(AdapterError),
}

impl fmt::Display for BindError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for BindError {}

/// Bind one durable native run to the runtime.codex receipt boundary.
///
/// An empty turn id means `turn/start` did not yield a correlation identity;
/// that execution remains outside the terminal receipt boundary and must stay
/// indeterminate. The caller must not synthesize a turn id merely to obtain a
/// receipt.
pub fn bind_runtime_codex_receipt(
    record: &NativeRunRecord,
    output: &NativeRunOutput,
    admitted_at_ms: u64,
    deadline_ms: u64,
) -> Result<Option<CodexAdapterReceipt>, BindError> {
    if deadline_ms <= admitted_at_ms {
        return Err(BindError::InvalidDeadline);
    }
    if output.turn_id.is_empty() {
        if output.terminal_observed {
            return Err(BindError::InvalidTerminalState);
        }
        return Ok(None);
    }

    let dispatch = record.dispatch.as_ref().ok_or(BindError::MissingDispatch)?;
    if output.thread_id != dispatch.thread_id {
        return Err(BindError::AssignmentMismatch("thread"));
    }
    if output.model_provider != dispatch.model_provider {
        return Err(BindError::AssignmentMismatch("model provider"));
    }
    if output.model != record.request.model {
        return Err(BindError::AssignmentMismatch("model"));
    }
    if record
        .turn_id
        .as_ref()
        .is_some_and(|turn_id| turn_id != &output.turn_id)
    {
        return Err(BindError::AssignmentMismatch("turn"));
    }

    let operation_id = stable_id(&record.request.request_id, "operation")?;
    let thread_id = stable_id(&output.thread_id, "thread")?;
    let turn_id = stable_id(&output.turn_id, "turn")?;
    let method_id = stable_id(TURN_START_METHOD_ID, "method")?;
    let payload_digest = digest32_from_hex(&record.request.payload_digest)?;

    let outcome = map_outcome(output)?;
    let response_digest = if output.terminal_observed {
        let encoded = serde_json::to_vec(output).map_err(|_| BindError::EncodeObservation)?;
        Some(Digest32::of_bytes(&encoded))
    } else {
        None
    };

    let receipt = adapt(
        admitted_at_ms,
        CodexOperationIntent {
            operation_id,
            thread_id: thread_id.clone(),
            turn_id: turn_id.clone(),
            method_id,
            protocol_version: APP_SERVER_PROTOCOL_VERSION,
            payload_digest,
            // The durable reservation freezes the exact payload before provider
            // dispatch. runtime.codex verifies equality but grants no authority.
            lease_payload_digest: payload_digest,
            deadline_ms,
        },
        Some(AppServerObservation {
            thread_id,
            turn_id,
            protocol_version: APP_SERVER_PROTOCOL_VERSION,
            outcome,
            response_digest,
        }),
    )
    .map_err(BindError::Adapter)?;

    // Provider completion without a currently observed owner may never emerge
    // from the composed product boundary as success.
    if output.status == NativeRunStatus::Completed
        && output.owner_authority != NativeOwnerAuthority::ObservedReady
        && receipt.status != AdapterStatus::Quarantined
    {
        return Err(BindError::InvalidTerminalState);
    }
    Ok(Some(receipt))
}

fn map_outcome(output: &NativeRunOutput) -> Result<AppServerOutcome, BindError> {
    if output.terminal_observed && output.status == NativeRunStatus::Indeterminate {
        return Err(BindError::InvalidTerminalState);
    }
    if !output.terminal_observed && output.status != NativeRunStatus::Indeterminate {
        return Err(BindError::InvalidTerminalState);
    }

    Ok(match output.status {
        NativeRunStatus::Completed
            if output.owner_authority != NativeOwnerAuthority::ObservedReady =>
        {
            AppServerOutcome::Quarantined
        }
        NativeRunStatus::Completed => AppServerOutcome::Completed,
        NativeRunStatus::Failed => AppServerOutcome::Failed,
        NativeRunStatus::Interrupted => AppServerOutcome::Interrupted,
        NativeRunStatus::Indeterminate => AppServerOutcome::InProgress,
    })
}

fn stable_id(value: &str, field: &'static str) -> Result<StableId, BindError> {
    StableId::new(value.to_string()).map_err(|_| BindError::InvalidIdentity(field))
}

fn digest32_from_hex(value: &str) -> Result<Digest32, BindError> {
    if value.len() != 64 {
        return Err(BindError::InvalidPayloadDigest);
    }
    let mut bytes = [0_u8; 32];
    for (index, chunk) in value.as_bytes().chunks_exact(2).enumerate() {
        let pair = std::str::from_utf8(chunk).map_err(|_| BindError::InvalidPayloadDigest)?;
        bytes[index] =
            u8::from_str_radix(pair, 16).map_err(|_| BindError::InvalidPayloadDigest)?;
    }
    let digest = Digest32::from_array(bytes);
    if digest.is_zero() {
        return Err(BindError::InvalidPayloadDigest);
    }
    Ok(digest)
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_infer_core::durable_control::native::NativeDispatch;
    use codex_hepta_infer_core::durable_control::native::NativeRequest;
    use codex_hepta_infer_core::durable_control::native::NativeReservationState;

    fn record() -> NativeRunRecord {
        NativeRunRecord {
            request: NativeRequest {
                request_id: "request-1".to_string(),
                principal_id: "agent-1".to_string(),
                worker_generation: 1,
                model: "model-1".to_string(),
                payload_digest: "11".repeat(32),
            },
            revision: 3,
            state: NativeReservationState::Running,
            dispatch: Some(NativeDispatch {
                thread_id: "thread-1".to_string(),
                model_provider: "provider-1".to_string(),
                context_digest: "22".repeat(32),
            }),
            turn_id: Some("turn-1".to_string()),
            cancel_requested: false,
            pre_dispatch_stop: None,
            observation: None,
        }
    }

    fn output(status: NativeRunStatus, authority: NativeOwnerAuthority) -> NativeRunOutput {
        NativeRunOutput {
            thread_id: "thread-1".to_string(),
            turn_id: "turn-1".to_string(),
            model: "model-1".to_string(),
            model_provider: "provider-1".to_string(),
            status,
            output: "answer".to_string(),
            observed_output_tokens: Some(4),
            terminal_observed: status != NativeRunStatus::Indeterminate,
            stop_reason: None,
            owner_authority: authority,
        }
    }

    #[test]
    fn verified_completion_is_the_only_success_path() {
        let receipt = bind_runtime_codex_receipt(
            &record(),
            &output(NativeRunStatus::Completed, NativeOwnerAuthority::ObservedReady),
            1_000,
            2_000,
        )
        .unwrap()
        .unwrap();
        assert_eq!(receipt.status, AdapterStatus::Succeeded);
    }

    #[test]
    fn unverified_completion_is_quarantined() {
        let receipt = bind_runtime_codex_receipt(
            &record(),
            &output(NativeRunStatus::Completed, NativeOwnerAuthority::Unverified),
            1_000,
            2_000,
        )
        .unwrap()
        .unwrap();
        assert_eq!(receipt.status, AdapterStatus::Quarantined);
    }

    #[test]
    fn failed_and_interrupted_runs_preserve_terminal_status() {
        for (status, expected) in [
            (NativeRunStatus::Failed, AdapterStatus::Failed),
            (NativeRunStatus::Interrupted, AdapterStatus::Interrupted),
        ] {
            let receipt = bind_runtime_codex_receipt(
                &record(),
                &output(status, NativeOwnerAuthority::ObservedReady),
                1_000,
                2_000,
            )
            .unwrap()
            .unwrap();
            assert_eq!(receipt.status, expected);
        }
    }

    #[test]
    fn unknown_turn_start_outcome_cannot_receive_a_terminal_receipt() {
        let mut unknown = output(NativeRunStatus::Indeterminate, NativeOwnerAuthority::Unverified);
        unknown.turn_id.clear();
        unknown.output.clear();
        unknown.observed_output_tokens = None;
        assert!(
            bind_runtime_codex_receipt(&record(), &unknown, 1_000, 2_000)
                .unwrap()
                .is_none()
        );
    }

    #[test]
    fn assignment_drift_fails_closed() {
        let mut changed = output(NativeRunStatus::Completed, NativeOwnerAuthority::ObservedReady);
        changed.turn_id = "turn-other".to_string();
        assert!(matches!(
            bind_runtime_codex_receipt(&record(), &changed, 1_000, 2_000),
            Err(BindError::AssignmentMismatch("turn"))
        ));
    }
}
