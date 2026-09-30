//! Concrete Hepta domain composition boundary for Agentd.
//!
//! `codex-hepta-agentd` depends on this one crate instead of binding every
//! domain implementation independently. Stable protocol and App Server bridge
//! crates stay direct Agentd dependencies. New or replaced domain owners are
//! wired here, while Agentd lifecycle/configuration code remains unchanged.
//! Re-exports preserve the original type identities; this crate grants no
//! authority and owns no durable product fact.

#![forbid(unsafe_code)]

pub mod automation {
    pub use codex_hepta_automation::*;
}
pub mod bellman_operator {
    pub use codex_hepta_bellman_operator::*;
}
pub mod learning_artifacts {
    pub use codex_hepta_learning_artifacts::*;
}
pub mod intelligence {
    pub use codex_hepta_intelligence::*;
}
pub mod intuition {
    pub use codex_hepta_intuition::*;
}
pub mod learning_ledger {
    pub use codex_hepta_learning_ledger::*;
}
pub mod authbus {
    pub use codex_hepta_authbus::*;
}
pub mod evidence {
    pub use codex_hepta_evidence::*;
}
pub mod contracts {
    pub use codex_hepta_contracts::*;
}
pub mod codex_adapter {
    pub use codex_hepta_codex_adapter::*;
}
pub mod prompt_registry {
    pub use codex_hepta_prompt_registry::*;
}
pub mod prompt_optimizer {
    pub use codex_hepta_prompt_optimizer::*;
}
pub mod cognitive_read {
    pub use codex_hepta_cognitive_read::*;
}
pub mod cognitive_store {
    pub use codex_hepta_cognitive_store::*;
}
pub mod control_plane {
    pub use codex_hepta_control_plane::*;
}
pub mod types {
    pub use codex_hepta_types::*;
}
pub mod fleet {
    pub use codex_hepta_fleet::*;
}
pub mod intelligence_eval {
    pub use codex_hepta_intelligence_eval::*;
}
pub mod ndu {
    pub use codex_hepta_ndu::*;
}
pub mod neuron {
    pub use codex_hepta_neuron::*;
}
pub mod objective {
    pub use codex_hepta_objective::*;
}
pub mod context_compiler {
    pub use codex_hepta_context_compiler::*;
}
pub mod memory {
    pub use codex_hepta_memory::*;
}
pub mod memory_retrieval {
    pub use codex_hepta_memory_retrieval::*;
}
pub mod memory_extension {
    pub use codex_hepta_memory_extension::*;
}
pub mod paths {
    pub use codex_hepta_paths::*;
}
pub mod plasticity {
    pub use codex_hepta_plasticity::*;
}
