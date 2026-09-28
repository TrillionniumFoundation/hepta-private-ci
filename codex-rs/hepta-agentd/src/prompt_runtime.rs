//! Agentd prompt runtime composition.
//!
//! The established product owner remains available while the V3 owner is
//! compiled from ordinary source in the same crate. Product wiring can migrate
//! without qualification-time source materialization.

#[path = "prompt_runtime_legacy.rs"]
mod legacy;
pub use legacy::*;

#[path = "prompt_product_v3.rs"]
pub(crate) mod product_v3;
pub(crate) use product_v3::AgentdPromptProductErrorV3;
pub(crate) use product_v3::AgentdPromptProductOwnerV3;
