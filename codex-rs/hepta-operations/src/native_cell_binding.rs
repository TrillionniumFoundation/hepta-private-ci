//! Exact identity bridge from a proposed Cell tool call to the already
//! durable kernel.operations outbox. No execution owner or authority is added.
//! FinalUse authorization and terminal host observations remain external.

use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::ExecutionContractError;
use codex_hepta_types::RuntimeReceiptV1;
use codex_hepta_types::RuntimeToolIntentV1;
use codex_hepta_types::StableId;

use crate::DispatchClaim;
use crate::DurableOperationIntentV1;
use crate::MAX_DURABLE_LEASE_MS;
use crate::MAX_DURABLE_OUTBOX_ATTEMPTS;

const NATIVE_DESTINATION: &str = "hepta.runtime.native-tool.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NativeCellBindingError {
    InvalidIntent(ExecutionContractError),
    ArgumentBytesMismatch,
    DeadlineExpired,
    ForeignOrExpiredClaim,
    InvalidInternalDestination,
}

impl fmt::Display for NativeCellBindingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for NativeCellBindingError {}

/// A caller must supply host-trusted time here and recheck it at the actual
/// effect boundary. A matching returned intent is not a signing token.
pub fn bind_native_cell_to_durable_outbox_v1(
    now_unix_ms: u64,
    intent: &RuntimeToolIntentV1,
    final_argument_bytes: &[u8],
) -> Result<DurableOperationIntentV1, NativeCellBindingError> {
    intent
        .validate()
        .map_err(NativeCellBindingError::InvalidIntent)?;
    if now_unix_ms >= intent.cell.deadline_ms {
        return Err(NativeCellBindingError::DeadlineExpired);
    }
    if Digest32::of_bytes(final_argument_bytes) != intent.arguments_digest {
        return Err(NativeCellBindingError::ArgumentBytesMismatch);
    }
    // Intent digest covers idempotency key, host, tool, argument digest,
    // generation, logical cell and owner scope. The durable outbox continues
    // to own replay denial, writer fences and independent FinalUse.
    Ok(DurableOperationIntentV1 {
        scope_id: intent.host_scope.clone(),
        operation_id: intent.cell.operation_id.clone(),
        expected_predecessor: None,
        destination: StableId::new(NATIVE_DESTINATION)
            .map_err(|_| NativeCellBindingError::InvalidInternalDestination)?,
        payload_digest: intent.intent_digest(),
        owner_generation: intent.cell.generation,
    })
}

/// Preflight one purported claim before entering DurableDispatcher. This is a
/// supplemental negative check, not proof that a lease was actually issued.
pub fn check_native_cell_outbox_claim_v1(
    now_unix_ms: u64,
    intent: &RuntimeToolIntentV1,
    final_argument_bytes: &[u8],
    claim: &DispatchClaim,
) -> Result<(), NativeCellBindingError> {
    let expected =
        bind_native_cell_to_durable_outbox_v1(now_unix_ms, intent, final_argument_bytes)?;
    if claim.intent != expected
        || claim.owner_generation != expected.owner_generation
        || claim.fence == 0
        || claim.attempts == 0
        || claim.attempts > MAX_DURABLE_OUTBOX_ATTEMPTS
        || claim.expires_at_unix_ms <= now_unix_ms
        || claim.expires_at_unix_ms > intent.cell.deadline_ms
        || claim.expires_at_unix_ms.saturating_sub(now_unix_ms) > MAX_DURABLE_LEASE_MS
    {
        return Err(NativeCellBindingError::ForeignOrExpiredClaim);
    }
    Ok(())
}

/// A shape/identity validator only. Terminal effect truth and signing remain
/// the responsibility of a real target-host observer and the durable owner.
pub fn check_native_cell_receipt_v1(
    intent: &RuntimeToolIntentV1,
    receipt: &RuntimeReceiptV1,
) -> Result<(), NativeCellBindingError> {
    receipt
        .validate_against(intent)
        .map_err(NativeCellBindingError::InvalidIntent)
}

#[cfg(test)]
#[path = "native_cell_binding_tests.rs"]
mod tests;
