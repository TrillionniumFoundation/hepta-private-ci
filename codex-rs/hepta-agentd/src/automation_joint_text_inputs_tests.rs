//! File custody behavior only: these synthetic input bytes are not an H worker
//! request, a registered provider, a model, or permission to perform Training.

use super::*;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;

use codex_hepta_automation::JointTextInputManifestV1;
use codex_hepta_automation::JointTextProfileV1;
use pretty_assertions::assert_eq;

fn fixture() -> (
    tempfile::TempDir,
    JointTextInputCustodyV1,
    JointTextInputRefV1,
) {
    let directory = tempfile::tempdir().expect("private test directory");
    let provider = directory.path().join("provider");
    std::fs::create_dir(&provider).expect("test provider directory");
    std::fs::set_permissions(&provider, std::fs::Permissions::from_mode(0o700))
        .expect("test-only directory mode");
    let path = provider.canonicalize().expect("canonical root");
    let original = std::fs::metadata(&path).expect("test root identity");
    let expected = JointTextRootIdentityV1 {
        device: original.dev(),
        inode: original.ino(),
        uid: original.uid(),
    };
    files::Directory::open_root(&path, &expected)
        .expect("test owner root")
        .write_new("layout.json", ROOT_LAYOUT)
        .expect("test owner provisions original layout");
    let custody =
        JointTextInputCustodyV1::open_existing(&path, &expected).expect("existing private root");
    let reference = JointTextInputRefV1::from_manifest(JointTextInputManifestV1 {
        schema_version: 1,
        profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
        request_sha256: Sha256Digest::for_bytes(b"request bytes\n"),
        request_bytes: 14,
        request_binding_digest: Sha256Digest::for_bytes(b"request binding"),
        predecessor_sha256: Sha256Digest::for_bytes(b"predecessor"),
        predecessor_bytes: 11,
        worker_execution_source_digest: Sha256Digest::for_bytes(b"worker source"),
    })
    .expect("synthetic binding");
    (directory, custody, reference)
}

#[test]
fn root_incarnation_mismatch_is_refused_before_input_creation() {
    let (_root, custody, _) = fixture();
    let actual = std::fs::metadata(&custody.root_path).expect("original root");
    let wrong = JointTextRootIdentityV1 {
        device: actual.dev(),
        inode: actual.ino().checked_add(1).expect("different inode"),
        uid: actual.uid(),
    };
    assert!(JointTextInputCustodyV1::open_existing(&custody.root_path, &wrong).is_err());
    assert!(!custody.root_path.join("inputs").exists());
}

#[test]
fn missing_or_changed_layout_is_refused_before_staging() {
    let (_root, custody, reference) = fixture();
    let layout = custody.root_path.join("layout.json");
    std::fs::remove_file(&layout).expect("test removes original marker");
    assert!(custody.verify_root().is_err());
    assert!(
        custody
            .stage_bound(&reference, b"request bytes\n", b"predecessor")
            .is_err()
    );
    custody
        .root
        .write_new("layout.json", b"{\"schema_version\":1}")
        .expect("test conflicting marker");
    assert!(custody.verify_root().is_err());
    assert!(
        custody
            .stage_bound(&reference, b"request bytes\n", b"predecessor")
            .is_err()
    );
    assert!(!custody.root_path.join("inputs").exists());
    assert_eq!(
        std::fs::read(layout).expect("conflict preserved"),
        b"{\"schema_version\":1}"
    );
}

#[test]
fn identical_inputs_read_back_without_overwriting_and_changed_bytes_are_refused() {
    let (_root, custody, reference) = fixture();
    custody
        .stage_bound(&reference, b"request bytes\n", b"predecessor")
        .expect("first stage");
    let path = custody
        .root_path
        .join("inputs")
        .join(reference.input_id.as_str())
        .join("request.json");
    let first = std::fs::metadata(&path).expect("original metadata");
    custody
        .stage_bound(&reference, b"request bytes\n", b"predecessor")
        .expect("identical stage");
    let second = std::fs::metadata(&path).expect("readback metadata");
    assert_eq!(
        (first.ino(), first.mtime_nsec(), first.ctime_nsec()),
        (second.ino(), second.mtime_nsec(), second.ctime_nsec())
    );
    assert!(
        custody
            .stage_bound(&reference, b"changed bytes\n", b"predecessor")
            .is_err()
    );
    let observed = custody.read(&reference).expect("readback");
    assert_eq!(
        (observed.request, observed.predecessor),
        (b"request bytes\n".to_vec(), b"predecessor".to_vec())
    );
}

#[test]
fn partial_input_and_extra_file_are_retained_and_never_completed_implicitly() {
    let (_root, custody, reference) = fixture();
    let (inputs, _) = custody.root.create("inputs").expect("test inputs");
    let (entry, _) = inputs
        .create(reference.input_id.as_str())
        .expect("partial entry");
    entry
        .write_new("request.json", b"request bytes\n")
        .expect("partial original");
    assert!(
        custody
            .stage_bound(&reference, b"request bytes\n", b"predecessor")
            .is_err()
    );
    let path = custody
        .root_path
        .join("inputs")
        .join(reference.input_id.as_str());
    assert_eq!(
        std::fs::read(path.join("request.json")).expect("preserved"),
        b"request bytes\n"
    );
    assert!(!path.join("manifest.json").exists());
    entry
        .write_new("predecessor.heptapk", b"predecessor")
        .expect("test file");
    entry
        .write_new(
            "manifest.json",
            &reference.manifest.encode().expect("manifest"),
        )
        .expect("test manifest");
    entry
        .write_new("extra.json", b"unadmitted")
        .expect("extra test file");
    assert!(custody.read(&reference).is_err());
    assert_eq!(
        std::fs::read(path.join("extra.json")).expect("extra preserved"),
        b"unadmitted"
    );
}

#[test]
fn symlink_hardlink_tamper_and_directory_replacement_refuse_custody() {
    let (root, custody, reference) = fixture();
    custody
        .stage_bound(&reference, b"request bytes\n", b"predecessor")
        .expect("stage");
    let path = custody
        .root_path
        .join("inputs")
        .join(reference.input_id.as_str());
    let request = path.join("request.json");
    let backup = root.path().join("original-request");
    std::fs::rename(&request, &backup).expect("test substitution");
    symlink(&backup, &request).expect("test symlink");
    assert!(custody.read(&reference).is_err());
    std::fs::remove_file(&request).expect("test symlink removal");
    std::fs::hard_link(&backup, &request).expect("test hardlink");
    assert!(custody.read(&reference).is_err());
    std::fs::remove_file(&request).expect("test hardlink removal");
    std::fs::rename(&backup, &request).expect("restore original test file");
    std::fs::write(&request, b"changed bytes\n").expect("test tamper");
    assert!(custody.read(&reference).is_err());
    let observed_root = custody.root_path.clone();
    let renamed = root.path().join("provider-moved");
    std::fs::rename(&observed_root, &renamed).expect("test root rename");
    std::fs::create_dir(&observed_root).expect("replacement root");
    std::fs::set_permissions(&observed_root, std::fs::Permissions::from_mode(0o700))
        .expect("replacement private mode");
    assert!(custody.read(&reference).is_err());
    std::fs::remove_dir(&observed_root).expect("remove replacement test root");
    std::fs::rename(&renamed, &observed_root).expect("restore test root for TempDir cleanup");
}
