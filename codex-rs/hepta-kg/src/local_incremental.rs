//! Frontier-local knowledge-graph mutation planning with a versioned state commitment.
//!
//! Complete V2 generations remain the normative rebuild and audit oracle. V3
//! keeps an owner-local deterministic commitment that is updated only along the
//! changed node/edge frontier, so expensive preparation can occur before a
//! short compare-and-swap write-critical section.

mod canonical;
mod commitment;
mod digest;
mod model;
mod state;

pub use model::KnowledgeLocalIncrementalErrorV3;
pub use model::KnowledgeLocalMutationReceiptV3;
pub use model::KnowledgeLocalMutationWorkV3;
pub use model::KnowledgeLocalStorageDeltaV3;
pub use model::KnowledgeProjectionDeltaV3;
pub use state::KnowledgeLocalIncrementalStateV3;

#[cfg(test)]
mod tests;
