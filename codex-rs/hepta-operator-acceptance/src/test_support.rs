#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

#[cfg(windows)]
use std::path::PathBuf;
use std::process::Command;

use tempfile::TempDir;

pub(crate) fn private_tempdir(label: &str) -> TempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    temporary
}

// Fixtures use the platform's real OpenSSH tools; production verification stays native.
pub(crate) fn ssh_keygen() -> Command {
    #[cfg(windows)]
    let program = PathBuf::from(
        std::env::var_os("SystemRoot").expect("Windows test runner must provide SystemRoot"),
    )
    .join("System32")
    .join("OpenSSH")
    .join("ssh-keygen.exe");
    #[cfg(not(windows))]
    let program = "/usr/bin/ssh-keygen";
    Command::new(program)
}
