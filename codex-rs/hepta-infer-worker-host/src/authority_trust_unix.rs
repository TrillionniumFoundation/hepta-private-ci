//! The original host uses the one canonical external trust client in contracts.
pub use codex_hepta_contracts::authority_trust_unix::*;

#[cfg(all(test, target_os = "linux"))]
#[path = "authority_trust_unix_tests.rs"]
pub(crate) mod tests;
