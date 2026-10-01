//! OS private-directory, identity and durable replacement primitives.
//!
//! This utility has no domain authority or product dependencies. Callers retain
//! ownership of their state and authorization decisions.

#![cfg_attr(not(windows), allow(dead_code))]

#[cfg(windows)]
mod windows;

#[cfg(windows)]
pub use windows::PrivateStateDirectory;

#[cfg(windows)]
pub use windows::opened_resource_identity;

#[cfg(target_os = "macos")]
mod macos;

#[cfg(target_os = "macos")]
pub use macos::verify_private_permissions;
