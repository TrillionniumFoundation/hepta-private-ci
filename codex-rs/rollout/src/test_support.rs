/// Create a fresh test home with explicit custody before SQLite opens it.
pub(crate) fn private_home() -> std::io::Result<tempfile::TempDir> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut builder = tempfile::Builder::new();
        builder.permissions(std::fs::Permissions::from_mode(0o700));
        #[cfg(target_os = "macos")]
        {
            // Keep fresh fixture paths in the same physical namespace retained by State.
            builder.tempdir_in(std::env::temp_dir().canonicalize()?)
        }
        #[cfg(not(target_os = "macos"))]
        builder.tempdir()
    }
    #[cfg(not(unix))]
    tempfile::tempdir()
}
