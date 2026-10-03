use std::fs;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;

use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::DurableWriterLock;
use super::ProductionWriterError;
use crate::CognitiveStore;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

#[tokio::test]
async fn writer_lock_is_private_and_preserves_single_writer_until_last_drop() {
    let temp = TempDir::new().expect("temp");
    let store = CognitiveStore::open(&layout(&temp, &agent_id(239)))
        .await
        .expect("store");
    let first = DurableWriterLock::acquire(&store, "lease:private").expect("first lock");
    let path = first._path.clone();
    let metadata = fs::symlink_metadata(&path).expect("lock metadata");
    assert!(metadata.is_file());
    assert_eq!(metadata.nlink(), 1);
    assert_eq!(metadata.mode() & 0o7777, 0o600);
    let retained = first.clone();
    drop(first);
    assert!(matches!(
        DurableWriterLock::acquire(&store, "lease:private"),
        Err(ProductionWriterError::WriterBusy)
    ));
    drop(retained);
    let reopened = DurableWriterLock::acquire(&store, "lease:private").expect("reopen lock");
    assert_eq!(
        reopened._file.metadata().expect("reopened inode").ino(),
        metadata.ino()
    );
}

#[tokio::test]
async fn writer_lock_rejects_aliased_nonregular_and_permissive_files_without_modifying_them() {
    for kind in ["symlink", "hardlink", "fifo", "directory", "permissive"] {
        let temp = TempDir::new().expect("temp");
        let store = CognitiveStore::open(&layout(&temp, &agent_id(238)))
            .await
            .expect("store");
        let first = DurableWriterLock::acquire(&store, "lease:unsafe").expect("initial lock");
        let path = first._path.clone();
        drop(first);
        fs::remove_file(&path).expect("remove owned fixture lock");
        let outside = temp.path().join("outside-lock");
        fs::write(&outside, b"retained external content").expect("outside fixture");
        fs::set_permissions(&outside, fs::Permissions::from_mode(0o600)).expect("private");
        match kind {
            "symlink" => symlink(&outside, &path).expect("symlink fixture"),
            "hardlink" => fs::hard_link(&outside, &path).expect("hardlink fixture"),
            "fifo" => assert!(
                std::process::Command::new("mkfifo")
                    .arg("-m")
                    .arg("600")
                    .arg(&path)
                    .status()
                    .expect("FIFO fixture")
                    .success()
            ),
            "directory" => fs::create_dir(&path).expect("directory fixture"),
            "permissive" => {
                fs::write(&path, b"retained lock content").expect("permissive fixture");
                fs::set_permissions(&path, fs::Permissions::from_mode(0o666))
                    .expect("permissive mode");
            }
            _ => unreachable!(),
        }
        let before = fs::symlink_metadata(&path).expect("fixture metadata");
        assert!(
            matches!(
                DurableWriterLock::acquire(&store, "lease:unsafe"),
                Err(ProductionWriterError::Durability(_))
            ),
            "unsafe {kind} writer-lock path must reject"
        );
        let after = fs::symlink_metadata(&path).expect("preserved fixture");
        assert_eq!(
            (after.ino(), after.mode(), after.nlink()),
            (before.ino(), before.mode(), before.nlink())
        );
        assert_eq!(
            fs::read(&outside).expect("outside unchanged"),
            b"retained external content"
        );
        if kind == "permissive" {
            assert_eq!(
                fs::read(&path).expect("lock unchanged"),
                b"retained lock content"
            );
        }
    }
}

#[tokio::test]
async fn writer_lock_reopens_legacy_readable_file_without_changing_its_mode() {
    let temp = TempDir::new().expect("temp");
    let store = CognitiveStore::open(&layout(&temp, &agent_id(237)))
        .await
        .expect("store");
    let first = DurableWriterLock::acquire(&store, "lease:legacy").expect("initial lock");
    let path = first._path.clone();
    drop(first);
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).expect("legacy mode");
    let before = fs::symlink_metadata(&path).expect("legacy metadata");
    let reopened = DurableWriterLock::acquire(&store, "lease:legacy").expect("legacy reopen");
    let after = reopened._file.metadata().expect("retained metadata");
    assert_eq!((after.ino(), after.mode()), (before.ino(), before.mode()));
}

#[tokio::test]
async fn public_writer_open_rejects_redirected_lock_before_appending_a_lease() {
    struct FixtureVerifier;
    impl super::ProductionAuthorityVerifier for FixtureVerifier {
        fn verify(
            &self,
            authority: &super::ProductionAuthorityLease,
            expected_agent: &codex_hepta_contracts::AgentId,
        ) -> Result<(), String> {
            if authority.agent_id == *expected_agent {
                Ok(())
            } else {
                Err("fixture owner mismatch".to_string())
            }
        }
    }

    let temp = TempDir::new().expect("temp");
    let owner = agent_id(236);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let lease_id = "lease:public-redirected";
    let initial = DurableWriterLock::acquire(&store, lease_id).expect("initial lock");
    let path = initial._path.clone();
    drop(initial);
    fs::remove_file(&path).expect("remove owned fixture lock");
    let outside = temp.path().join("outside-lock");
    fs::write(&outside, b"unchanged").expect("external fixture");
    fs::set_permissions(&outside, fs::Permissions::from_mode(0o600)).expect("private");
    symlink(&outside, &path).expect("redirected lock");
    let before = store.recovery_anchor().await.expect("initial exact cut");
    let authority = super::ProductionAuthorityLease::from_verified_parts(
        owner,
        codex_hepta_contracts::Sha256Digest::for_bytes(b"test-grant"),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        super::now_unix_seconds().expect("clock") + 3_600,
        super::ProductionAuthorityToken::from_verified_bytes(b"test-token".to_vec())
            .expect("fixture token"),
    )
    .expect("fixture authority");
    assert!(matches!(
        super::ProductionDurableWriter::open(
            store.clone(),
            authority,
            &FixtureVerifier,
            lease_id,
            /*generation*/ 1,
        )
        .await,
        Err(ProductionWriterError::Durability(_))
    ));
    assert_eq!(
        store.recovery_anchor().await.expect("unchanged cut"),
        before
    );
    assert_eq!(
        fs::read(&outside).expect("unchanged external file"),
        b"unchanged"
    );
}
