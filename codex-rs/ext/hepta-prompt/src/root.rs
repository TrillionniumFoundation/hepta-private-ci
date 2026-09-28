//! Prompt-extension crate root with an explicit V3 compile surface.
//!
//! The historical `lib.rs` remains the sole installed physical provider bridge.
//! V3 proof/host types compile as a separately named module, but no product path
//! installs `install_prompt_runtime_v3`; Agentd retains the unique send owner.

#![forbid(unsafe_code)]

#[path = "lib.rs"]
mod canonical_runtime;

pub use canonical_runtime::*;

#[cfg(feature = "prompt-context-v3")]
pub mod v3;
