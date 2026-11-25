#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use tempfile::TempDir;

pub(crate) fn private_tempdir(label: &str) -> TempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    #[cfg(windows)]
    crate::durable::windows::protect_private_test_directory(temporary.path())
        .unwrap_or_else(|error| panic!("secure Windows {label}: {error}"));
    temporary
}
