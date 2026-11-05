/// Create a fresh test home with explicit custody before SQLite opens it.
pub(crate) fn private_home() -> std::io::Result<tempfile::TempDir> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
    }
    #[cfg(not(unix))]
    tempfile::tempdir()
}
