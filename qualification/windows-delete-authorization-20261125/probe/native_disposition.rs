//! Separate native contract; no filtering or replacement of the original tests.
#![cfg(windows)]

use codex_windows_delete_boundary_probe::support;

#[path = "../../../codex-rs/windows-sandbox-rs/src/token_delete_native_disposition_tests.rs"]
mod native_disposition;
