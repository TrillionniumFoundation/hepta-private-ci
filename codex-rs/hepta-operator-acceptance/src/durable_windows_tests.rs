use std::os::windows::fs::MetadataExt;

use pretty_assertions::assert_eq;

use super::FILE_ATTRIBUTE_REPARSE_POINT;
use super::FileSnapshot;
use super::RetainedDirectory;
use super::open_without_following;
use super::verify_unchanged;
use crate::AcceptanceError;
use crate::durable::secure_hash;
use crate::durable::secure_read;
use crate::durable::write_private_atomic_replace;
use crate::durable::write_private_new;
use crate::test_support::private_tempdir;

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
fn directory_flush_persists_new_and_atomically_replaced_artifacts() {
    let temporary = private_tempdir("temporary durable store");
    let root = temporary.path().canonicalize().expect("canonical store");
    let artifact = root.join("artifact");
    let next = root.join("artifact.next");

    write_private_new(&artifact, b"initial").expect("durable new artifact");
    assert_eq!(
        secure_read(&artifact, /*max_bytes*/ 64).expect("read initial artifact"),
        b"initial"
    );
    write_private_atomic_replace(&artifact, &next, b"replacement")
        .expect("durable replacement artifact");
    assert_eq!(
        secure_read(&artifact, /*max_bytes*/ 64).expect("read replaced artifact"),
        b"replacement"
    );
    assert!(!next.exists());
}

#[test]
fn directory_flush_missing_parent_is_not_created() {
    let temporary = private_tempdir("temporary missing-parent fixture");
    let missing = temporary.path().join("missing");
    let error = RetainedDirectory::open(&missing).expect_err("missing parent must be rejected");
    assert!(matches!(
        error,
        AcceptanceError::Io(error) if error.kind() == std::io::ErrorKind::NotFound
    ));
    assert!(write_private_new(&missing.join("artifact"), b"unpublished").is_err());
    assert!(!missing.exists());
}

#[test]
fn directory_flush_rejects_a_regular_file() {
    let temporary = private_tempdir("temporary directory-type fixture");
    let artifact = temporary.path().join("artifact");
    std::fs::write(&artifact, b"unchanged").expect("seed artifact");

    assert!(RetainedDirectory::open(&artifact).is_err());
    assert_eq!(
        std::fs::read(&artifact).expect("retained artifact"),
        b"unchanged"
    );
}

#[test]
fn directory_flush_rejects_junction_and_ancestor_redirection() {
    let temporary = private_tempdir("temporary reparse fixture");
    let real = temporary.path().join("real-directory");
    let child = real.join("child");
    let alias = temporary.path().join("directory-link");
    std::fs::create_dir_all(&child).expect("real parent directory");
    std::fs::write(child.join("retained"), b"unchanged").expect("seed retained artifact");
    // Junctions do not require the optional symbolic-link privilege. Literal
    // relative names avoid passing fixture paths through cmd's quoting rules.
    let output = std::process::Command::new("cmd.exe")
        .args([
            "/d",
            "/c",
            "mklink",
            "/J",
            "directory-link",
            "real-directory",
        ])
        .current_dir(temporary.path())
        .output()
        .expect("create directory junction");
    assert!(
        output.status.success(),
        "junction creation failed: {output:?}"
    );
    let metadata = std::fs::symlink_metadata(&alias).expect("junction metadata");
    assert_ne!(
        u64::from(metadata.file_attributes()) & FILE_ATTRIBUTE_REPARSE_POINT,
        0
    );

    for path in [&alias, &alias.join("child")] {
        assert!(RetainedDirectory::open(path).is_err());
    }
    assert_eq!(
        std::fs::read(child.join("retained")).expect("retained target"),
        b"unchanged"
    );
    std::fs::remove_dir(&alias).expect("remove fixture junction");
}

#[test]
fn retained_directory_blocks_parent_and_ancestor_rename_until_drop() {
    let temporary = private_tempdir("temporary retained-parent fixture");
    let ancestor = temporary.path().join("ancestor");
    let root = ancestor.join("store");
    let moved = ancestor.join("moved-store");
    let moved_ancestor = temporary.path().join("moved-ancestor");
    std::fs::create_dir_all(&root).expect("real store directory");
    let retained = RetainedDirectory::open(&root).expect("retain parent");

    assert!(std::fs::rename(&root, &moved).is_err());
    assert!(std::fs::rename(&ancestor, &moved_ancestor).is_err());
    retained.sync_all(&root).expect("flush retained directory");
    drop(retained);

    std::fs::rename(&root, &moved).expect("parent released after drop");
    std::fs::rename(&ancestor, &moved_ancestor).expect("ancestor released after drop");
}

#[test]
fn retained_directory_rejects_another_real_parent_identity() {
    let temporary = private_tempdir("temporary parent-identity fixture");
    let first = temporary.path().join("first");
    let second = temporary.path().join("second");
    std::fs::create_dir(&first).expect("first real parent");
    std::fs::create_dir(&second).expect("second real parent");
    let retained = RetainedDirectory::open(&first).expect("retain first parent");

    assert!(retained.sync_all(&second).is_err());
    retained
        .sync_all(&first)
        .expect("flush the original parent");
}
