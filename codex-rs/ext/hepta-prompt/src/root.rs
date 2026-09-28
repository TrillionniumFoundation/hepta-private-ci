//! Prompt-extension crate root with an explicit V3 compile surface.
//!
//! The historical `lib.rs` remains the sole installed physical provider bridge.
//! V3 proof and host types compile as a separately named module, while Agentd
//! retains the unique physical-send owner and no second V3 bridge is installed.

#![forbid(unsafe_code)]

#[path = "lib.rs"]
mod canonical_runtime;

pub use canonical_runtime::*;

#[cfg(feature = "prompt-context-v3")]
pub mod v3;
