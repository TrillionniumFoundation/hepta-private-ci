//! Compatibility-only prompt optimization surfaces.
//!
//! These APIs preserve historical source and qualification behavior. They are
//! not the registered canonical policy pipeline and must not be used to create
//! production prompt portfolios.

#[path = "compat_legacy.rs"]
mod legacy;
pub use legacy::*;

#[path = "graph.rs"]
pub mod graph;
pub use graph::GraphBoundPromptPortfolioReceipt;
pub use graph::optimize_with_factor_graph;

#[path = "local_shadow.rs"]
pub mod local_shadow;
