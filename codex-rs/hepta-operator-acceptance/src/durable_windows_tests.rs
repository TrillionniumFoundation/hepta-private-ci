use super::FileSnapshot;
use super::open_without_following;
use super::verify_unchanged;
use crate::durable::secure_hash;
use crate::durable::secure_read;
use crate::durable::write_private_atomic_replace;
use crate::durable::write_private_new;

#[test]
fn durable_publication_distinguishes_create_from_replace() {
    let directory = tempfile::tempdir().expect("temporary artifact directory");
    let artifact = directory.path().join("artifact");
    let staging = directory.path().join("staging");

    write_private_new(&artifact, b"first").expect("publish the new artifact");
    assert!(write_private_new(&artifact, b"second").is_err());
    assert_eq!(secure_read(&artifact, 16).unwrap(), b"first");
    write_private_atomic_replace(&artifact, &staging, b"second")
        .expect("durably replace the old artifact");
    assert_eq!(secure_read(&artifact, 16).unwrap(), b"second");
    assert_eq!(std::fs::read_dir(directory.path()).unwrap().count(), 1);
}

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
