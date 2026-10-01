use std::io::Read as _;

use super::Boundary;
use super::FileAccess;
use crate::private_state::PrivateStateRoot;
use crate::private_state_test_support::grant_everyone_read;
use crate::private_state_test_support::private_tempdir;
use crate::private_state_test_support::windows_acl;

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

#[test]
fn snapshot_rejects_existing_destination_dacl_without_replacing_evidence() {
    for boundary in [
        Boundary::ParentVerified,
        Boundary::Opened,
        Boundary::FileSynced,
    ] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
        let path = root.path().join("snapshot");
        super::write_private(&root, &path, b"operator evidence").unwrap();
        let mut acl = None;
        let result = super::write_at_boundaries(&root, &path, b"new snapshot", |observed| {
            if observed == boundary {
                acl = Some(grant_everyone_read(&path));
                root.verify().unwrap();
            }
            Ok(())
        });
        assert!(result.is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"operator evidence");
        assert_eq!(windows_acl(&path), acl.unwrap());
    }
}

#[test]
fn snapshot_rejects_atomic_temp_dacl_before_writing_and_before_commit() {
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
                let file = std::fs::File::open(&temps[0]).unwrap();
                root.verify_mutable_file(&file).unwrap();
                grant_everyone_read(&temps[0]);
                assert!(root.verify_mutable_file(&file).is_err());
                retained = Some(file);
            }
            Ok(())
        });
        assert!(result.is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"old snapshot");
        let mut retained = retained.unwrap();
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
fn snapshot_rejects_held_parent_dacl_drift_at_each_publish_cut() {
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
        let result = super::write_at_boundaries(&root, &path, b"new snapshot", |observed| {
            if observed == boundary {
                acl = Some(grant_everyone_read(root.path()));
            }
            Ok(())
        });
        assert!(result.is_err());
        assert!(root.verify().is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"old snapshot");
        assert_eq!(windows_acl(root.path()), acl.unwrap());
    }
}

#[test]
fn snapshot_rejects_linked_existing_destination_without_changing_either_entry() {
    let directory = private_tempdir();
    let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
    let path = root.path().join("snapshot");
    let alias = root.path().join("snapshot-alias");
    super::write_private(&root, &path, b"old snapshot").unwrap();
    std::fs::hard_link(&path, &alias).unwrap();
    root.verify().unwrap();
    assert!(super::write_private(&root, &path, b"new snapshot").is_err());
    assert_eq!(std::fs::read(&path).unwrap(), b"old snapshot");
    assert_eq!(std::fs::read(&alias).unwrap(), b"old snapshot");
}
