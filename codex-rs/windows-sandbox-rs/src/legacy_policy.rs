use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
use anyhow::Result;

/// Rejects write policies that the direct restricted-token backend cannot enforce.
///
/// This is admission containment, not a repair of restricted-token DELETE
/// confinement. Direct callers must explicitly use the elevated backend instead;
/// this guard neither launches it nor falls back to a weaker policy.
pub(crate) fn ensure_legacy_write_policy(
    permissions: &ResolvedWindowsSandboxPermissions,
    uses_write_capabilities: bool,
    has_deny_write_paths: bool,
) -> Result<()> {
    // Full-disk write policies intentionally have no enumerated writable roots,
    // so the capability flag alone cannot distinguish them from read-only.
    if permissions.has_full_disk_write_access() || uses_write_capabilities || has_deny_write_paths {
        anyhow::bail!(
            "write-capable or deny-write requests require the elevated Windows sandbox backend"
        );
    }
    Ok(())
}

#[cfg(test)]
#[path = "legacy_policy_tests.rs"]
mod tests;
