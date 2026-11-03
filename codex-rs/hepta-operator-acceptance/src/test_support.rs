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

// The test oracle is the platform's real OpenSSH executable. Production
// verification does not spawn it or discover an executable on PATH.
pub(crate) fn ssh_keygen() -> std::process::Command {
    #[cfg(windows)]
    let executable = std::path::PathBuf::from(
        std::env::var_os("SystemRoot")
            .expect("Windows SystemRoot is required for the OpenSSH oracle"),
    )
    .join("System32")
    .join("OpenSSH")
    .join("ssh-keygen.exe");
    #[cfg(not(windows))]
    let executable = std::path::PathBuf::from("/usr/bin/ssh-keygen");
    std::process::Command::new(executable)
}
