//! Narrow safe interfaces to native OS APIs that require audited FFI.
#![deny(unsafe_op_in_unsafe_fn)]

#[cfg(any(target_os = "windows", target_os = "macos"))]
pub mod picker;
#[cfg(target_os = "windows")]
pub mod registrar;

#[cfg(target_os = "windows")]
pub mod pipe;
