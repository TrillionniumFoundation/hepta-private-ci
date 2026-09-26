//! Explicit migration-only compatibility namespace.
//!
//! New product code must use [`crate::verified`] and the authenticated canonical
//! V2 pipeline. These modules remain available only so existing source callers
//! can migrate without silently changing semantics.

pub mod canonical_v1 {
    pub use crate::canonical::*;
}

#[path = "../graph.rs"]
pub mod graph;
#[path = "../local_shadow.rs"]
pub mod local_shadow;
pub mod legacy;

pub use graph::GraphBoundPromptPortfolioReceipt;
pub use graph::optimize_with_factor_graph;
pub use legacy::CandidateDecision;
pub use legacy::CandidateDisposition;
pub use legacy::Error;
pub use legacy::OptimizationRequest;
pub use legacy::PromptCandidate;
pub use legacy::PromptPortfolioReceipt;
pub use legacy::optimize;

#[cfg(test)]
#[path = "../graph_tests.rs"]
mod graph_tests;
