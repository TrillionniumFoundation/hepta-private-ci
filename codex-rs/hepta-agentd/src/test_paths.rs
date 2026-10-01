//! Canonical, isolated roots for tests that create Unix-domain sockets.

/// Darwin's normal temporary directory can exhaust SUN_LEN before the fleet
/// layout adds its socket filename. Use the canonical short /tmp parent there.
/// TempDir owns a unique private directory and removes it on drop.
pub(crate) fn socket_test_dir() -> std::io::Result<tempfile::TempDir> {
    #[cfg(target_os = "macos")]
    let parent = std::path::Path::new("/tmp").canonicalize()?;
    #[cfg(not(target_os = "macos"))]
    let parent = std::env::temp_dir().canonicalize()?;
    tempfile::Builder::new().prefix("hepta-").tempdir_in(parent)
}
