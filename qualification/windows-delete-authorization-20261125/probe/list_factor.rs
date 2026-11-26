//! Independent integration target: no filter skips in the original four-case gate.
#![cfg(windows)]

use codex_windows_delete_boundary_probe::authorization;
use codex_windows_delete_boundary_probe::support;

#[path = "../../../codex-rs/windows-sandbox-rs/src/token_delete_list_factor_tests.rs"]
mod list_factor;
