#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use tempfile::TempDir;

pub(crate) fn private_tempdir(label: &str) -> TempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    temporary
}

pub(crate) fn openssh_keygen_for_tests() -> &'static str {
    // Windows CI does not have the Unix /usr/bin absolute path. The test
    // still invokes real OpenSSH and must fail if it is not installed.
    #[cfg(windows)]
    {
        "ssh-keygen.exe"
    }
    #[cfg(not(windows))]
    {
        "/usr/bin/ssh-keygen"
    }
}
