//! Builds the actual path dependency and directly reuses its qualification tests.
//! No SQLite C implementation or Rust VFS implementation is copied into this crate.

#[cfg(not(windows))]
compile_error!("this native qualification must execute on Windows");

pub use libsqlite3_sys::*;

#[cfg(all(test, windows))]
#[path = "../../../../codex-rs/third_party/libsqlite3-sys-0.39.1/src/hepta_owner_tests.rs"]
mod hepta_owner_tests;
