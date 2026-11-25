//! Fail closed before an unqualified token backend can claim filesystem isolation.

/// The current Windows token backends have no qualified filesystem isolation boundary.
///
/// Native regressions show that an ambient parent `FILE_DELETE_CHILD` grant
/// survives `WRITE_RESTRICTED`, even when an object's `DELETE` is refused.
/// Read-only profiles cannot rely on that token to prevent deletion either.
/// A dedicated broker account does not remove grants to `Everyone` on outside
/// directories, and the broker uses the same unqualified token mechanism.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WindowsFilesystemIsolationUnavailable;

impl std::fmt::Display for WindowsFilesystemIsolationUnavailable {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(
            "Windows filesystem isolation is unavailable: neither the direct token nor the account broker is qualified",
        )
    }
}

impl std::error::Error for WindowsFilesystemIsolationUnavailable {}

pub use WindowsFilesystemIsolationUnavailable as LegacyFilesystemIsolationUnavailable;

/// Internal launch guard shared with the standalone command-runner binary.
///
/// No current backend is admitted. This refuses a managed isolation request;
/// it does not change the permissions of separately authorized unsandboxed work.
#[doc(hidden)]
pub fn require_qualified_windows_filesystem() -> Result<(), WindowsFilesystemIsolationUnavailable> {
    Err(WindowsFilesystemIsolationUnavailable)
}

pub(crate) fn require_qualified_legacy_filesystem()
-> Result<(), LegacyFilesystemIsolationUnavailable> {
    require_qualified_windows_filesystem()
}

#[cfg(test)]
#[path = "legacy_boundary_tests.rs"]
mod tests;
