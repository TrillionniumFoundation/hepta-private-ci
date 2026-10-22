//! Backward-compatible Cell execution contract facade.
//!
//! The shared, authority-free types and native adapter trait live in
//! `codex-hepta-types`; this crate retains only Codex App Server dispatch.

pub use codex_hepta_types::{
    CellExecutionIntentV1,
    CodexTurnBindingV1,
    EXECUTION_CONTRACT_VERSION_V1,
    ExecutionContractError,
    ExecutionIntentKindV1,
    ExecutionReceiptV1,
    ExecutionStatusV1,
    FinalPayloadDigestV1,
    GenerationFenceWitnessV1,
    NativeExecutionAdapter,
    RecoveryDispositionV1,
    RuntimeExecutionError,
    RuntimeReceiptV1,
    RuntimeToolIntentV1,
    ToolOutcomeV1,
};

#[cfg(test)]
use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};

#[cfg(test)]
#[path = "execution_contract_tests.rs"]
mod tests;
