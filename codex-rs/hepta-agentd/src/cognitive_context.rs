//! Authenticated cognitive-context product boundary.
//!
//! The established SQLite/retrieval implementation is retained byte-for-byte
//! in `cognitive_context_legacy.rs`.  The V2 wrapper turns its planner receipt
//! into a process-generation-bound, monotonic, owner-read-authenticated seal
//! and verifies that seal immediately before final use.

#[path = "cognitive_context_legacy.rs"]
mod legacy;
mod cognitive_context_v2;

pub(crate) use cognitive_context_v2::read_with_retrieval_context_and_learning;
pub(crate) use cognitive_context_v2::revalidate_with_retrieval_context;
pub(crate) use legacy::CognitiveContextError;

#[cfg(test)]
pub(crate) use cognitive_context_v2::read;
#[cfg(test)]
pub(crate) use cognitive_context_v2::read_with_retrieval_context;
#[cfg(test)]
pub(crate) use cognitive_context_v2::revalidate;
