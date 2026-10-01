#![cfg(unix)]

use super::*;
use serde_json::Value;
use std::os::unix::fs::PermissionsExt as _;

fn replace(root: &PrivateStateRoot, original: &Path) -> PrivateStateRoot {
    std::fs::rename(root.path(), original).unwrap();
    PrivateStateRoot::open(root.path().to_path_buf()).unwrap()
}

#[test]
fn root_json_publication_rejects_directory_replacement_and_preserves_both_records() {
    for name in ["pending-update.json", "last-update-result.json"] {
        let temp = tempfile::tempdir().unwrap();
        let root = PrivateStateRoot::open(temp.path().join("updates")).unwrap();
        let path = root.path().join(name);
        persist_json_atomic(&root, &path, &"old committed record").unwrap();
        let original = temp.path().join("original");
        let result = persist_json_at_boundary(&root, &path, &"new committed record", || {
            let replacement = replace(&root, &original);
            persist_json_atomic(&replacement, &path, &"replacement sentinel")
        });
        assert!(result.is_err());
        assert_eq!(
            std::fs::read(original.join(name)).unwrap(),
            b"\"old committed record\""
        );
        assert_eq!(std::fs::read(&path).unwrap(), b"\"replacement sentinel\"");
    }
}

#[test]
fn owner_and_runner_locks_cannot_open_or_chmod_a_replacement_directory() {
    for name in ["update-owner.lock", "update-runner.lock"] {
        let temp = tempfile::tempdir().unwrap();
        let root = PrivateStateRoot::open(temp.path().join("updates")).unwrap();
        let original = temp.path().join("original");
        let path = root.path().join(name);
        let result = lock_named(&root, name, || {
            let _replacement = replace(&root, &original);
            std::fs::write(&path, b"replacement lock sentinel")?;
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644))?;
            Ok(())
        });
        assert!(result.is_err());
        assert!(!original.join(name).exists());
        assert_eq!(std::fs::read(&path).unwrap(), b"replacement lock sentinel");
        assert_eq!(
            std::fs::metadata(&path).unwrap().permissions().mode() & 0o777,
            0o644
        );
    }
}

#[test]
fn handoff_contention_cannot_switch_to_a_fresh_owner_lock() {
    let temp = tempfile::tempdir().unwrap();
    let root = PrivateStateRoot::open(temp.path().join("updates")).unwrap();
    let _original_owner = lock_update_root(&root).unwrap();
    let original = temp.path().join("original");
    let mut contentions = 0;
    let result = lock_handoff_at_contention(&root, || {
        contentions += 1;
        let _replacement = replace(&root, &original);
        std::fs::write(
            root.path().join("update-owner.lock"),
            b"fresh lock sentinel",
        )?;
        Ok(())
    });
    assert!(result.is_err());
    assert_eq!(contentions, 1);
    assert_eq!(
        std::fs::read(root.path().join("update-owner.lock")).unwrap(),
        b"fresh lock sentinel"
    );
}

#[test]
fn private_json_read_and_delete_do_not_consume_or_remove_a_replacement_record() {
    let temp = tempfile::tempdir().unwrap();
    let root = PrivateStateRoot::open(temp.path().join("updates")).unwrap();
    let path = root.path().join("pending-update.json");
    persist_json_atomic(&root, &path, &"original record").unwrap();
    let original = temp.path().join("original");
    let replacement = replace(&root, &original);
    persist_json_atomic(&replacement, &path, &"replacement record").unwrap();
    assert!(read_private_json::<Value>(&root, &path, 64 * 1024).is_err());
    assert!(remove_private_file(&root, &path).is_err());
    assert_eq!(
        std::fs::read(original.join("pending-update.json")).unwrap(),
        b"\"original record\""
    );
    assert_eq!(std::fs::read(&path).unwrap(), b"\"replacement record\"");
}

