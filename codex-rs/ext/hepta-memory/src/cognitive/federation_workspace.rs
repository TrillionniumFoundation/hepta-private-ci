use std::path::Path;
use std::path::PathBuf;

/// Restore the representation used by durable workspace grants, accepting only
/// the drive/UNC namespace prefix conversion performed by PathUri.
pub(super) fn restore_workspace_identity(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute() {
        return None;
    }
    #[cfg(windows)]
    {
        let canonical = std::fs::canonicalize(path).ok()?;
        if !canonical.is_dir()
            || !same_windows_namespace_identity(path.to_str()?, canonical.to_str()?)
        {
            return None;
        }
        Some(canonical)
    }
    #[cfg(not(windows))]
    {
        Some(path.to_path_buf())
    }
}

#[cfg(any(windows, test))]
fn same_windows_namespace_identity(supplied: &str, canonical: &str) -> bool {
    use codex_utils_absolute_path::normalize_windows_device_path;

    let supplied_normalized = normalize_windows_device_path(supplied);
    let canonical_normalized = normalize_windows_device_path(canonical);
    supplied_normalized.as_deref().unwrap_or(supplied)
        == canonical_normalized.as_deref().unwrap_or(canonical)
}

#[cfg(test)]
#[path = "federation_workspace_tests.rs"]
mod tests;
