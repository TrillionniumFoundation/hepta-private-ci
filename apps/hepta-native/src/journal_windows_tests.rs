use std::path::Path;
use std::path::PathBuf;
use std::process::Command;

use super::FileAccess;
use crate::private_state::PrivateStateRoot;
use crate::private_state_test_support::private_tempdir;

fn grant_everyone_read(path: &Path) {
    let executable =
        PathBuf::from(std::env::var_os("SystemRoot").unwrap()).join("System32/icacls.exe");
    let output = Command::new(executable)
        .arg(path)
        .args(["/grant", "*S-1-1-0:(R)", "/Q"])
        .output()
        .unwrap();
    assert!(output.status.success(), "{output:?}");
}

#[test]
fn native_snapshot_wal_and_lock_reject_public_child_acls_without_mutation() {
    let directory = private_tempdir();
    let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
    let snapshot = directory.path().join("snapshot.json");
    super::write_private(&root, &snapshot, b"private snapshot").unwrap();
    super::append_wal_frame(&root, &snapshot, b"private wal", 4096, 1024).unwrap();
    let lock = directory.path().join("snapshot.json.lock");
    drop(
        super::open_private_file_in(&root, &lock, FileAccess::Lock, /*preexisting*/ false).unwrap(),
    );

    for path in [&snapshot, &super::wal_path(&snapshot), &lock] {
        let original = std::fs::read(path).unwrap();
        grant_everyone_read(path);
        root.verify().unwrap();
        for access in [
            FileAccess::Read,
            FileAccess::Write,
            FileAccess::Append,
            FileAccess::Lock,
        ] {
            assert!(
                super::open_private_file_in(&root, path, access, /*preexisting*/ true).is_err()
            );
            assert_eq!(std::fs::read(path).unwrap(), original);
        }
    }
    assert!(super::read_wal_frames(&root, &snapshot, 4096, 1024).is_err());
    assert!(super::truncate_wal(&root, &snapshot, 0).is_err());
}
