//! Bounded, authority-free prompt intervention optimization.
//!
//! `canonical` is the only active policy implementation. `verified` supplies
//! the sealed production admission states that prevent caller-forged receipts.
//! Historical local and graph selectors remain available under `compat` while
//! downstream callers migrate; root re-exports preserve source compatibility.

#![forbid(unsafe_code)]

pub mod canonical;
pub mod compat;
pub mod verified;

// Historical source-compatible exports. They are compatibility surfaces only;
// new product code must use `canonical` plus `verified`.
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
