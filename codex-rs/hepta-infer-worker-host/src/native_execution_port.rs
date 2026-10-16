//! Original owner-bound preparation for the existing Codex turn/start seam.
//!
//! This projection reads the *already durably reserved* native record. It is
//! not an authority token or a new dispatcher, and it may not be reconstructed
//! from a user-supplied Codex envelope or from a dispatched/reopened record.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct ReservedNativePortBindingV1 {
    pub operation_id: StableId,
    pub source_admission_digest: Digest32,
    pub generation: Generation,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum NativePortBindingErrorV1 {
    BindingMismatch(&'static str),
    NotFreshlyReserved,
    InvalidSourceDigest,
    InvalidGeneration,
    InvalidOperationIdentity,
}

impl fmt::Display for NativePortBindingErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl StdError for NativePortBindingErrorV1 {}

/// Verify the original owner's reserved record before constructing a nonauthorizing
/// execution intent. This check cannot replace a current Final-use grant or the
/// original owner's durable dispatch/acknowledgement/reconciliation protocol.
pub(super) fn bind_reserved_native_port_v1(
    record: &NativeRunRecord,
    request_id: &str,
    principal_id: &str,
    generation: u64,
    model: &str,
) -> Result<ReservedNativePortBindingV1, NativePortBindingErrorV1> {
    if record.request.request_id != request_id {
        return Err(NativePortBindingErrorV1::BindingMismatch("request"));
    }
    if record.request.principal_id != principal_id {
        return Err(NativePortBindingErrorV1::BindingMismatch("principal"));
    }
    if record.request.worker_generation != generation {
        return Err(NativePortBindingErrorV1::BindingMismatch("generation"));
    }
    if record.request.model != model {
        return Err(NativePortBindingErrorV1::BindingMismatch("model"));
    }
    // Once an effect might have been submitted, only the original reconciler
    // may act. Never turn a dispatching/reopened record into a fresh intent.
    if record.revision != 1
        || record.state != NativeReservationState::Reserved
        || record.dispatch.is_some()
        || record.turn_id.is_some()
        || record.cancel_requested
        || record.pre_dispatch_stop.is_some()
        || record.dispatch_rejection.is_some()
        || record.observation.is_some()
    {
        return Err(NativePortBindingErrorV1::NotFreshlyReserved);
    }
    let generation = Generation::new(record.request.worker_generation)
        .map_err(|_| NativePortBindingErrorV1::InvalidGeneration)?;
    let source_admission_digest: Digest32 = record
        .request
        .payload_digest
        .parse()
        .map_err(|_| NativePortBindingErrorV1::InvalidSourceDigest)?;
    if source_admission_digest.is_zero() {
        return Err(NativePortBindingErrorV1::InvalidSourceDigest);
    }
    // Preserve the legacy persisted operation identity domain exactly.
    let operation_id = StableId::new(format!(
        "native:{}",
        Digest32::of_bytes(record.request.request_id.as_bytes())
    ))
    .map_err(|_| NativePortBindingErrorV1::InvalidOperationIdentity)?;
    Ok(ReservedNativePortBindingV1 {
        operation_id,
        source_admission_digest,
        generation,
    })
}

#[cfg(test)]
#[path = "native_execution_port_tests.rs"]
mod tests;
