//! Backward-compatible Cell execution contract facade.
//!
//! The shared, authority-free types and native adapter trait live in
//! `codex-hepta-types`; this crate retains only Codex App Server dispatch.

pub use codex_hepta_types::CellExecutionIntentV1;
pub use codex_hepta_types::CodexTurnBindingV1;
pub use codex_hepta_types::EXECUTION_CONTRACT_VERSION_V1;
pub use codex_hepta_types::ExecutionContractError;
pub use codex_hepta_types::ExecutionIntentKindV1;
pub use codex_hepta_types::ExecutionReceiptV1;
pub use codex_hepta_types::ExecutionStatusV1;
pub use codex_hepta_types::FinalPayloadDigestV1;
pub use codex_hepta_types::GenerationFenceWitnessV1;
pub use codex_hepta_types::NativeExecutionAdapter;
pub use codex_hepta_types::RecoveryDispositionV1;
pub use codex_hepta_types::RuntimeExecutionError;
pub use codex_hepta_types::RuntimeReceiptV1;
pub use codex_hepta_types::RuntimeToolIntentV1;
pub use codex_hepta_types::ToolOutcomeV1;

/// Admit a native tool call through the shared structural safety gate.
///
/// Unlike calling `NativeExecutionAdapter::execute` directly, this entry
/// rejects an invalid or expired intent before any backend invocation and
/// rechecks the returned receipt against the exact tool, arguments, host,
/// idempotency key, generation and payload before forwarding it to the caller.
///
/// This does not authenticate physical host evidence, grant Final-use, or
/// replace the production writer / independent observer.
pub async fn execute_native_tool_intent<A: NativeExecutionAdapter>(
    adapter: &A,
    now_ms: u64,
    intent: RuntimeToolIntentV1,
) -> Result<RuntimeReceiptV1, RuntimeExecutionError> {
    intent
        .validate()
        .map_err(RuntimeExecutionError::InvalidIntent)?;
    if now_ms >= intent.cell.deadline_ms {
        return Err(RuntimeExecutionError::InvalidIntent(
            ExecutionContractError::ExpiredDeadline,
        ));
    }

    let receipt = adapter.execute(intent.clone()).await?;
    receipt
        .validate_against(&intent)
        .map_err(RuntimeExecutionError::InvalidReceipt)?;
    Ok(receipt)
}

#[cfg(test)]
use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};

#[cfg(test)]
#[path = "execution_contract_tests.rs"]
mod tests;
