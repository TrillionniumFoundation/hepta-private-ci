use super::*;

use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

use ed25519_dalek::SigningKey;
use tempfile::TempDir;

fn private_tempdir() -> TempDir {
    let directory = tempfile::tempdir().expect("tempdir");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private tempdir");
    directory
}

async fn fixture() -> (TempDir, TempDir, PathBuf, PathBuf, AuthBusAuthorityOwner) {
    let database_root = private_tempdir();
    let checkpoint_root = private_tempdir();
    let database = database_root.path().join("authority.sqlite");
    let checkpoint = checkpoint_root.path().join("authority-checkpoint.json");
    let owner = AuthBusAuthorityOwner::bootstrap_new(
        &database,
        checkpoint.clone(),
        "authbus-owner-test",
    )
    .await
    .expect("bootstrap owner");
    (
        database_root,
        checkpoint_root,
        database,
        checkpoint,
        owner,
    )
}

#[tokio::test]
async fn writer_lease_fences_a_second_owner_and_releases_on_drop() {
    let (_database_root, _checkpoint_root, database, checkpoint, owner) = fixture().await;
    let second = AuthBusAuthorityOwner::open(
        &database,
        checkpoint.clone(),
        "authbus-owner-test",
    )
    .await;
    assert!(matches!(
        second,
        Err(AuthBusAuthorityError::WriterLeaseHeld)
    ));

    drop(owner);
    let reopened = AuthBusAuthorityOwner::open(
        &database,
        checkpoint,
        "authbus-owner-test",
    )
    .await;
    assert!(reopened.is_ok(), "normal owner drop must release the writer lease");
}

#[tokio::test]
async fn stale_writer_lease_fails_closed_until_explicitly_recovered() {
    let (_database_root, _checkpoint_root, database, checkpoint, owner) = fixture().await;
    drop(owner);

    let lock_path = writer_lock_path(&checkpoint).expect("writer lock path");
    let mut lock = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&lock_path)
        .expect("create stale lock");
    lock.write_all(b"{\"stale\":true}").expect("write stale lock");
    lock.sync_all().expect("sync stale lock");

    assert!(matches!(
        AuthBusAuthorityOwner::open(
            &database,
            checkpoint.clone(),
            "authbus-owner-test",
        )
        .await,
        Err(AuthBusAuthorityError::WriterLeaseHeld)
    ));

    std::fs::remove_file(lock_path).expect("operator removes verified stale lock");
    AuthBusAuthorityOwner::open(&database, checkpoint, "authbus-owner-test")
        .await
        .expect("open after explicit stale-lock recovery");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn concurrent_mutations_are_serialized_through_one_checkpoint_publisher() {
    let (_database_root, _checkpoint_root, database, checkpoint, owner) = fixture().await;
    let owner = Arc::new(owner);
    let mut tasks = Vec::new();
    for index in 0_u8..32 {
        let owner = Arc::clone(&owner);
        tasks.push(tokio::spawn(async move {
            let key = SigningKey::from_bytes(&[index.saturating_add(1); 32]);
            owner
                .admin()
                .enroll_issuer(
                    IssuerPurpose::Message,
                    IssuerSpec {
                        issuer_id: StableId::new(format!("issuer:concurrent:{index}"))
                            .expect("issuer id"),
                        key_epoch: Generation::new(1).expect("generation"),
                        verifying_key: key.verifying_key(),
                    },
                )
                .await
        }));
    }
    for task in tasks {
        task.await
            .expect("task join")
            .expect("serialized issuer enrollment");
    }
    owner
        .admin()
        .sync_checkpoint()
        .await
        .expect("checkpoint synchronized");

    drop(owner);
    AuthBusAuthorityOwner::open(&database, checkpoint, "authbus-owner-test")
        .await
        .expect("concurrent owner state reopens without false rollback");
}

#[tokio::test]
async fn crash_after_external_publication_is_reconciled_without_replaying_mutation() {
    let (_database_root, _checkpoint_root, database, checkpoint, owner) = fixture().await;
    owner.host.fail_after_external_replace_once();
    let key = SigningKey::from_bytes(&[77; 32]);
    let result = owner
        .admin()
        .enroll_issuer(
            IssuerPurpose::Message,
            IssuerSpec {
                issuer_id: StableId::new("issuer:crash-window").expect("issuer id"),
                key_epoch: Generation::new(1).expect("generation"),
                verifying_key: key.verifying_key(),
            },
        )
        .await;
    assert!(
        matches!(result, Err(AuthBusAuthorityError::Storage(ref message))
            if message.contains("injected crash")),
        "the mutation commits but the injected publication window must surface"
    );

    owner
        .admin()
        .sync_checkpoint()
        .await
        .expect("reconcile external successor into the local checkpoint");
    drop(owner);
    AuthBusAuthorityOwner::open(&database, checkpoint, "authbus-owner-test")
        .await
        .expect("reconciled crash window reopens");
}
