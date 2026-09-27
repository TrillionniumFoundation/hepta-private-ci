//! Prompt intervention policy. `canonical` is the sole supported policy path.
//!
//! Compatibility calculators do not authenticate evidence or authorize effects.
#![forbid(unsafe_code)]

#[cfg(test)]
extern crate self as codex_hepta_prompt_optimizer;

pub mod canonical;
mod canonical_engine;
pub mod compat;

// Preserve source compatibility during caller migration. New callers must name
// `compat` explicitly; these exports are not the canonical policy pipeline.
pub use compat::CandidateDecision;
pub use compat::CandidateDisposition;
pub use compat::Error;
pub use compat::GraphBoundPromptPortfolioReceipt;
pub use compat::OptimizationRequest;
pub use compat::PromptCandidate;
pub use compat::PromptPortfolioReceipt;
pub use compat::local_shadow;
pub use compat::optimize;
pub use compat::optimize_with_factor_graph;

pub(crate) use compat::canonical_factor_pair;
pub(crate) use compat::optimize_with_factor_graph_constraints;
