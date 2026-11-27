use super::*;

use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

use ed25519_dalek::SigningKey;
use tempfile::TempDir;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn private_tempdir() -> TestResult<TempDir> {
    Ok(tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()?)
}

async fn fixture() -> TestResult<(TempDir, TempDir, PathBuf, PathBuf, AuthBusAuthorityOwner)> {
    let database_root = private_tempdir()?;
    let checkpoint_root = private_tempdir()?;
    let database = database_root
        .path()
        .canonicalize()?
        .join("authority.sqlite");
    let checkpoint = checkpoint_root
        .path()
        .canonicalize()?
        .join("authority-checkpoint.json");
    let owner =
        AuthBusAuthorityOwner::bootstrap_new(&database, checkpoint.clone(), "authbus-owner-test")
            .await?;
    Ok((database_root, checkpoint_root, database, checkpoint, owner))
}

#[tokio::test]
async fn writer_lease_fences_a_second_owner_and_releases_on_drop() -> TestResult {
    let (_database_root, _checkpoint_root, database, checkpoint, owner) = fixture().await?;
    let second =
        AuthBusAuthorityOwner::open(&database, checkpoint.clone(), "authbus-owner-test").await;
    assert!(matches!(
        second,
        Err(AuthBusAuthorityError::WriterLeaseHeld)
    ));

    drop(owner);
    let reopened = AuthBusAuthorityOwner::open(&database, checkpoint, "authbus-owner-test").await;
    assert!(
        reopened.is_ok(),
        "normal owner drop must release the writer lease"
    );
    Ok(())
}

#[tokio::test]
async fn stale_writer_lease_fails_closed_until_explicitly_recovered() -> TestResult {
    let (_database_root, _checkpoint_root, database, checkpoint, owner) = fixture().await?;
    drop(owner);

    let lock_path = writer_lock_path(&checkpoint).expect("writer lock path");
    let mut lock = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&lock_path)
        .expect("create stale lock");
    lock.write_all(b"{\"stale\":true}")
        .expect("write stale lock");
    lock.sync_all().expect("sync stale lock");

    assert!(matches!(
        AuthBusAuthorityOwner::open(&database, checkpoint.clone(), "authbus-owner-test",).await,
        Err(AuthBusAuthorityError::WriterLeaseHeld)
    ));

    std::fs::remove_file(lock_path).expect("operator removes verified stale lock");
    AuthBusAuthorityOwner::open(&database, checkpoint, "authbus-owner-test")
        .await
        .expect("open after explicit stale-lock recovery");
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn concurrent_mutations_are_serialized_through_one_checkpoint_publisher() -> TestResult {
    let (_database_root, _checkpoint_root, database, checkpoint, owner) = fixture().await?;
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
                        verifying_key: key.verifying_key().into(),
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
    Ok(())
}

#[tokio::test]
async fn crash_after_external_publication_is_reconciled_without_replaying_mutation() -> TestResult {
    let (_database_root, _checkpoint_root, database, checkpoint, owner) = fixture().await?;
    owner.host.fail_after_external_replace_once();
    let key = SigningKey::from_bytes(&[77; 32]);
    let result = owner
        .admin()
        .enroll_issuer(
            IssuerPurpose::Message,
            IssuerSpec {
                issuer_id: StableId::new("issuer:crash-window").expect("issuer id"),
                key_epoch: Generation::new(1).expect("generation"),
                verifying_key: key.verifying_key().into(),
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
    Ok(())
}

#[tokio::test]
async fn serialized_mutation_cancellation_preserves_single_operation_slot() -> TestResult {
    use std::future::Future;
    use std::future::pending;
    use std::sync::atomic::AtomicBool;
    use std::sync::atomic::Ordering;
    use std::task::Context;
    use std::task::Waker;

    let (_database_root, _checkpoint_root, _database, _checkpoint, owner) = fixture().await?;
    let port = owner.admin();
    let first_entered = AtomicBool::new(false);
    let waiter_entered = AtomicBool::new(false);
    let mut first = Box::pin(async {
        serialized_mutation!(port, async {
            first_entered.store(true, Ordering::SeqCst);
            pending::<Result<(), AuthBusAuthorityError>>().await
        })
    });
    let mut context = Context::from_waker(Waker::noop());
    assert!(first.as_mut().poll(&mut context).is_pending());
    assert!(first_entered.load(Ordering::SeqCst));

    let mut cancelled_waiter = Box::pin(async {
        serialized_mutation!(port, async {
            waiter_entered.store(true, Ordering::SeqCst);
            Ok::<(), AuthBusAuthorityError>(())
        })
    });
    assert!(cancelled_waiter.as_mut().poll(&mut context).is_pending());
    drop(cancelled_waiter);
    assert!(!waiter_entered.load(Ordering::SeqCst));

    let mut next = Box::pin(async {
        serialized_mutation!(port, async {
            waiter_entered.store(true, Ordering::SeqCst);
            Ok::<(), AuthBusAuthorityError>(())
        })
    });
    assert!(next.as_mut().poll(&mut context).is_pending());
    assert!(!waiter_entered.load(Ordering::SeqCst));
    drop(first);
    next.await
        .expect("cancelling the active operation releases its slot");
    assert!(waiter_entered.load(Ordering::SeqCst));
    owner
        .admin()
        .sync_checkpoint()
        .await
        .expect("the original owner remains usable after cancellation");
    Ok(())
}

#[tokio::test]
async fn serialized_mutation_rechecks_lease_and_releases_slot_on_rejection() -> TestResult {
    use std::sync::atomic::AtomicBool;
    use std::sync::atomic::Ordering;

    let (_database_root, _checkpoint_root, _database, checkpoint, owner) = fixture().await?;
    let port = owner.admin();
    let first = async {
        serialized_mutation!(port, async {
            std::fs::remove_file(writer_lock_path(&checkpoint)?)
                .expect("remove the original writer lease during the operation");
            Ok::<(), AuthBusAuthorityError>(())
        })
    }
    .await;
    assert!(matches!(first, Err(AuthBusAuthorityError::WriterLeaseLost)));

    let entered = AtomicBool::new(false);
    let next = async {
        serialized_mutation!(port, async {
            entered.store(true, Ordering::SeqCst);
            Ok::<(), AuthBusAuthorityError>(())
        })
    }
    .await;
    assert!(matches!(next, Err(AuthBusAuthorityError::WriterLeaseLost)));
    assert!(!entered.load(Ordering::SeqCst));
    Ok(())
}
