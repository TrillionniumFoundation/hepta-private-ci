use super::FileSnapshot;
use super::open_without_following;
use super::verify_unchanged;
use crate::durable::secure_hash;
use crate::durable::secure_read;

#[test]
fn hardlinked_artifacts_are_rejected_before_reading_or_hashing() {
    let temporary = tempfile::tempdir().expect("temporary artifact directory");
    let artifact = temporary.path().join("artifact");
    std::fs::write(&artifact, b"sealed").expect("write artifact");
    std::fs::hard_link(&artifact, temporary.path().join("alias")).expect("create hardlink");

    assert!(secure_read(&artifact, /*max_bytes*/ 64).is_err());
    assert!(secure_hash(&artifact).is_err());
}

#[test]
fn hardlinks_added_after_open_are_rejected() {
    let temporary = tempfile::tempdir().expect("temporary artifact directory");
    let artifact = temporary.path().join("artifact");
    std::fs::write(&artifact, b"sealed").expect("write artifact");
    let file = open_without_following(&artifact).expect("open artifact");
    let before = FileSnapshot::capture(&file, "artifact").expect("capture original handle");
    std::fs::hard_link(&artifact, temporary.path().join("alias")).expect("create hardlink");

    assert!(verify_unchanged(&file, &artifact, &before, "artifact").is_err());
}

#[test]
fn path_replacement_after_open_is_rejected() {
    let temporary = tempfile::tempdir().expect("temporary artifact directory");
    let artifact = temporary.path().join("artifact");
    std::fs::write(&artifact, b"sealed").expect("write artifact");
    let file = open_without_following(&artifact).expect("open artifact");
    let before = FileSnapshot::capture(&file, "artifact").expect("capture original handle");
    std::fs::rename(&artifact, temporary.path().join("original")).expect("move original artifact");
    std::fs::write(&artifact, b"sealed").expect("replace artifact with the same bytes");

    assert!(verify_unchanged(&file, &artifact, &before, "artifact").is_err());
}

#[test]
fn owner_private_directory_and_child_file_are_readable_without_world_ace() {
    let root = crate::test_support::private_tempdir("Windows private owner evidence");
    crate::durable::verify_secure_directory(root.path(), "owner evidence root")
        .expect("real protected owner-only DACL");
    let artifact = root.path().join("private-state.json");
    std::fs::write(&artifact, b"authenticated-evidence")
        .expect("write test data under protected root");
    assert_eq!(
        secure_read(&artifact, /*max_bytes*/ 128).unwrap(),
        b"authenticated-evidence"
    );
}

#[test]
fn world_readable_native_acl_is_refused_before_private_state_consumption() {
    let root = crate::test_support::private_tempdir("Windows ACL negative control");
    let artifact = root.path().join("unsafe-data.txt");
    std::fs::write(&artifact, b"never-consume-insecure-evidence").unwrap();
    super::allow_untrusted_test_principal(&artifact).expect("injected insecure ACL");
    assert!(secure_read(&artifact, /*max_bytes*/ 256).is_err());
    assert!(crate::durable::secure_hash(&artifact).is_err());
    assert_eq!(
        std::fs::read(&artifact).unwrap(),
        b"never-consume-insecure-evidence"
    );
}

#[test]
fn native_windows_owner_lock_is_exclusive_and_reopens_after_release() {
    let root = crate::test_support::private_tempdir("Windows owner lock negative control");
    let owner = crate::durable::lock_sidecar(root.path()).expect("first exclusive owner");
    assert!(crate::durable::lock_existing_sidecar(root.path()).is_err());
    drop(owner);
    let reopened = crate::durable::lock_existing_sidecar(root.path());
    assert!(reopened.is_ok(), "original owner was released on close");
}
