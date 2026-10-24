use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

fn fixture() -> (tempfile::TempDir, Arc<RootAuthorityDirectory>) {
    assert_eq!(rustix::process::geteuid().as_raw(), 0);
    let directory = tempfile::Builder::new()
        .prefix("hepta-root-input-")
        .tempdir_in("/run")
        .unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let root = RootAuthorityDirectory::open(directory.path()).unwrap();
    (directory, root)
}

#[test]
#[ignore = "actual Root complete original observation candidate and same-inode publication"]
fn root_observation_resume_keeps_complete_original_bytes_and_inode() {
    let (directory, root) = fixture();
    let id = "native.original.initialization.v1";
    let original = root
        .save_observation(id, br#"{"schema_version":1,"initial":"retained"}"#)
        .unwrap();
    let expected = original.payload().to_vec();
    let name = observation_name(id).unwrap();
    let inode = directory.path().join(&name).metadata().unwrap().ino();
    drop(original);
    std::fs::rename(
        directory.path().join(&name),
        directory.path().join(format!("{name}.next")),
    )
    .unwrap();
    assert!(root.open_observation(id).is_err());
    let restored = root.resume_observation(id).unwrap();
    assert_eq!(restored.payload(), expected);
    assert_eq!(
        directory.path().join(&name).metadata().unwrap().ino(),
        inode
    );
    assert_eq!(root.resume_observation(id).unwrap().payload(), expected);
}

#[test]
#[ignore = "actual Root observation missing/corrupt/wrong-ID candidates stay refused"]
fn root_observation_resume_does_not_invent_missing_or_damaged_original_input() {
    let (directory, root) = fixture();
    let id = "native.original.initialization.v1";
    assert!(root.resume_observation(id).is_err());
    let name = observation_name(id).unwrap();
    let temporary = format!("{name}.next");
    let mut file = root
        .open_private(&temporary, OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL)
        .unwrap();
    file.write_all(b"{incomplete").unwrap();
    file.sync_all().unwrap();
    assert!(root.resume_observation(id).is_err());
    assert_eq!(
        std::fs::read(directory.path().join(&temporary)).unwrap(),
        b"{incomplete"
    );
    assert!(!directory.path().join(&name).exists());
}

#[test]
#[ignore = "actual Root exact immutable configuration alias without replacing canonical data"]
fn root_observation_alias_is_exact_idempotent_and_noreplace() {
    let (directory, root) = fixture();
    let original = root
        .save_observation(
            "native.original.bootstrap.v1",
            b"complete retained bootstrap",
        )
        .unwrap();
    original.publish_initial_alias("bootstrap.json").unwrap();
    let path = directory.path().join("bootstrap.json");
    let first = path.metadata().unwrap();
    original.publish_initial_alias("bootstrap.json").unwrap();
    assert_eq!(path.metadata().unwrap().ino(), first.ino());
    assert_eq!(first.uid(), 0);
    assert_eq!(first.mode() & 0o777, 0o600);
    let different = root
        .save_observation("native.conflicting.input", b"different input")
        .unwrap();
    assert_eq!(
        different.publish_initial_alias("bootstrap.json"),
        Err(AuthorityTrustError::Conflict)
    );
    assert_eq!(std::fs::read(path).unwrap(), original.payload());
    for name in [
        "../escape",
        "frontier-v1-other.json",
        "observation-v1-other.json",
        "bad.lock",
        "bad.next",
    ] {
        assert_eq!(
            original.publish_initial_alias(name),
            Err(AuthorityTrustError::Invalid)
        );
    }
}

#[test]
#[ignore = "actual Root original configuration alias rejects a symlink and retains unpublished bytes"]
fn root_observation_alias_refuses_nonprivate_or_nonregular_canonical_entries() {
    let (directory, root) = fixture();
    let original = root
        .save_observation("native.original.pin.v1", b"same pinned public identity")
        .unwrap();
    let other = directory.path().join("other");
    std::fs::write(&other, b"unrelated").unwrap();
    std::os::unix::fs::symlink(&other, directory.path().join("installation.json")).unwrap();
    assert!(original.publish_initial_alias("installation.json").is_err());
    assert_eq!(std::fs::read(other).unwrap(), b"unrelated");
}