#[test]
fn staged_destination_parent_replacement_never_publishes_to_either_directory() {
    for cut in [
        CopyBoundary::ParentVerified,
        CopyBoundary::Opened,
        CopyBoundary::FileSynced,
    ] {
        let temp = tempfile::tempdir().unwrap();
        let root = PrivateStateRoot::open(temp.path().join("staged")).unwrap();
        let source = temp.path().join("download");
        std::fs::write(&source, b"signed candidate").unwrap();
        let destination = root.path().join("candidate.package");
        std::fs::write(&destination, b"old staging record").unwrap();
        std::fs::set_permissions(&destination, std::fs::Permissions::from_mode(0o600)).unwrap();
        assert_eq!(
            destination.metadata().unwrap().permissions().mode() & 0o777,
            0o600
        );
        let original = temp.path().join("original");
        let mut observed_cut = false;
        let result = copy_at_boundaries(
            &source,
            &destination,
            &crate::model::sha256_hex(b"signed candidate"),
            None,
            Some(&root),
            |boundary| {
                if boundary == cut {
                    observed_cut = true;
                    let _replacement = replace(&root, &original);
                    std::fs::write(&destination, b"replacement staging sentinel")?;
                }
                Ok(())
            },
        );
        assert!(result.is_err());
        assert!(observed_cut, "requested replacement cut was not reached");
        assert_eq!(
            std::fs::read(original.join("candidate.package")).unwrap(),
            b"old staging record"
        );
        assert_eq!(
            std::fs::read(&destination).unwrap(),
            b"replacement staging sentinel"
        );
    }
}

#[test]
fn staged_source_root_replacement_before_commit_preserves_installed_binary() {
    let temp = tempfile::tempdir().unwrap();
    let root = PrivateStateRoot::open(temp.path().join("staged")).unwrap();
    let source = root.path().join("candidate.package");
    std::fs::write(&source, b"signed candidate").unwrap();
    let destination = temp.path().join("installed");
    std::fs::write(&destination, b"installed predecessor").unwrap();
    let original = temp.path().join("original");
    let result = copy_at_boundaries(
        &source,
        &destination,
        &crate::model::sha256_hex(b"signed candidate"),
        Some(&root),
        None,
        |boundary| {
            if boundary == CopyBoundary::FileSynced {
                let _replacement = replace(&root, &original);
                std::fs::write(&source, b"replacement source sentinel")?;
            }
            Ok(())
        },
    );
    assert!(result.is_err());
    assert_eq!(
        std::fs::read(&destination).unwrap(),
        b"installed predecessor"
    );
    assert_eq!(
        std::fs::read(&source).unwrap(),
        b"replacement source sentinel"
    );
    assert_eq!(
        std::fs::read(original.join("candidate.package")).unwrap(),
        b"signed candidate"
    );
}

#[test]
fn legacy_staged_permissions_are_tightened_without_following_a_link_or_changing_an_alias() {
    let temp = tempfile::tempdir().unwrap();
    let root = PrivateStateRoot::open(temp.path().join("staged")).unwrap();
    let package = root.path().join("candidate.package");
    std::fs::write(&package, b"signed candidate").unwrap();
    std::fs::set_permissions(&package, std::fs::Permissions::from_mode(0o644)).unwrap();
    assert_eq!(
        digest_private_file(&root, &package).unwrap(),
        crate::model::sha256_hex(b"signed candidate")
    );
    assert_eq!(
        std::fs::metadata(&package).unwrap().permissions().mode() & 0o777,
        0o600
    );
    let external = temp.path().join("operator-data");
    std::fs::write(&external, b"operator bytes").unwrap();
    std::fs::set_permissions(&external, std::fs::Permissions::from_mode(0o644)).unwrap();
    let link = root.path().join("linked.package");
    std::os::unix::fs::symlink(&external, &link).unwrap();
    assert!(digest_private_file(&root, &link).is_err());
    let alias = root.path().join("aliased.package");
    std::fs::hard_link(&external, &alias).unwrap();
    assert!(digest_private_file(&root, &alias).is_err());
    assert_eq!(
        std::fs::metadata(&external).unwrap().permissions().mode() & 0o777,
        0o644
    );
    assert_eq!(std::fs::read(&external).unwrap(), b"operator bytes");
}
