use super::*;
use pretty_assertions::assert_eq;

#[test]
fn damaged_or_legacy_registry_is_preserved_and_never_reset() {
    let temp = tempfile::tempdir().unwrap();
    let old = temp.path().join("cap_sid");
    fs::write(&old, b"S-1-5-21-1-2-3-4").unwrap();
    let before = fs::read(&old).unwrap();
    assert!(load_or_create_cap_sids(temp.path()).is_err());
    assert_eq!(fs::read(&old).unwrap(), before);
    assert!(!cap_sid_file(temp.path()).exists());
    let fresh = tempfile::tempdir().unwrap();
    load_or_create_cap_sids(fresh.path()).unwrap();
    fs::write(cap_sid_file(fresh.path()), b"{damaged").unwrap();
    assert!(load_or_create_cap_sids(fresh.path()).is_err());
    assert_eq!(fs::read(cap_sid_file(fresh.path())).unwrap(), b"{damaged");
}

#[test]
fn removed_registry_cannot_recreate_history_under_original_checkpoint() {
    let temp = tempfile::tempdir().unwrap();
    load_or_create_cap_sids(temp.path()).unwrap();
    fs::remove_file(cap_sid_file(temp.path())).unwrap();
    assert!(load_or_create_cap_sids(temp.path()).is_err());
    assert!(!cap_sid_file(temp.path()).exists());
}

#[test]
fn persistent_max_plus_one_preserves_all_live_identities() {
    let temp = tempfile::tempdir().unwrap();
    with_registry(temp.path(), |caps| {
        for index in 0..MAX_REGISTERED_ROOTS {
            register_root(
                caps,
                canonical_path_key(&temp.path().join(format!("root-{index}"))),
                RootRole::Additional,
            )?;
        }
        Ok(())
    })
    .unwrap();
    let before = fs::read(cap_sid_file(temp.path())).unwrap();
    assert!(writable_root_cap_sid_for_path(temp.path(), &temp.path().join("MAX+1")).is_err());
    assert_eq!(fs::read(cap_sid_file(temp.path())).unwrap(), before);
    assert_eq!(
        load_or_create_cap_sids(temp.path())
            .unwrap()
            .writable_root_by_path
            .len(),
        MAX_REGISTERED_ROOTS
    );
}

#[test]
fn locked_registry_and_missing_checkpoint_do_not_adopt_or_overwrite_state() {
    let temp = tempfile::tempdir().unwrap();
    load_or_create_cap_sids(temp.path()).unwrap();
    let before = fs::read(cap_sid_file(temp.path())).unwrap();
    let path = temp.path().join("cap_sid.v2.lock");
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .unwrap();
    lock.try_lock().unwrap();
    assert!(load_or_create_cap_sids(temp.path()).is_err());
    assert_eq!(fs::read(cap_sid_file(temp.path())).unwrap(), before);
    drop(lock);
    fs::remove_file(path).unwrap();
    assert!(load_or_create_cap_sids(temp.path()).is_err());
    assert_eq!(fs::read(cap_sid_file(temp.path())).unwrap(), before);
}

#[test]
fn excessive_registry_bytes_are_rejected_without_replacement() {
    let temp = tempfile::tempdir().unwrap();
    load_or_create_cap_sids(temp.path()).unwrap();
    let bytes = vec![b' '; MAX_REGISTRY_BYTES as usize + 1];
    fs::write(cap_sid_file(temp.path()), &bytes).unwrap();
    assert!(load_or_create_cap_sids(temp.path()).is_err());
    assert_eq!(fs::read(cap_sid_file(temp.path())).unwrap(), bytes);
}

#[test]
fn old_same_generation_json_cannot_restore_issued_identity_quota() {
    let temp = tempfile::tempdir().unwrap();
    writable_root_cap_sid_for_path(temp.path(), &temp.path().join("root-a")).unwrap();
    let old = fs::read(cap_sid_file(temp.path())).unwrap();
    writable_root_cap_sid_for_path(temp.path(), &temp.path().join("root-b")).unwrap();
    let checkpoint_path = temp.path().join("cap_sid.v2.lock");
    let checkpoint = fs::read(&checkpoint_path).unwrap();
    fs::write(cap_sid_file(temp.path()), &old).unwrap();
    assert!(load_or_create_cap_sids(temp.path()).is_err());
    assert_eq!(fs::read(cap_sid_file(temp.path())).unwrap(), old);
    assert_eq!(fs::read(checkpoint_path).unwrap(), checkpoint);
}

