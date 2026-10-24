//! Prompt intervention optimization.
//!
//! `canonical` is the only active policy pipeline. Historical score-only and
//! local-shadow calculators remain available under `compat` so existing
//! qualification callers can migrate without being mistaken for the canonical
//! product path.

#![forbid(unsafe_code)]

pub mod canonical;
pub mod compat;

// Temporary source-compatibility exports. New code must use `compat::*`
// explicitly; the implementation map records these as compatibility-only.
pub use compat::CandidateDecision;
pub use compat::CandidateDisposition;
pub use compat::Error;
pub use compat::GraphBoundPromptPortfolioReceipt;
pub use compat::OptimizationRequest;
pub use compat::PromptCandidate;
pub use compat::PromptPortfolioReceipt;
pub use compat::optimize;
pub use compat::optimize_with_factor_graph;

/// Compatibility alias for callers that have not yet moved to
/// `codex_hepta_prompt_optimizer::compat::local_shadow`.
pub mod local_shadow {
    pub use crate::compat::local_shadow::*;
}
