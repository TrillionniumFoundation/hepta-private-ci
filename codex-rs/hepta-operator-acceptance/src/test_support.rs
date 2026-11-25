#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use tempfile::TempDir;

pub(crate) struct PrivateTempDir {
    _temporary: TempDir,
    root: std::path::PathBuf,
}

impl PrivateTempDir {
    pub(crate) fn path(&self) -> &std::path::Path {
        &self.root
    }
}

pub(crate) fn private_tempdir(label: &str) -> PrivateTempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    #[cfg(windows)]
    let root = {
        let root = temporary.path().join("private");
        codex_utils_path::windows_private::PrivateDirectory::create_new(&root)
            .unwrap_or_else(|error| panic!("create private {label}: {error}"));
        root
    };
    #[cfg(not(windows))]
    let root = temporary.path().to_path_buf();
    PrivateTempDir {
        _temporary: temporary,
        root,
    }
}

// Production verification never resolves an executable through PATH. These
// synthetic signing fixtures use the platform's installed OpenSSH explicitly.
pub(crate) fn ssh_keygen() -> std::path::PathBuf {
    #[cfg(windows)]
    {
        let system_root = std::env::var_os("SystemRoot")
            .unwrap_or_else(|| panic!("Windows OpenSSH fixture requires SystemRoot"));
        std::path::PathBuf::from(system_root).join("System32/OpenSSH/ssh-keygen.exe")
    }
    #[cfg(not(windows))]
    {
        std::path::PathBuf::from("/usr/bin/ssh-keygen")
    }
}
