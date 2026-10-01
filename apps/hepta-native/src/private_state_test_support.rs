use tempfile::TempDir;

pub fn private_tempdir() -> TempDir {
    let root = tempfile::tempdir().unwrap();
    #[cfg(target_os = "macos")]
    {
        // Establish a no-ACL control on this freshly created, uniquely owned
        // fixture. The production owner never removes an existing ACL.
        let output = std::process::Command::new("/bin/chmod")
            .arg("-N")
            .arg(root.path())
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "owned fixture ACL setup failed: status={:?}, stderr={}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        );
    }
    // Let the production owner create Unix mode 0700 or the Windows protected
    // DACL instead of depending on tempfile's inherited permissions.
    let child = root.path().join("private");
    crate::private_state::PrivateStateRoot::open(&child).unwrap();
    let holding = root.path().with_extension("private-child");
    std::fs::rename(&child, &holding).unwrap();
    std::fs::remove_dir(root.path()).unwrap();
    std::fs::rename(&holding, root.path()).unwrap();
    root
}

#[cfg(target_os = "macos")]
pub(crate) fn add_macos_acl(path: &std::path::Path, rights: &str) -> Vec<u8> {
    use std::os::unix::fs::PermissionsExt as _;

    let mode = std::fs::metadata(path).unwrap().permissions().mode() & 0o777;
    let output = std::process::Command::new("/bin/chmod")
        .args(["+a", &format!("everyone allow {rights}")])
        .arg(path)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "chmod ACL fixture failed: status={:?}, stderr={}",
        output.status,
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        std::fs::metadata(path).unwrap().permissions().mode() & 0o777,
        mode
    );
    macos_acl(path)
}

#[cfg(target_os = "macos")]
pub(crate) fn macos_acl(path: &std::path::Path) -> Vec<u8> {
    let output = std::process::Command::new("/bin/ls")
        .arg("-lde")
        .arg(path)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "ls ACL fixture failed: status={:?}, stderr={}",
        output.status,
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(String::from_utf8_lossy(&output.stdout).contains("everyone allow"));
    // The first line contains size, timestamps and pathname. Atomic temporary
    // creation/cleanup can change directory stats while retaining the exact ACL.
    let entry_start = output
        .stdout
        .iter()
        .position(|byte| *byte == b'\n')
        .map_or(output.stdout.len(), |index| index + 1);
    let entries = output.stdout[entry_start..].to_vec();
    assert!(String::from_utf8_lossy(&entries).contains("everyone allow"));
    entries
}
