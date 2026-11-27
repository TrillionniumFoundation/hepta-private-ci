//! Admission for the same-user Windows restricted-token backend.
//!
//! The original native regressions prove that an ambient parent-directory
//! `FILE_DELETE_CHILD` grant can authorize deletion outside the requested roots.
//! Removing `WRITE_RESTRICTED` also removes the promised ambient read access, so
//! changing that flag alone is not a replacement for the existing contract.

use std::fmt;

/// The same-user legacy backend cannot enforce its filesystem isolation contract.
///
/// This refusal occurs before token creation, capability persistence, ACL edits,
/// or child launch. Callers must propagate it without retrying the request with
/// unrestricted execution or treating it as successful sandbox qualification.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LegacyWindowsSandboxIsolationUnavailable;

impl fmt::Display for LegacyWindowsSandboxIsolationUnavailable {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(
            "legacy Windows sandbox isolation is unavailable: ambient parent FILE_DELETE_CHILD \
             can bypass deletion boundaries; no qualified replacement preserves this read policy",
        )
    }
}

impl std::error::Error for LegacyWindowsSandboxIsolationUnavailable {}

pub(crate) fn require_legacy_filesystem_isolation() -> anyhow::Result<()> {
    Err(LegacyWindowsSandboxIsolationUnavailable.into())
}
