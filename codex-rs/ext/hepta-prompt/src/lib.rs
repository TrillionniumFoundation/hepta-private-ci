//! Host-bound prompt delivery bridge for the real Codex provider spine.
//!
//! V3 is compiled as ordinary source together with the retained V1/V2
//! compatibility implementation. Product composition can therefore select V3
//! without materializing or rewriting source at qualification time.

#![forbid(unsafe_code)]

#[path = "legacy.rs"]
mod legacy;
pub use legacy::*;

mod v3;
pub use v3::*;
