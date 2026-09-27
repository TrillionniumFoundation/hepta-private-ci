//! Source-aware context compiler.
//!
//! The legacy crate root remains intact as an internal compatibility module.
//! Provider-bound V2 closure is exported alongside it while migration proceeds.

#![forbid(unsafe_code)]

#[path = "lib.rs"]
mod compatibility;

pub use compatibility::*;

mod provider_bound;

pub use provider_bound::*;
