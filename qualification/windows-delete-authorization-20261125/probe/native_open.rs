//! Separate diagnostic binary, preserving both existing zero-skip gates.
#![cfg(windows)]

use codex_windows_delete_boundary_probe::authorization;
use codex_windows_delete_boundary_probe::support;

#[path = "../../../codex-rs/windows-sandbox-rs/src/token_delete_native_open_tests.rs"]
mod native_open;
