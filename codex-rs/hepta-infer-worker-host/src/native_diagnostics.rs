//! Observational view of an already opened inference.control owner.
//!
//! This module cannot open a journal, contact a provider, claim authority,
//! reserve, settle, release or replay an operation. Its output is diagnostic,
//! not a terminal receipt, a billing statement or permission to retry.

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

/// A diagnostic routing hint, never evidence authorizing a state transition.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeRecoveryAction {
    ReservedNotDispatched,
    TerminalObserved,
    StoppedBeforeEffect,
    RejectedBeforeStart,
    ReconcileOnly,
    LegacyUnresolved,
    InconsistentRecord,
}

/// Redacted authority observation; provider/owner error text is not exported.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeAuthorityObservation {
    Unverified,
    ObservedReady,
    Lost,
}

/// A view of one persisted operation revision. Unknown usage stays `None`.
/// The v1 journal has no admission/first-indeterminate timestamp, so this view
/// deliberately cannot report an age or derive one from a dispatch deadline.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NativeRecoverySnapshot {
    pub schema_version: u32,
    pub operation_id_sha256: String,
    pub revision: u64,
    pub worker_generation: u64,
    pub state: NativeReservationState,
    pub holds_local_slot: bool,
    pub cancellation_requested: bool,
    pub terminal_observed: bool,
    pub observed_output_tokens: Option<u64>,
    pub owner_authority: NativeAuthorityObservation,
    pub recorded_dispatch_deadline_unix_ms: Option<u64>,
    pub exact_history_binding_present: bool,
    pub terminal_correlation_present: bool,
    pub recovery_action: NativeRecoveryAction,
}

/// Inspect existing owner state without mutation or external I/O. The caller
/// must already possess the control-owner handle; no second journal decoder,
/// writer or state cache is introduced. A missing identity is an error, not an
/// invitation to create a replacement request.
pub fn inspect_native_run(
    control: &DurableInferenceControl,
    request_id: &str,
) -> Result<NativeRecoverySnapshot, Error> {
    let record = control
        .native_record(request_id)
        .ok_or(Error::RequestNotFound)?;
    let observation = record.observation.as_ref();
    let terminal_observed = observation.is_some_and(|value| value.terminal_observed);
    let exact_history_binding_present = record.dispatch.as_ref().is_some_and(|dispatch| {
        dispatch.codex_payload_digest.is_some()
            && dispatch.codex_request_digest.is_some()
            && dispatch.app_server_version.is_some()
            && dispatch.protocol_id.is_some()
            && dispatch.codex_source_admission_digest.is_some()
            && dispatch.codex_home_digest.is_some()
            && dispatch.codex_connection_id.is_some()
            && dispatch.codex_session_id.is_some()
            && dispatch.codex_deadline_ms.is_some()
            && dispatch.codex_authority_witness_sha256.is_some()
    });
    let recovery_action = match record.state {
        NativeReservationState::Released if terminal_observed => {
            NativeRecoveryAction::TerminalObserved
        }
        NativeReservationState::Released if record.pre_dispatch_stop.is_some() => {
            NativeRecoveryAction::StoppedBeforeEffect
        }
        NativeReservationState::Released if record.dispatch_rejection.is_some() => {
            NativeRecoveryAction::RejectedBeforeStart
        }
        NativeReservationState::Released => NativeRecoveryAction::InconsistentRecord,
        NativeReservationState::Reserved if record.dispatch.is_none() => {
            NativeRecoveryAction::ReservedNotDispatched
        }
        NativeReservationState::Reserved => NativeRecoveryAction::InconsistentRecord,
        NativeReservationState::Dispatching
        | NativeReservationState::Running
        | NativeReservationState::Cancelling
        | NativeReservationState::Indeterminate => {
            if exact_history_binding_present {
                NativeRecoveryAction::ReconcileOnly
            } else {
                NativeRecoveryAction::LegacyUnresolved
            }
        }
    };
    let owner_authority = match observation.map(|value| &value.owner_authority) {
        None | Some(NativeOwnerAuthority::Unverified) => NativeAuthorityObservation::Unverified,
        Some(NativeOwnerAuthority::ObservedReady) => NativeAuthorityObservation::ObservedReady,
        Some(NativeOwnerAuthority::Lost { .. }) => NativeAuthorityObservation::Lost,
    };
    let mut identity = Sha256::new();
    identity.update(b"hepta.inference.worker.diagnostic-operation.v1\0");
    identity.update(request_id.as_bytes());
    Ok(NativeRecoverySnapshot {
        schema_version: 1,
        operation_id_sha256: format!("{:x}", identity.finalize()),
        revision: record.revision,
        worker_generation: record.request.worker_generation,
        state: record.state,
        holds_local_slot: record.state != NativeReservationState::Released,
        cancellation_requested: record.cancel_requested,
        terminal_observed,
        observed_output_tokens: observation.and_then(|value| value.observed_output_tokens),
        owner_authority,
        recorded_dispatch_deadline_unix_ms: record
            .dispatch
            .as_ref()
            .and_then(|value| value.codex_deadline_ms),
        exact_history_binding_present,
        terminal_correlation_present: observation
            .is_some_and(|value| value.codex_terminal_correlation_digest.is_some()),
        recovery_action,
    })
}

#[cfg(test)]
#[path = "native_diagnostics_tests.rs"]
mod tests;
