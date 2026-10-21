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

// Test-only signing uses a real OpenSSH process; production verifies natively.
pub(crate) fn ssh_keygen() -> std::process::Command {
    #[cfg(windows)]
    {
        let mut directories = Vec::new();
        if let Some(root) = std::env::var_os("SystemRoot") {
            directories.push(
                std::path::PathBuf::from(root)
                    .join("System32")
                    .join("OpenSSH"),
            );
        }
        if let Some(path) = std::env::var_os("PATH") {
            directories.extend(std::env::split_paths(&path));
        }
        let executable = directories
            .into_iter()
            .filter(|directory| directory.is_absolute())
            .map(|directory| directory.join("ssh-keygen.exe"))
            .find(|path| path.is_file())
            .expect("Windows OpenSSH ssh-keygen.exe is required for live signature tests");
        std::process::Command::new(executable)
    }
    #[cfg(not(windows))]
    std::process::Command::new("/usr/bin/ssh-keygen")
}
