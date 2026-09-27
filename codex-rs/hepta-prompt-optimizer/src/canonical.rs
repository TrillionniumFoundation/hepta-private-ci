//! The single verified prompt policy API.
//!
//! Public raw DTOs are inspection/transport values, not admitted phase objects.
//! Only the owner-bound pipeline can construct a verified phase. The arithmetic
//! engine is private and cannot be invoked by downstream product consumers.

pub use codex_hepta_kg as knowledge_graph;

#[path = "canonical_body.rs"]
mod body;
pub use body::*;

#[cfg(test)]
#[path = "canonical_orchestration_tests.rs"]
mod orchestration_tests;
