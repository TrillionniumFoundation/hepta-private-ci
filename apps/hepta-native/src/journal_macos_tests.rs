use super::Boundary;
use super::FileAccess;
use crate::private_state::PrivateStateRoot;
use crate::private_state_test_support::add_macos_acl;
use crate::private_state_test_support::macos_acl;
use crate::private_state_test_support::private_tempdir;
use std::io::Read as _;
use std::os::unix::fs::PermissionsExt as _;

#[test]
fn private_file_acl_rejects_reads_mutation_and_locks_without_changing_evidence() {
    let directory = private_tempdir();
    let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
    let path = root.path().join("state");
    super::write_private(&root, &path, b"operator evidence").unwrap();
    assert_eq!(path.metadata().unwrap().permissions().mode() & 0o777, 0o600);
    let acl = add_macos_acl(&path, "read");
    for access in [
        FileAccess::Read,
        FileAccess::Write,
        FileAccess::Append,
        FileAccess::Lock,
    ] {
        assert!(super::open_private_file_in(&root, &path, access, /*preexisting*/ true).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"operator evidence");
        assert_eq!(macos_acl(&path), acl);
    }
}

#[test]
fn snapshot_rejects_existing_destination_acl_without_replacing_evidence() {
    for boundary in [
        Boundary::ParentVerified,
        Boundary::Opened,
        Boundary::FileSynced,
    ] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
        let path = root.path().join("snapshot");
        super::write_private(&root, &path, b"operator evidence").unwrap();
        assert_eq!(path.metadata().unwrap().permissions().mode() & 0o777, 0o600);
        let mut acl = None;
        assert!(
            super::write_at_boundaries(&root, &path, b"new snapshot", |observed| {
                if observed == boundary {
                    acl = Some(add_macos_acl(&path, "read"));
                }
                Ok(())
            })
            .is_err()
        );
        assert_eq!(std::fs::read(&path).unwrap(), b"operator evidence");
        assert_eq!(macos_acl(&path), acl.unwrap());
    }
}

#[test]
fn snapshot_rejects_atomic_temp_acl_before_writing_and_before_commit() {
    for boundary in [Boundary::Opened, Boundary::FileSynced] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
        let path = root.path().join("snapshot");
        super::write_private(&root, &path, b"old snapshot").unwrap();
        let mut retained = None;
        let result = super::write_at_boundaries(&root, &path, b"new snapshot", |observed| {
            if observed == boundary {
                let temps: Vec<_> = std::fs::read_dir(root.path())
                    .unwrap()
                    .map(|entry| entry.unwrap().path())
                    .filter(|entry| entry != &path)
                    .collect();
                assert_eq!(temps.len(), 1);
                assert_eq!(
                    temps[0].metadata().unwrap().permissions().mode() & 0o777,
                    0o600
                );
                add_macos_acl(&temps[0], "read");
                retained = Some(std::fs::File::open(&temps[0]).unwrap());
            }
            Ok(())
        });
        assert!(result.is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"old snapshot");
        let mut retained = retained.unwrap();
        assert!(codex_utils_private_state::verify_private_permissions(&retained).is_err());
        let mut bytes = Vec::new();
        retained.read_to_end(&mut bytes).unwrap();
        let expected: &[u8] = if boundary == Boundary::Opened {
            b""
        } else {
            b"new snapshot"
        };
        assert_eq!(bytes, expected);
    }
}

#[test]
fn snapshot_rejects_held_parent_acl_drift_at_each_publish_cut() {
    for boundary in [
        Boundary::ParentVerified,
        Boundary::Opened,
        Boundary::FileSynced,
    ] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
        let path = root.path().join("snapshot");
        super::write_private(&root, &path, b"old snapshot").unwrap();
        let mut acl = None;
        assert!(
            super::write_at_boundaries(&root, &path, b"new snapshot", |observed| {
                if observed == boundary {
                    acl = Some(add_macos_acl(root.path(), "list,search"));
                }
                Ok(())
            })
            .is_err()
        );
        assert_eq!(std::fs::read(&path).unwrap(), b"old snapshot");
        assert_eq!(macos_acl(root.path()), acl.unwrap());
    }
}
