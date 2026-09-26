//! Authenticated, bounded prompt-intervention portfolio optimization.
//!
//! [`verified`] is the only product-intended pipeline. It seals every stage,
//! revalidates digests across crate boundaries, authenticates independent
//! evidence, constrains graph semantics and emits authority-free receipts.
//!
//! [`canonical`] is the original V1 source implementation retained for wire and
//! source compatibility while callers migrate. Caller-scored `optimize`, the
//! graph adapter and `local_shadow` are explicitly grouped under [`compat`].

#![forbid(unsafe_code)]

pub mod canonical;
pub mod compat;
pub mod verified;
pub mod wire;

// Transitional root re-exports. They preserve current callers while making the
// compatibility boundary explicit in the module tree and implementation map.
pub use compat::GraphBoundPromptPortfolioReceipt;
pub use compat::optimize_with_factor_graph;
pub use compat::local_shadow;
pub use compat::legacy::CandidateDecision;
pub use compat::legacy::CandidateDisposition;
pub use compat::legacy::Error;
pub use compat::legacy::OptimizationRequest;
pub use compat::legacy::PromptCandidate;
pub use compat::legacy::PromptPortfolioReceipt;
pub use compat::legacy::optimize;

pub(crate) use compat::legacy::canonical_factor_pair;
pub(crate) use compat::legacy::optimize_with_factor_graph_constraints;
