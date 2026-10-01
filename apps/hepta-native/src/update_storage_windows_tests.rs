use super::CopyBoundary;
use crate::model::sha256_hex;
use crate::private_state::PrivateStateRoot;
use crate::private_state_test_support::grant_everyone_read;
use crate::private_state_test_support::private_tempdir;
use crate::private_state_test_support::windows_acl;
use std::io::Read as _;

#[test]
fn private_copy_rejects_existing_destination_dacl_without_replacing_evidence() {
    for boundary in [
        CopyBoundary::ParentVerified,
        CopyBoundary::Opened,
        CopyBoundary::FileSynced,
    ] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open(directory.path().join("state")).unwrap();
        let source = directory.path().join("incoming");
        let destination = root.path().join("staged");
        std::fs::write(&source, b"new package").unwrap();
        crate::journal_storage::write_private(&root, &destination, b"operator evidence").unwrap();
        let mut acl = None;
        let result = super::copy_at_boundaries(
            &source,
            &destination,
            &sha256_hex(b"new package"),
            /*source_root*/ None,
            Some(&root),
            |observed| {
                if observed == boundary {
                    acl = Some(grant_everyone_read(&destination));
                    root.verify().unwrap();
                }
                Ok(())
            },
        );
        assert!(result.is_err());
        assert_eq!(std::fs::read(&destination).unwrap(), b"operator evidence");
        assert_eq!(windows_acl(&destination), acl.unwrap());
    }
}

#[test]
fn private_copy_rejects_temp_dacl_before_copying_and_before_publication() {
    for boundary in [CopyBoundary::Opened, CopyBoundary::FileSynced] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open(directory.path().join("state")).unwrap();
        let source = directory.path().join("incoming");
        let destination = root.path().join("staged");
        std::fs::write(&source, b"new package").unwrap();
        crate::journal_storage::write_private(&root, &destination, b"old package").unwrap();
        let mut retained = None;
        let result = super::copy_at_boundaries(
            &source,
            &destination,
            &sha256_hex(b"new package"),
            /*source_root*/ None,
            Some(&root),
            |observed| {
                if observed == boundary {
                    let temps: Vec<_> = std::fs::read_dir(root.path())
                        .unwrap()
                        .map(|entry| entry.unwrap().path())
                        .filter(|entry| entry != &destination)
                        .collect();
                    assert_eq!(temps.len(), 1);
                    let file = std::fs::File::open(&temps[0]).unwrap();
                    root.verify_mutable_file(&file).unwrap();
                    grant_everyone_read(&temps[0]);
                    assert!(root.verify_mutable_file(&file).is_err());
                    retained = Some(file);
                }
                Ok(())
            },
        );
        assert!(result.is_err());
        assert_eq!(std::fs::read(&destination).unwrap(), b"old package");
        let mut retained = retained.unwrap();
        let mut bytes = Vec::new();
        retained.read_to_end(&mut bytes).unwrap();
        let expected: &[u8] = if boundary == CopyBoundary::Opened {
            b""
        } else {
            b"new package"
        };
        assert_eq!(bytes, expected);
    }
}

#[test]
fn private_copy_rejects_parent_dacl_drift_before_writing_or_publishing() {
    for boundary in [
        CopyBoundary::ParentVerified,
        CopyBoundary::Opened,
        CopyBoundary::FileSynced,
    ] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open(directory.path().join("state")).unwrap();
        let source = directory.path().join("incoming");
        let destination = root.path().join("staged");
        std::fs::write(&source, b"new package").unwrap();
        crate::journal_storage::write_private(&root, &destination, b"old package").unwrap();
        let mut acl = None;
        let result = super::copy_at_boundaries(
            &source,
            &destination,
            &sha256_hex(b"new package"),
            /*source_root*/ None,
            Some(&root),
            |observed| {
                if observed == boundary {
                    acl = Some(grant_everyone_read(root.path()));
                }
                Ok(())
            },
        );
        assert!(result.is_err());
        assert!(root.verify().is_err());
        assert_eq!(std::fs::read(&destination).unwrap(), b"old package");
        assert_eq!(windows_acl(root.path()), acl.unwrap());
    }
}

#[test]
fn private_source_dacl_drift_rejects_installer_copy_before_replacement() {
    for boundary in [CopyBoundary::Opened, CopyBoundary::FileSynced] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open(directory.path().join("state")).unwrap();
        let source = root.path().join("staged");
        let destination = directory.path().join("installed");
        crate::journal_storage::write_private(&root, &source, b"admitted package").unwrap();
        std::fs::write(&destination, b"installed predecessor").unwrap();
        let mut acl = None;
        let result = super::copy_at_boundaries(
            &source,
            &destination,
            &sha256_hex(b"admitted package"),
            Some(&root),
            /*private_root*/ None,
            |observed| {
                if observed == boundary {
                    acl = Some(grant_everyone_read(&source));
                    root.verify().unwrap();
                }
                Ok(())
            },
        );
        assert!(result.is_err());
        assert_eq!(
            std::fs::read(&destination).unwrap(),
            b"installed predecessor"
        );
        assert_eq!(std::fs::read(&source).unwrap(), b"admitted package");
        assert_eq!(windows_acl(&source), acl.unwrap());
    }
}

#[test]
fn external_installer_copy_does_not_require_private_dacl_policy() {
    let directory = private_tempdir();
    let source = directory.path().join("source");
    let destination = directory.path().join("installed");
    std::fs::write(&source, b"admitted package").unwrap();
    let acl = grant_everyone_read(&source);
    super::copy_and_sync(&source, &destination, &sha256_hex(b"admitted package")).unwrap();
    assert_eq!(std::fs::read(destination).unwrap(), b"admitted package");
    assert_eq!(windows_acl(&source), acl);
}
