//! Compatibility exports for the shared OS private-state utility.

#![cfg_attr(not(windows), allow(dead_code))]

#[cfg(windows)]
mod windows;

#[cfg(windows)]
pub use windows::PrivateStateDirectory;

#[cfg(windows)]
pub use windows::opened_resource_identity;
