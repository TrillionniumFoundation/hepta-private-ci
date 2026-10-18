use super::FileSnapshot;
use super::open_without_following;
use super::verify_unchanged;
use crate::durable::secure_hash;
use crate::durable::secure_read;

#[test]
fn durable_writes_flush_the_real_directory_and_preserve_payloads()
-> Result<(), Box<dyn std::error::Error>> {
    let temporary = tempfile::tempdir()?;
    let artifact = temporary.path().join("artifact");
    crate::durable::write_private_new(&artifact, b"first")?;
    assert_eq!(secure_read(&artifact, /*max_bytes*/ 64)?, b"first");
    crate::durable::write_private_atomic_replace(
        &artifact,
        &temporary.path().join("artifact.next"),
        b"replacement",
    )?;
    assert_eq!(secure_read(&artifact, /*max_bytes*/ 64)?, b"replacement");
    Ok(())
}

#[test]
fn directory_barrier_rejects_files_missing_paths_and_junctions()
-> Result<(), Box<dyn std::error::Error>> {
    let temporary = tempfile::tempdir()?;
    let artifact = temporary.path().join("artifact");
    let missing = temporary.path().join("missing");
    std::fs::write(&artifact, b"retained")?;
    assert!(super::sync_directory(&artifact).is_err());
    assert!(super::sync_directory(&missing).is_err());
    assert!(!missing.exists());

    let real = temporary.path().join("real");
    let alias = temporary.path().join("alias");
    std::fs::create_dir(&real)?;
    let output = std::process::Command::new("cmd.exe")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&alias)
        .arg(&real)
        .output()?;
    assert!(
        output.status.success(),
        "junction creation failed: {output:?}"
    );
    assert!(super::sync_directory(&alias).is_err());
    std::fs::remove_dir(alias)?;
    assert_eq!(std::fs::read(artifact)?, b"retained");
    Ok(())
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
