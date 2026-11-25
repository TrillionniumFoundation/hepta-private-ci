//! Compile the actual repository fixtures without unrelated product dependencies.

#[cfg(all(windows, test))]
#[path = "../../../codex-rs/windows-sandbox-rs/src/token_delete_authorization_tests.rs"]
mod matrix;
