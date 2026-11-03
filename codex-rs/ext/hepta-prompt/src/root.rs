//! Prompt extension for the single Agentd-owned provider spine.
//!
//! V3 compiler objects are projected by Agentd into the canonical runtime
//! attachment. The historical alternate bridge is retained in `v3.rs` as
//! design provenance, not registered or exported as another installer.

#![forbid(unsafe_code)]

#[path = "lib.rs"]
mod canonical_runtime;
pub use canonical_runtime::*;
