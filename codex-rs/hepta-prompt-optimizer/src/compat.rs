//! Compatibility-only prompt optimization surfaces.
//!
//! These APIs preserve historical source and qualification behavior. They are
//! not the registered canonical policy pipeline and must not be used to create
//! production prompt portfolios.

#[path = "compat_legacy.rs"]
mod legacy;
pub use legacy::CandidateDecision;
pub use legacy::CandidateDisposition;
pub use legacy::Error;
pub use legacy::OptimizationRequest;
pub use legacy::PromptCandidate;
pub use legacy::PromptPortfolioReceipt;
pub use legacy::optimize;
pub(crate) use legacy::canonical_factor_pair;
pub(crate) use legacy::optimize_with_factor_graph_constraints;

#[path = "graph.rs"]
pub mod graph;
pub use graph::GraphBoundPromptPortfolioReceipt;
pub use graph::optimize_with_factor_graph;

#[path = "local_shadow.rs"]
pub mod local_shadow;
