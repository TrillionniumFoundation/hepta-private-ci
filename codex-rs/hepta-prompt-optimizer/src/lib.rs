//! Canonical prompt-intervention optimization plus explicitly isolated legacy compatibility.
//!
//! New product code must use [`canonical`]. The [`compat`] namespace retains the
//! pre-canonical shadow APIs only for bounded migration and qualification.

#![forbid(unsafe_code)]

pub mod canonical;
pub mod compat;

pub(crate) use compat::canonical_factor_pair;
pub(crate) use compat::optimize_with_factor_graph_constraints;

// Temporary source-compatibility re-exports. They are deliberately deprecated so
// new callers cannot mistake the legacy greedy surface for the canonical policy.
#[allow(deprecated)]
#[deprecated(note = "use codex_hepta_prompt_optimizer::compat explicitly; product code must use canonical")]
pub use compat::CandidateDecision;
#[allow(deprecated)]
#[deprecated(note = "use codex_hepta_prompt_optimizer::compat explicitly; product code must use canonical")]
pub use compat::CandidateDisposition;
#[allow(deprecated)]
#[deprecated(note = "use codex_hepta_prompt_optimizer::compat explicitly; product code must use canonical")]
pub use compat::Error;
#[allow(deprecated)]
#[deprecated(note = "use codex_hepta_prompt_optimizer::compat explicitly; product code must use canonical")]
pub use compat::GraphBoundPromptPortfolioReceipt;
#[allow(deprecated)]
#[deprecated(note = "use codex_hepta_prompt_optimizer::compat explicitly; product code must use canonical")]
pub use compat::OptimizationRequest;
#[allow(deprecated)]
#[deprecated(note = "use codex_hepta_prompt_optimizer::compat explicitly; product code must use canonical")]
pub use compat::PromptCandidate;
#[allow(deprecated)]
#[deprecated(note = "use codex_hepta_prompt_optimizer::compat explicitly; product code must use canonical")]
pub use compat::PromptPortfolioReceipt;
#[allow(deprecated)]
#[deprecated(note = "use codex_hepta_prompt_optimizer::compat::local_shadow explicitly")]
pub use compat::local_shadow;
#[allow(deprecated)]
#[deprecated(note = "use codex_hepta_prompt_optimizer::compat::optimize explicitly")]
pub use compat::optimize;
#[allow(deprecated)]
#[deprecated(note = "use codex_hepta_prompt_optimizer::compat::optimize_with_factor_graph explicitly")]
pub use compat::optimize_with_factor_graph;