#[test]
fn fixed_pending_stage_is_preserved_and_fences_all_later_use() {
    let temp = tempfile::tempdir().unwrap();
    load_or_create_cap_sids(temp.path()).unwrap();
    let before = fs::read(cap_sid_file(temp.path())).unwrap();
    let plan = filesystem_capability_plan(temp.path(), temp.path(), &[], &[]).unwrap();
    let stage = temp.path().join("cap_sid.v2.stage");
    fs::write(&stage, b"interrupted update").unwrap();
    assert!(load_or_create_cap_sids(temp.path()).is_err());
    assert!(validate_filesystem_capability_plan(temp.path(), &plan).is_err());
    assert_eq!(fs::read(stage).unwrap(), b"interrupted update");
    assert_eq!(fs::read(cap_sid_file(temp.path())).unwrap(), before);
}

#[test]
fn malformed_or_excessive_checkpoint_is_never_rewritten() {
    for fault in [
        b"malformed".to_vec(),
        vec![b' '; MAX_REGISTRY_BYTES as usize + 1],
    ] {
        let temp = tempfile::tempdir().unwrap();
        load_or_create_cap_sids(temp.path()).unwrap();
        let before = fs::read(cap_sid_file(temp.path())).unwrap();
        let checkpoint = temp.path().join("cap_sid.v2.lock");
        fs::write(&checkpoint, &fault).unwrap();
        assert!(load_or_create_cap_sids(temp.path()).is_err());
        assert_eq!(fs::read(checkpoint).unwrap(), fault);
        assert_eq!(fs::read(cap_sid_file(temp.path())).unwrap(), before);
    }
}

#[test]
fn dangling_legacy_link_is_not_an_empty_namespace() {
    let temp = tempfile::tempdir().unwrap();
    let old = temp.path().join("cap_sid");
    let missing = temp.path().join("missing-target");
    std::os::windows::fs::symlink_file(&missing, &old).unwrap();
    assert!(load_or_create_cap_sids(temp.path()).is_err());
    assert_eq!(fs::read_link(&old).unwrap(), missing);
    assert!(!cap_sid_file(temp.path()).exists());
    assert!(!temp.path().join("cap_sid.v2.lock").exists());
}

#[test]
fn registry_and_checkpoint_links_are_refused_without_mutating_targets() {
    for leaf in ["cap_sid.v2.json", "cap_sid.v2.lock"] {
        let temp = tempfile::tempdir().unwrap();
        load_or_create_cap_sids(temp.path()).unwrap();
        let path = temp.path().join(leaf);
        let before = fs::read(&path).unwrap();
        let target = temp.path().join("link-target");
        fs::write(&target, &before).unwrap();
        fs::remove_file(&path).unwrap();
        std::os::windows::fs::symlink_file(&target, &path).unwrap();
        assert!(load_or_create_cap_sids(temp.path()).is_err());
        assert_eq!(fs::read_link(&path).unwrap(), target);
        assert_eq!(fs::read(target).unwrap(), before);
    }
}

#[test]
fn stale_wire_generation_and_missing_registry_cannot_validate() {
    let temp = tempfile::tempdir().unwrap();
    let cwd = temp.path().join("cwd");
    let plan =
        filesystem_capability_plan(temp.path(), &cwd, std::slice::from_ref(&cwd), &[]).unwrap();
    validate_filesystem_capability_plan(temp.path(), &plan).unwrap();
    let other = tempfile::tempdir().unwrap();
    assert!(validate_filesystem_capability_plan(other.path(), &plan).is_err());
    assert!(!cap_sid_file(other.path()).exists());
    load_or_create_cap_sids(other.path()).unwrap();
    assert!(validate_filesystem_capability_plan(other.path(), &plan).is_err());
}

#[test]
fn every_legacy_namespace_object_is_preserved_without_v2_birth() {
    for relative in [
        ".sandbox/setup_marker.json",
        ".sandbox/sandbox_users.json",
        ".sandbox-secrets/sandbox_users.json",
    ] {
        let temp = tempfile::tempdir().unwrap();
        let old = temp.path().join(relative);
        fs::create_dir_all(old.parent().unwrap()).unwrap();
        fs::write(&old, b"existing-valid-or-uncertain-state").unwrap();
        assert!(load_or_create_cap_sids(temp.path()).is_err());
        assert_eq!(
            fs::read(&old).unwrap(),
            b"existing-valid-or-uncertain-state"
        );
        assert!(!cap_sid_file(temp.path()).exists());
        assert!(!temp.path().join("cap_sid.v2.lock").exists());
    }
}
