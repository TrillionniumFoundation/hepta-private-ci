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
pub use codex_hepta_types::execute_native_tool_intent;
pub use codex_hepta_types::RecoveryDispositionV1;
pub use codex_hepta_types::RuntimeExecutionError;
pub use codex_hepta_types::RuntimeReceiptV1;
pub use codex_hepta_types::RuntimeToolIntentV1;
pub use codex_hepta_types::ToolOutcomeV1;

#[cfg(test)]
use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};

#[cfg(test)]
#[path = "execution_contract_tests.rs"]
mod tests;
