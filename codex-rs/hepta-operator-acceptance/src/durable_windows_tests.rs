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
fn directory_flush_uses_a_writable_directory_handle() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let directory = temporary.path().join("durable");
    std::fs::create_dir(&directory).expect("create directory");
    let artifact = directory.join("artifact");
    std::fs::write(&artifact, b"sealed").expect("write artifact");
    super::sync_directory(&directory).expect("flush actual directory handle");
    assert!(super::sync_directory(&artifact).is_err());
    assert!(super::sync_directory(&directory.join("missing")).is_err());
}

#[test]
fn directory_flush_rejects_junctions() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let directory = temporary.path().join("durable");
    std::fs::create_dir(&directory).expect("create directory");
    let alias = temporary.path().join("alias");
    let status = std::process::Command::new("cmd.exe")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&alias)
        .arg(&directory)
        .status()
        .expect("create junction");
    assert!(status.success());
    assert!(super::sync_directory(&alias).is_err());
    super::sync_directory(&directory).expect("real directory remains usable");
}
