//! Admission for the dedicated-account Windows sandbox backend.
//!
//! Native execution of the original four-cell deletion matrix demonstrated that
//! `WRITE_RESTRICTED` still permits outside-root deletion through ambient parent
//! `FILE_DELETE_CHILD` rights. Narrowing the restricting SIDs did not close it.

use std::fmt;

/// The elevated Windows backend has no qualified filesystem isolation mechanism.
///
/// Propagate this refusal without retrying with unrestricted execution. Refusal
/// does not qualify the original permission invariants or restore functionality.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ElevatedWindowsSandboxIsolationUnavailable;

impl fmt::Display for ElevatedWindowsSandboxIsolationUnavailable {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(
            "elevated Windows sandbox isolation is unavailable: ambient parent FILE_DELETE_CHILD \
             can bypass deletion boundaries; a replacement preserving read, launch and IPC \
             behavior has not been qualified",
        )
    }
}

impl std::error::Error for ElevatedWindowsSandboxIsolationUnavailable {}

/// Refuse unqualified elevated execution before provisioning, ACL edits or spawn.
///
/// The command-runner binary also calls this before its first filesystem mutation
/// so a direct broker request cannot bypass the public library admission paths.
pub fn require_elevated_filesystem_isolation() -> anyhow::Result<()> {
    Err(ElevatedWindowsSandboxIsolationUnavailable.into())
}
