use super::FileSnapshot;
use super::open_without_following;
use super::verify_unchanged;
use crate::durable::secure_hash;
use crate::durable::secure_read;
use crate::test_support::windows_custody::write_private_fixture;

#[test]
fn hardlinked_artifacts_are_rejected_before_reading_or_hashing() {
    let temporary = crate::test_support::private_tempdir("temporary artifact directory");
    let artifact = temporary.path().join("artifact");
    write_private_fixture(&artifact, b"sealed");
    assert_eq!(
        secure_read(&artifact, 64).expect("private one-link control"),
        b"sealed"
    );
    std::fs::hard_link(&artifact, temporary.path().join("alias")).expect("create hardlink");

    assert!(secure_read(&artifact, /*max_bytes*/ 64).is_err());
    assert!(secure_hash(&artifact).is_err());
}

#[test]
fn hardlinks_added_after_open_are_rejected() {
    let temporary = crate::test_support::private_tempdir("temporary artifact directory");
    let artifact = temporary.path().join("artifact");
    write_private_fixture(&artifact, b"sealed");
    let file = open_without_following(&artifact).expect("open artifact");
    let before = FileSnapshot::capture(&file, "artifact").expect("capture original handle");
    std::fs::hard_link(&artifact, temporary.path().join("alias")).expect("create hardlink");

    assert!(verify_unchanged(&file, &artifact, &before, "artifact").is_err());
}

#[test]
fn path_replacement_after_open_is_rejected() {
    let temporary = crate::test_support::private_tempdir("temporary artifact directory");
    let artifact = temporary.path().join("artifact");
    write_private_fixture(&artifact, b"sealed");
    let file = open_without_following(&artifact).expect("open artifact");
    let before = FileSnapshot::capture(&file, "artifact").expect("capture original handle");
    std::fs::rename(&artifact, temporary.path().join("original")).expect("move original artifact");
    write_private_fixture(&artifact, b"sealed");

    assert!(verify_unchanged(&file, &artifact, &before, "artifact").is_err());
}

#[test]
fn directory_flush_persists_new_and_replaced_sidecars() {
    let temporary = crate::test_support::private_tempdir("temporary sidecar directory");
    let artifact = temporary.path().join("artifact");
    let replacement = temporary.path().join("replacement");
    crate::durable::write_private_new(&artifact, b"first").expect("persist first sidecar");
    assert_eq!(
        secure_read(&artifact, 64).expect("read first sidecar"),
        b"first"
    );
    crate::durable::write_private_atomic_replace(&artifact, &replacement, b"second")
        .expect("persist replacement sidecar");
    assert_eq!(
        secure_read(&artifact, 64).expect("read replacement sidecar"),
        b"second"
    );
    assert!(!replacement.exists());
}

#[test]
fn directory_flush_rejects_regular_files_and_missing_paths() {
    let temporary = crate::test_support::private_tempdir("temporary sidecar directory");
    let artifact = temporary.path().join("artifact");
    write_private_fixture(&artifact, b"sealed");
    assert!(super::sync_directory(&artifact).is_err());
    assert!(super::sync_directory(&temporary.path().join("missing")).is_err());
}
