//! Availability boundary for managed Windows filesystem execution.
//!
//! Both launch backends currently derive WRITE_RESTRICTED tokens. Native
//! qualification showed that these tokens permit deletion outside the writable
//! roots. The dedicated-account runner uses the same primitive and does not
//! mediate individual filesystem operations, so it is not a qualified fallback.
//!
//! Keep this check ahead of ACL changes, helper setup, and process creation at
//! every execution entry point. An unavailable isolation mechanism is a launch
//! error, not a policy denial that can be retried without the sandbox.

/// Reject execution until a backend can enforce the complete managed filesystem
/// policy, including deletion. This also applies to read-only profiles.
///
/// The command-runner binary calls this directly before its own side effects;
/// callers must not substitute an elevated or unsandboxed launch on failure.
pub fn ensure_windows_managed_filesystem_isolation() -> std::io::Result<()> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "Windows managed filesystem execution is unavailable: the current token backends cannot enforce deletion restrictions; the requested child was not launched and no elevation or unsandboxed fallback is permitted",
    ))
}

#[cfg(test)]
#[path = "filesystem_isolation_tests.rs"]
mod tests;
