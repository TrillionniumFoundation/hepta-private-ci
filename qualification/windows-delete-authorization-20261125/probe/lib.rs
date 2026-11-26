//! Compile the actual repository fixtures without unrelated product dependencies.
//!
//! The public modules are qualification support, never a product launcher API.

#[cfg(windows)]
#[path = "../../../codex-rs/windows-sandbox-rs/src/token_delete_access_diagnostics.rs"]
pub mod authorization;
#[cfg(windows)]
#[path = "../../../codex-rs/windows-sandbox-rs/src/token_delete_matrix_support.rs"]
pub mod support;

#[cfg(all(windows, test))]
#[path = "../../../codex-rs/windows-sandbox-rs/src/token_delete_authorization_tests.rs"]
mod matrix;
