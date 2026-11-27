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
mod tests {
    use super::registered_workspace_path;
    use codex_utils_path_uri::PathUri;
    use std::path::Path;

    #[test]
    fn uri_workspace_recovers_registered_canonical_identity() {
        let directory = tempfile::tempdir().expect("workspace");
        let registered = directory
            .path()
            .canonicalize()
            .expect("canonical workspace");
        let decoded = PathUri::from_host_native_path(&registered)
            .expect("workspace uri")
            .to_path_buf();
        assert_ne!(decoded, registered, "exercise the removed verbatim prefix");
        assert_eq!(registered_workspace_path(&decoded), Some(registered));
    }

    #[test]
    fn missing_and_relative_workspace_paths_are_rejected() {
        let directory = tempfile::tempdir().expect("workspace");
        let missing = directory.path().join("missing");
        assert_eq!(registered_workspace_path(&missing), None);
        assert_eq!(registered_workspace_path(Path::new("relative")), None);
    }
}
