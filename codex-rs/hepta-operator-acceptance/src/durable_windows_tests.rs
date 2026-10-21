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
fn windows_private_parent_requires_real_directory_handle_sync() {
    // Actual directory flush capability is part of the proof. If the OS
    // refuses it, the acceptance gate must remain closed rather than treat
    // a file-only sync as equivalent to durable directory topology.
    let temporary = tempfile::tempdir().expect("temporary parent directory");
    crate::durable::sync_verified_sidecar_parent(temporary.path())
        .expect("Windows directory synchronization must be supported");
    let regular = temporary.path().join("not-a-parent");
    std::fs::write(&regular, b"file").expect("write regular test file");
    assert!(
        crate::durable::sync_verified_sidecar_parent(&regular).is_err(),
        "a regular file must never substitute for the containing directory"
    );
}
