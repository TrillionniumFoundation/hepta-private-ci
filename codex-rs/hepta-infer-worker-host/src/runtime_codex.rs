//! Product composition between the durable native App Server driver and
//! `runtime.codex`.
//!
//! The native control journal is the source of the frozen request payload and
//! dispatch identity. This module never creates provider/model authority. It
//! converts an already-observed, journal-bound run into the exact
//! `runtime.codex` boundary result and fails closed on identity drift.

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
pub(crate) const TURN_START_REJECTED: &str = "runtime.codex:turn-start-rejected";
pub(crate) const TURN_START_OVERLOADED: &str = "runtime.codex:turn-start-overloaded";
pub(crate) const TURN_START_OUTCOME_UNKNOWN: &str = "runtime.codex:turn-start-outcome-unknown";

/// Sealed product result. Only the native driver can construct this from the
/// same durable record that fenced the provider dispatch. A known pre-turn
/// rejection has a boundary status but deliberately has no terminal turn
/// receipt because no turn identity was admitted.
pub struct RuntimeCodexRun {
    output: NativeRunOutput,
    receipt: Option<CodexAdapterReceipt>,
    status: AdapterStatus,
}

impl RuntimeCodexRun {
    pub fn output(&self) -> &NativeRunOutput {
        &self.output
    }

    pub fn receipt(&self) -> Option<&CodexAdapterReceipt> {
        self.receipt.as_ref()
    }

    pub fn status(&self) -> AdapterStatus {
        self.status
    }

    pub fn succeeded(&self) -> bool {
        self.output.succeeded()
            && self.status == AdapterStatus::Succeeded
            && self
                .receipt
                .as_ref()
                .is_some_and(|receipt| receipt.status == AdapterStatus::Succeeded)
    }

    pub fn into_output(self) -> NativeRunOutput {
        self.output
    }
}

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

/// Crate-private witness constructor. Product callers receive
/// [`RuntimeCodexRun`] from `AppServerModelDriver::run_bound` instead of
/// assembling observations themselves.
pub(crate) fn bind_runtime_codex_run(
    record: &NativeRunRecord,
    output: NativeRunOutput,
    admitted_at_ms: u64,
    deadline_ms: u64,
) -> Result<RuntimeCodexRun, BindError> {
    let receipt = bind_receipt(record, &output, admitted_at_ms, deadline_ms)?;
    let status = match &receipt {
        Some(receipt) => receipt.status,
        None if output.stop_reason.as_deref() == Some(TURN_START_OVERLOADED) => {
            AdapterStatus::Overloaded
        }
        None if output.stop_reason.as_deref() == Some(TURN_START_REJECTED) => AdapterStatus::Rejected,
        None => AdapterStatus::Indeterminate,
    };
    Ok(RuntimeCodexRun {
        output,
        receipt,
        status,
    })
}

fn bind_receipt(
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

    fn bind(output: NativeRunOutput) -> RuntimeCodexRun {
        bind_runtime_codex_run(&record(), output, 1_000, 2_000).unwrap()
    }

    #[test]
    fn verified_completion_is_the_only_success_path() {
        let bound = bind(output(
            NativeRunStatus::Completed,
            NativeOwnerAuthority::ObservedReady,
        ));
        assert!(bound.succeeded());
        assert_eq!(bound.status(), AdapterStatus::Succeeded);
        assert_eq!(bound.receipt().unwrap().status, AdapterStatus::Succeeded);
    }

    #[test]
    fn unverified_completion_is_quarantined() {
        let bound = bind(output(
            NativeRunStatus::Completed,
            NativeOwnerAuthority::Unverified,
        ));
        assert!(!bound.succeeded());
        assert_eq!(bound.status(), AdapterStatus::Quarantined);
        assert_eq!(bound.receipt().unwrap().status, AdapterStatus::Quarantined);
    }

    #[test]
    fn failed_and_interrupted_runs_preserve_terminal_status() {
        for (status, expected) in [
            (NativeRunStatus::Failed, AdapterStatus::Failed),
            (NativeRunStatus::Interrupted, AdapterStatus::Interrupted),
        ] {
            let bound = bind(output(status, NativeOwnerAuthority::ObservedReady));
            assert_eq!(bound.status(), expected);
            assert_eq!(bound.receipt().unwrap().status, expected);
            assert!(!bound.succeeded());
        }
    }

    #[test]
    fn explicit_pre_turn_rejection_is_typed_without_forging_a_turn_receipt() {
        for (reason, expected) in [
            (TURN_START_REJECTED, AdapterStatus::Rejected),
            (TURN_START_OVERLOADED, AdapterStatus::Overloaded),
        ] {
            let mut rejected = output(
                NativeRunStatus::Indeterminate,
                NativeOwnerAuthority::Unverified,
            );
            rejected.turn_id.clear();
            rejected.output.clear();
            rejected.observed_output_tokens = None;
            rejected.stop_reason = Some(reason.to_string());
            let bound = bind_runtime_codex_run(&record(), rejected, 1_000, 2_000).unwrap();
            assert_eq!(bound.status(), expected);
            assert!(bound.receipt().is_none());
            assert!(!bound.succeeded());
        }
    }

    #[test]
    fn unknown_turn_start_outcome_cannot_receive_a_terminal_receipt() {
        let mut unknown = output(NativeRunStatus::Indeterminate, NativeOwnerAuthority::Unverified);
        unknown.turn_id.clear();
        unknown.output.clear();
        unknown.observed_output_tokens = None;
        unknown.stop_reason = Some(TURN_START_OUTCOME_UNKNOWN.to_string());
        let bound = bind_runtime_codex_run(&record(), unknown, 1_000, 2_000).unwrap();
        assert_eq!(bound.status(), AdapterStatus::Indeterminate);
        assert!(bound.receipt().is_none());
        assert!(!bound.succeeded());
    }

    #[test]
    fn assignment_drift_fails_closed() {
        let mut changed = output(NativeRunStatus::Completed, NativeOwnerAuthority::ObservedReady);
        changed.turn_id = "turn-other".to_string();
        assert!(matches!(
            bind_runtime_codex_run(&record(), changed, 1_000, 2_000),
            Err(BindError::AssignmentMismatch("turn"))
        ));
    }
}
