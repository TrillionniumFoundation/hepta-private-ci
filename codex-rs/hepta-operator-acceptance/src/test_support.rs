#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use tempfile::TempDir;

pub(crate) fn private_tempdir(label: &str) -> TempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    #[cfg(windows)]
    {
        // Replace only this fresh, empty test allocation with an atomically
        // private directory. Existing product state is never repaired.
        std::fs::remove_dir(temporary.path())
            .unwrap_or_else(|error| panic!("prepare private {label}: {error}"));
        let directory = codex_utils_path::open_private_state_directory(temporary.path())
            .unwrap_or_else(|error| panic!("secure {label}: {error}"));
        drop(directory);
    }
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

#[cfg(windows)]
pub(crate) fn retain_oracle_output(path: &std::path::Path) {
    // The test owns this freshly generated OpenSSH output. Preserve its exact
    // bytes in a new, atomically private file instead of repairing its ACL or
    // accepting the elevated process token's default owner as a product owner.
    let bytes = std::fs::read(path).expect("read independent OpenSSH output");
    std::fs::remove_file(path).expect("remove owned oracle output before private publication");
    crate::durable::write_private_new(path, &bytes).expect("publish exact private oracle output");
    assert_eq!(
        std::fs::read(path).expect("reread retained oracle output"),
        bytes
    );
}
