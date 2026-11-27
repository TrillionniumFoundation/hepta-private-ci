use std::path::Path;
use std::path::PathBuf;

/// Recover the registered Windows workspace spelling after a PathUri round trip.
///
/// Fleet WorkspaceBinding stores the filesystem-canonical root. On Windows that
/// root has a verbatim prefix, which PathUri removes when rendering a native path.
/// Recall and physical-send revalidation must bind the same canonical root as the
/// grant. A missing or redirected workspace fails closed against that binding.
pub(super) fn registered_workspace_path(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute() {
        return None;
    }
    #[cfg(windows)]
    {
        path.canonicalize().ok()
    }
    #[cfg(not(windows))]
    {
        Some(path.to_path_buf())
    }
}

#[cfg(all(test, windows))]
#[path = "federation_workspace_tests.rs"]
mod tests;
