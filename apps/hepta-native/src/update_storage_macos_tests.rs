use super::CopyBoundary;
use crate::model::sha256_hex;
use crate::private_state::PrivateStateRoot;
use crate::private_state_test_support::add_macos_acl;
use crate::private_state_test_support::macos_acl;
use crate::private_state_test_support::private_tempdir;
use std::io::Read as _;
use std::os::unix::fs::PermissionsExt as _;

#[test]
fn staged_file_acl_rejects_digest_and_migration_without_changing_bytes() {
    for mode in [0o600, 0o751] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
        let path = root.path().join("package");
        std::fs::write(&path, b"operator evidence").unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode)).unwrap();
        let acl = add_macos_acl(&path, "read");
        assert!(super::digest_private_file(&root, &path).is_err());
        assert_eq!(path.metadata().unwrap().permissions().mode() & 0o777, mode);
        assert_eq!(std::fs::read(&path).unwrap(), b"operator evidence");
        assert_eq!(macos_acl(&path), acl);
    }
}

#[test]
fn private_copy_rejects_temp_acl_before_copying_and_before_publication() {
    for boundary in [CopyBoundary::Opened, CopyBoundary::FileSynced] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open(directory.path().join("state")).unwrap();
        let source = directory.path().join("incoming");
        std::fs::write(&source, b"admitted package").unwrap();
        let destination = root.path().join("staged");
        super::copy_to_private_root(
            &root,
            &source,
            &destination,
            &sha256_hex(b"admitted package"),
        )
        .unwrap();
        std::fs::write(&source, b"new package").unwrap();
        let mut retained = None;
        assert!(
            super::copy_at_boundaries(
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
                        assert_eq!(
                            temps[0].metadata().unwrap().permissions().mode() & 0o777,
                            0o600
                        );
                        add_macos_acl(&temps[0], "read");
                        retained = Some(std::fs::File::open(&temps[0]).unwrap());
                    }
                    Ok(())
                }
            )
            .is_err()
        );
        assert_eq!(std::fs::read(&destination).unwrap(), b"admitted package");
        let mut retained = retained.unwrap();
        assert!(codex_utils_private_state::verify_private_permissions(&retained).is_err());
        let mut bytes = Vec::new();
        retained.read_to_end(&mut bytes).unwrap();
        let expected: &[u8] = if boundary == CopyBoundary::Opened {
            b""
        } else {
            b"new package"
        };
        assert_eq!(bytes, expected);
        std::fs::remove_file(source).unwrap();
    }
}

#[test]
fn private_copy_rejects_parent_acl_drift_before_writing_or_publishing() {
    for boundary in [
        CopyBoundary::ParentVerified,
        CopyBoundary::Opened,
        CopyBoundary::FileSynced,
    ] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open(directory.path().join("state")).unwrap();
        let source = directory.path().join("incoming");
        std::fs::write(&source, b"new package").unwrap();
        let destination = root.path().join("staged");
        std::fs::write(&destination, b"old package").unwrap();
        std::fs::set_permissions(&destination, std::fs::Permissions::from_mode(0o600)).unwrap();
        let mut acl = None;
        assert!(
            super::copy_at_boundaries(
                &source,
                &destination,
                &sha256_hex(b"new package"),
                /*source_root*/ None,
                Some(&root),
                |observed| {
                    if observed == boundary {
                        acl = Some(add_macos_acl(root.path(), "list,search"));
                    }
                    Ok(())
                }
            )
            .is_err()
        );
        assert_eq!(std::fs::read(&destination).unwrap(), b"old package");
        assert_eq!(macos_acl(root.path()), acl.unwrap());
        std::fs::remove_file(source).unwrap();
    }
}

#[test]
fn private_copy_rejects_existing_destination_acl_without_replacing_evidence() {
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
        std::fs::write(&destination, b"operator evidence").unwrap();
        std::fs::set_permissions(&destination, std::fs::Permissions::from_mode(0o600)).unwrap();
        let mut acl = None;
        assert!(
            super::copy_at_boundaries(
                &source,
                &destination,
                &sha256_hex(b"new package"),
                /*source_root*/ None,
                Some(&root),
                |observed| {
                    if observed == boundary {
                        acl = Some(add_macos_acl(&destination, "read"));
                    }
                    Ok(())
                }
            )
            .is_err()
        );
        assert_eq!(std::fs::read(&destination).unwrap(), b"operator evidence");
        assert_eq!(macos_acl(&destination), acl.unwrap());
    }
}

#[test]
fn private_source_acl_drift_rejects_installer_copy_before_replacement() {
    for boundary in [CopyBoundary::Opened, CopyBoundary::FileSynced] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open(directory.path().join("state")).unwrap();
        let source = root.path().join("staged");
        let destination = directory.path().join("installed");
        std::fs::write(&source, b"admitted package").unwrap();
        std::fs::set_permissions(&source, std::fs::Permissions::from_mode(0o600)).unwrap();
        std::fs::write(&destination, b"installed predecessor").unwrap();
        let mut acl = None;
        assert!(
            super::copy_at_boundaries(
                &source,
                &destination,
                &sha256_hex(b"admitted package"),
                Some(&root),
                /*private_root*/ None,
                |observed| {
                    if observed == boundary {
                        acl = Some(add_macos_acl(&source, "read"));
                    }
                    Ok(())
                }
            )
            .is_err()
        );
        assert_eq!(
            std::fs::read(&destination).unwrap(),
            b"installed predecessor"
        );
        assert_eq!(std::fs::read(&source).unwrap(), b"admitted package");
        assert_eq!(macos_acl(&source), acl.unwrap());
    }
}

#[test]
fn updater_owner_locks_reject_mode_private_acl_without_clearing_it() {
    let directory = private_tempdir();
    let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
    for name in ["update-owner.lock", "update-runner.lock"] {
        let path = root.path().join(name);
        std::fs::write(&path, b"operator evidence").unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        let acl = add_macos_acl(&path, "read");
        assert!(super::lock_named(&root, name, || Ok(())).is_err());
        assert_eq!(std::fs::read(&path).unwrap(), b"operator evidence");
        assert_eq!(macos_acl(&path), acl);
    }
}

#[test]
fn external_installer_copy_does_not_require_private_acl_policy() {
    let directory = private_tempdir();
    let source = directory.path().join("source");
    let destination = directory.path().join("installed");
    std::fs::write(&source, b"admitted package").unwrap();
    let acl = add_macos_acl(&source, "read");
    super::copy_and_sync(&source, &destination, &sha256_hex(b"admitted package")).unwrap();
    assert_eq!(std::fs::read(destination).unwrap(), b"admitted package");
    assert_eq!(macos_acl(&source), acl);
}
