//! Containment for the elevated restricted-token filesystem boundary.
//!
//! The original four-cell native regression observed outside-root deletion under
//! target DELETE and parent FILE_DELETE_CHILD grants. The dedicated account does
//! not remove ambient Everyone grants from either token access check. Refusal is
//! a temporary compatibility break, not qualification of the requested operation.

use std::fmt;

/// Elevated Windows execution cannot currently enforce its deletion boundary.
///
/// Callers must propagate this refusal without falling back to unrestricted
/// execution, publishing a successful effect receipt, or retrying the same
/// operation through a different backend.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ElevatedWindowsSandboxIsolationUnavailable;

impl fmt::Display for ElevatedWindowsSandboxIsolationUnavailable {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(
            "elevated Windows sandbox isolation is unavailable: ambient DELETE or \
             parent FILE_DELETE_CHILD grants can delete outside writable roots",
        )
    }
}

impl std::error::Error for ElevatedWindowsSandboxIsolationUnavailable {}

/// Refuse before client preparation or the native runner can perform side effects.
///
/// This is public because the command-runner binary shares this admission with
/// the library's capture, session and token-construction entry points.
pub fn require_elevated_filesystem_isolation() -> anyhow::Result<()> {
    Err(ElevatedWindowsSandboxIsolationUnavailable.into())
}
