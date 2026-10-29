#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::Component;
use std::path::Path;
use std::process::Command;
use std::process::Output;

use tempfile::TempDir;

pub(crate) fn private_tempdir(label: &str) -> TempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    temporary
}

// Test-only signing uses a real OpenSSH process; production verifies natively.
pub(crate) fn ssh_keygen(root: &Path) -> Command {
    #[cfg(windows)]
    let mut command = {
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
        Command::new(executable)
    };
    #[cfg(not(windows))]
    let mut command = Command::new("/usr/bin/ssh-keygen");
    #[cfg(windows)]
    command.current_dir(openssh_spawn_cwd(root));
    #[cfg(not(windows))]
    command.current_dir(root);
    command
}


#[cfg(windows)]
fn openssh_spawn_cwd(root: &Path) -> std::path::PathBuf {
    let path = root
        .to_str()
        .expect("Windows OpenSSH fixture path must be Unicode");
    let Some(dos_path) = path.strip_prefix(r"\\?\") else {
        return root.to_path_buf();
    };
    let bytes = dos_path.as_bytes();
    assert!(
        bytes.len() >= 3
            && bytes[0].is_ascii_alphabetic()
            && bytes[1] == b':'
            && bytes[2] == b'\\',
        "Windows OpenSSH fixture requires a local drive-letter path: {root:?}"
    );
    let ordinary = std::path::PathBuf::from(dos_path);
    let verified = ordinary
        .canonicalize()
        .expect("revalidate non-verbatim OpenSSH fixture directory");
    assert_eq!(
        verified.as_path(),
        root,
        "OpenSSH subprocess cwd must retain the exact canonical fixture identity"
    );
    ordinary
}

#[cfg(windows)]
#[test]
fn openssh_subprocess_cwd_preserves_canonical_fixture_identity() {
    let temporary = private_tempdir("OpenSSH subprocess cwd test");
    let root = temporary.path().canonicalize().expect("canonical fixture root");
    let spawn_cwd = openssh_spawn_cwd(&root);
    assert!(
        !spawn_cwd.to_string_lossy().starts_with(r"\\?\"),
        "OpenSSH must not inherit a Windows verbatim cwd"
    );
    assert_eq!(
        spawn_cwd.canonicalize().expect("revalidate test cwd"),
        root
    );
}

// Keep canonical paths for trust checks, but do not pass Windows verbatim paths
// as OpenSSH file arguments. Each command runs inside the same fixture root.
pub(crate) fn ssh_keygen_path<'a>(root: &Path, path: &'a Path) -> &'a Path {
    let relative = path
        .strip_prefix(root)
        .expect("OpenSSH input must be within the fixture root");
    assert!(
        !relative.as_os_str().is_empty()
            && relative
                .components()
                .all(|component| matches!(component, Component::Normal(_))),
        "OpenSSH input must be a relative fixture file: {relative:?}"
    );
    relative
}

pub(crate) fn run_ssh_keygen(command: &mut Command) -> Output {
    let output = command
        .output()
        .unwrap_or_else(|error| panic!("start test-only OpenSSH {command:?}: {error}"));
    assert!(
        output.status.success(),
        "test-only OpenSSH failed: command={command:?}; cwd={:?}; status={:?}; code={:?}; stdout={:?}; stderr={:?}",
        command.get_current_dir(),
        output.status,
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    output
}
