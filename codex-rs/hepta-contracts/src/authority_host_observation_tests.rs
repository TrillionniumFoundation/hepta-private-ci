//! Actual filesystem persistence through the existing test directory owner.
//! These tests do not claim that a kernel launch or power loss occurred.

use super::*;
use pretty_assertions::assert_eq;

const OBSERVATION: &str = "native-launch:01010101010101010101010101010101:0000000000000001";

fn record_path(directory: &Path, observation: &str) -> std::path::PathBuf {
    let digest = Sha256::digest(observation.as_bytes());
    let suffix: String = digest.iter().map(|byte| format!("{byte:02x}")).collect();
    directory.join(format!("observation-v1-{suffix}.json"))
}

#[test]
fn immutable_observation_reopens_and_retries_without_replacing_the_saved_inode() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let first = root
        .save_observation(OBSERVATION, b"actual complete bound observation")
        .unwrap();
    let path = record_path(directory.path(), OBSERVATION);
    let original = std::fs::metadata(&path).unwrap();
    let again = root.save_observation(OBSERVATION, first.payload()).unwrap();
    let current = std::fs::metadata(&path).unwrap();
    assert_eq!(
        (original.dev(), original.ino()),
        (current.dev(), current.ino())
    );
    assert_eq!(again.observation_id(), OBSERVATION);
    assert_eq!(first.verify_durable(), Ok(()));
    drop(again);
    let reopened = test_directory(directory.path())
        .save_observation(OBSERVATION, first.payload())
        .unwrap();
    assert_eq!(reopened.payload(), first.payload());
    assert_eq!(reopened.verify_durable(), Ok(()));
}

#[test]
fn immutable_observation_never_acknowledges_a_failed_directory_sync() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    *root.before_directory_sync.lock().unwrap() = Some(Arc::new(|| {
        Err(std::io::Error::other("injected directory sync failure"))
    }));
    assert!(matches!(
        root.save_observation(OBSERVATION, b"complete bytes"),
        Err(AuthorityTrustError::Unavailable)
    ));
    let path = record_path(directory.path(), OBSERVATION);
    assert!(
        path.exists(),
        "the actual rename preceded the failed directory sync"
    );
    let inode = std::fs::metadata(&path).unwrap().ino();
    assert!(
        root.save_observation(OBSERVATION, b"complete bytes")
            .is_err(),
        "equal visible bytes do not skip sync"
    );
    *root.before_directory_sync.lock().unwrap() = None;
    let saved = root
        .save_observation(OBSERVATION, b"complete bytes")
        .unwrap();
    assert_eq!(std::fs::metadata(&path).unwrap().ino(), inode);
    *root.before_directory_sync.lock().unwrap() = Some(Arc::new(|| {
        Err(std::io::Error::other("ack boundary failed"))
    }));
    assert_eq!(
        saved.verify_durable(),
        Err(AuthorityTrustError::Unavailable)
    );
    *root.before_directory_sync.lock().unwrap() = None;
    assert_eq!(saved.verify_durable(), Ok(()));
}

#[test]
fn immutable_observation_refuses_changed_bytes_invalid_identity_and_record_overflow() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let saved = root.save_observation(OBSERVATION, b"original").unwrap();
    assert!(matches!(
        root.save_observation(OBSERVATION, b"different"),
        Err(AuthorityTrustError::Conflict)
    ));
    for identity in ["", "../issuer", "a/b", "contains space"] {
        assert!(matches!(
            root.save_observation(identity, b"x"),
            Err(AuthorityTrustError::Invalid)
        ));
    }
    assert!(matches!(
        root.save_observation("empty", b""),
        Err(AuthorityTrustError::Invalid)
    ));
    assert!(matches!(
        root.save_observation("too-large", &vec![255; MAX_RECORD_BYTES as usize]),
        Err(AuthorityTrustError::Invalid)
    ));
    assert_eq!(saved.verify_durable(), Ok(()));
    assert_eq!(saved.payload(), b"original");
}

#[test]
fn immutable_observation_rejects_replaced_inode_symlink_and_shared_inode() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let saved = root.save_observation(OBSERVATION, b"original").unwrap();
    let path = record_path(directory.path(), OBSERVATION);
    let replacement = directory.path().join("replacement");
    std::fs::copy(&path, &replacement).unwrap();
    std::fs::rename(&replacement, &path).unwrap();
    assert_eq!(
        saved.verify_durable(),
        Err(AuthorityTrustError::Unavailable)
    );
    let same_bytes_new_inode = root.save_observation(OBSERVATION, b"original").unwrap();
    assert_eq!(same_bytes_new_inode.verify_durable(), Ok(()));
    let hardlink = directory.path().join("shared");
    std::fs::hard_link(&path, &hardlink).unwrap();
    assert!(same_bytes_new_inode.verify_durable().is_err());
    assert!(root.save_observation(OBSERVATION, b"original").is_err());
    std::fs::remove_file(&path).unwrap();
    std::os::unix::fs::symlink(&hardlink, &path).unwrap();
    assert!(root.save_observation(OBSERVATION, b"original").is_err());
}

#[test]
fn immutable_observation_uses_the_original_exclusive_root_publication_lock() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let saved = root.save_observation(OBSERVATION, b"original").unwrap();
    let path = record_path(directory.path(), OBSERVATION);
    let name = path.file_name().unwrap().to_str().unwrap();
    let lock = root.lock(&format!("{name}.lock")).unwrap();
    assert!(matches!(
        root.save_observation(OBSERVATION, b"original"),
        Err(AuthorityTrustError::Conflict)
    ));
    assert_eq!(saved.verify_durable(), Err(AuthorityTrustError::Conflict));
    drop(lock);
    assert_eq!(saved.verify_durable(), Ok(()));
}

#[test]
fn immutable_observations_preserve_previous_boot_and_existing_authority_frontier() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let authority =
        HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 7_u64).unwrap();
    let first = root
        .save_observation(OBSERVATION, b"first boot bytes")
        .unwrap();
    let second = root
        .save_observation(
            "native-launch:02020202020202020202020202020202:0000000000000001",
            b"second boot bytes",
        )
        .unwrap();
    assert_eq!(authority.load(OWNER), Ok(7));
    assert_eq!(first.verify_durable(), Ok(()));
    assert_eq!(second.verify_durable(), Ok(()));
    assert_eq!(first.payload(), b"first boot bytes");
    assert_eq!(second.payload(), b"second boot bytes");
}
