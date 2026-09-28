use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use super::*;
use crate::AuthBusAuthorityWorker;
use crate::AuthBusAuthorityWorkerConfig;
use crate::AuthBusMutationDisposition;
use crate::IssuerLifecycleState;

struct Fixture {
    _root: tempfile::TempDir,
    database: PathBuf,
    checkpoint: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::tempdir().expect("root");
        let canonical = root.path().canonicalize().expect("canonical root");
        for name in ["db", "witness"] {
            let path = canonical.join(name);
            std::fs::create_dir(&path).expect("directory");
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).expect("mode");
        }
        Self {
            database: canonical.join("db/authority.sqlite"),
            checkpoint: canonical.join("witness/checkpoint.json"),
            _root: root,
        }
    }
    async fn bootstrap(&self) -> AuthBusAuthorityHost {
        AuthBusAuthorityHost::bootstrap(&self.database, self.checkpoint.clone(), "regression")
            .await
            .expect("bootstrap")
    }
    async fn reopen(&self) -> AuthBusAuthorityHost {
        for _ in 0..100 {
            match AuthBusAuthorityHost::open(&self.database, self.checkpoint.clone(), "regression")
                .await
            {
                Ok(host) => return host,
                Err(AuthBusAuthorityError::OwnerAlreadyActive) => {
                    tokio::time::sleep(Duration::from_millis(10)).await
                }
                Err(error) => panic!("reopen failed: {error}"),
            }
        }
        panic!("closed owner did not release within bounded drain");
    }
}

fn epoch(value: u64) -> Generation {
    Generation::new(value).expect("epoch")
}
fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}
fn issuer(name: &str, generation: u64) -> IssuerSpec {
    IssuerSpec {
        issuer_id: id(name),
        key_epoch: epoch(generation),
        verifying_key: SigningKey::from_bytes(&[17; 32]).verifying_key(),
    }
}

async fn close(host: AuthBusAuthorityHost) {
    host.store.pool.close().await;
    drop(host);
}

#[tokio::test]
async fn live_worker_retains_owner_after_original_host_handle_is_dropped() {
    let fixture = Fixture::new();
    let host = Arc::new(fixture.bootstrap().await);
    let weak = Arc::downgrade(&host);
    let worker =
        AuthBusAuthorityWorker::new(Arc::clone(&host), AuthBusAuthorityWorkerConfig::default())
            .expect("worker");
    drop(host);
    assert!(weak.upgrade().is_some());
    assert!(matches!(
        AuthBusAuthorityHost::open(&fixture.database, fixture.checkpoint.clone(), "regression")
            .await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));
    drop(worker);
    let replacement = fixture.reopen().await;
    close(replacement).await;
}

#[tokio::test]
async fn cloned_pool_retains_owner_until_its_final_capability_is_dropped() {
    let fixture = Fixture::new();
    let host = fixture.bootstrap().await;
    let pool = host.store.pool.clone();
    drop(host);
    assert!(matches!(
        AuthBusAuthorityHost::open(&fixture.database, fixture.checkpoint.clone(), "regression")
            .await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));
    pool.close().await;
    drop(pool);
    close(fixture.reopen().await).await;
}

#[tokio::test]
async fn failed_rotation_rolls_back_old_key_and_survives_reopen() {
    let fixture = Fixture::new();
    let host = fixture.bootstrap().await;
    let before = host
        .enroll_issuer(IssuerPurpose::Message, issuer("issuer:atomic", 1))
        .await
        .expect("enroll");
    let witness = host.checkpoint.read().expect("witness");
    sqlx::query("CREATE TRIGGER inject_rotation_failure BEFORE INSERT ON authbus_issuer_registry
        WHEN NEW.key_epoch = x'0000000000000002' BEGIN SELECT RAISE(ABORT, 'injected insert failure'); END")
        .execute(&host.store.pool).await.expect("failpoint");
    assert!(
        host.rotate_issuer(
            IssuerPurpose::Message,
            issuer("issuer:atomic", 2),
            epoch(1),
            1
        )
        .await
        .is_err()
    );
    assert_eq!(
        host.issuer_record(IssuerPurpose::Message, &id("issuer:atomic"), epoch(1))
            .await
            .expect("old key"),
        before
    );
    assert!(matches!(
        host.issuer_record(IssuerPurpose::Message, &id("issuer:atomic"), epoch(2))
            .await,
        Err(AuthBusAuthorityError::IssuerMissing)
    ));
    assert_eq!(host.checkpoint.read().expect("witness"), witness);
    sqlx::query("DROP TRIGGER inject_rotation_failure")
        .execute(&host.store.pool)
        .await
        .expect("remove fault");
    close(host).await;
    let reopened = fixture.reopen().await;
    assert_eq!(
        reopened
            .issuer_record(IssuerPurpose::Message, &id("issuer:atomic"), epoch(1))
            .await
            .expect("reopened"),
        before
    );
    close(reopened).await;
}

#[tokio::test]
async fn failed_revoke_and_retire_preserve_exact_previous_state() {
    let fixture = Fixture::new();
    let host = fixture.bootstrap().await;
    host.enroll_issuer(IssuerPurpose::Message, issuer("issuer:states", 1))
        .await
        .expect("enroll");
    for (target, expected_revision, expected_state) in [
        ("revoked", 1, IssuerLifecycleState::Active),
        ("retired", 2, IssuerLifecycleState::Revoked),
    ] {
        let before = host
            .issuer_record(IssuerPurpose::Message, &id("issuer:states"), epoch(1))
            .await
            .expect("before");
        assert_eq!(before.state, expected_state);
        let sql = if target == "revoked" {
            "CREATE TRIGGER inject_state_failure BEFORE UPDATE ON authbus_issuer_registry
            WHEN NEW.state = 'revoked' BEGIN SELECT RAISE(ABORT, 'injected state failure'); END"
        } else {
            "CREATE TRIGGER inject_state_failure BEFORE UPDATE ON authbus_issuer_registry
            WHEN NEW.state = 'retired' BEGIN SELECT RAISE(ABORT, 'injected state failure'); END"
        };
        sqlx::query(sql)
            .execute(&host.store.pool)
            .await
            .expect("fault");
        let result = if target == "revoked" {
            host.revoke_issuer(
                IssuerPurpose::Message,
                &id("issuer:states"),
                epoch(1),
                expected_revision,
            )
            .await
            .map(|_| ())
        } else {
            host.retire_issuer_epoch(
                IssuerPurpose::Message,
                &id("issuer:states"),
                epoch(1),
                expected_revision,
            )
            .await
            .map(|_| ())
        };
        assert!(result.is_err());
        assert_eq!(
            host.issuer_record(IssuerPurpose::Message, &id("issuer:states"), epoch(1))
                .await
                .expect("after"),
            before
        );
        sqlx::query("DROP TRIGGER inject_state_failure")
            .execute(&host.store.pool)
            .await
            .expect("remove fault");
        if target == "revoked" {
            host.revoke_issuer(IssuerPurpose::Message, &id("issuer:states"), epoch(1), 1)
                .await
                .expect("revoke without fault");
        }
    }
    close(host).await;
    let reopened = fixture.reopen().await;
    assert_eq!(
        reopened
            .issuer_record(IssuerPurpose::Message, &id("issuer:states"), epoch(1))
            .await
            .expect("reopen")
            .state,
        IssuerLifecycleState::Revoked
    );
    close(reopened).await;
}

#[tokio::test]
async fn pending_checkpoint_blocks_new_mutation_and_is_not_a_rollback() {
    let fixture = Fixture::new();
    let host = fixture.bootstrap().await;
    host.set_checkpoint_failpoint(3);
    let error = host
        .enroll_issuer(IssuerPurpose::Message, issuer("issuer:committed", 1))
        .await
        .expect_err("publication fails");
    assert_eq!(
        error.mutation_disposition(),
        AuthBusMutationDisposition::Committed
    );
    let blocked = host
        .enroll_issuer(IssuerPurpose::Message, issuer("issuer:not-started", 1))
        .await
        .expect_err("preflight blocks");
    assert_eq!(
        blocked.mutation_disposition(),
        AuthBusMutationDisposition::NotStarted
    );
    assert!(matches!(
        host.issuer_record(IssuerPurpose::Message, &id("issuer:not-started"), epoch(1))
            .await,
        Err(AuthBusAuthorityError::IssuerMissing)
    ));
    assert_eq!(
        host.issuer_record(IssuerPurpose::Message, &id("issuer:committed"), epoch(1))
            .await
            .expect("readback")
            .revision,
        1
    );
    let diagnostics = host.owner_diagnostics();
    assert!(diagnostics.checkpoint_pending);
    assert_eq!(diagnostics.checkpoint_pending_returns, 1);
    assert_eq!(diagnostics.not_started, 1);
    host.set_checkpoint_failpoint(0);
    close(host).await;
    let reopened = fixture.reopen().await;
    assert!(
        reopened
            .message_issuer(&id("issuer:committed"), epoch(1))
            .await
            .is_ok()
    );
    close(reopened).await;
}

#[tokio::test]
async fn checkpoint_faults_are_isolated_between_owner_instances() {
    let left = Fixture::new();
    let right = Fixture::new();
    let a = left.bootstrap().await;
    let b = right.bootstrap().await;
    a.set_checkpoint_failpoint(1);
    let (failed, successful) = tokio::join!(
        a.enroll_issuer(IssuerPurpose::Message, issuer("issuer:a", 1)),
        b.enroll_issuer(IssuerPurpose::Message, issuer("issuer:b", 1))
    );
    assert!(failed.is_err());
    assert!(successful.is_ok());
    a.set_checkpoint_failpoint(0);
    a.sync_checkpoint().await.expect("repair");
    close(a).await;
    close(b).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn concurrent_mutations_publish_one_consistent_frontier() {
    let fixture = Fixture::new();
    let host = Arc::new(fixture.bootstrap().await);
    let mut tasks = tokio::task::JoinSet::new();
    for number in 0..24 {
        let host = Arc::clone(&host);
        tasks.spawn(async move {
            host.enroll_issuer(
                IssuerPurpose::Message,
                issuer(&format!("issuer:parallel-{number}"), 1),
            )
            .await
        });
    }
    while let Some(result) = tasks.join_next().await {
        result.expect("task").expect("publication");
    }
    let external = host.checkpoint.read().expect("external");
    assert_eq!(
        host.store.authority_checkpoint().await.expect("local"),
        Some(external)
    );
    assert_eq!(
        host.store
            .authority_frontier_digest()
            .await
            .expect("frontier"),
        external.digest
    );
    assert_eq!(host.owner_diagnostics().committed, 24);
    host.store.pool.close().await;
}

#[tokio::test]
async fn cancellation_after_commit_requires_reconciliation_before_next_operation() {
    let fixture = Fixture::new();
    let host = Arc::new(fixture.bootstrap().await);
    let (committed, ready) = tokio::sync::oneshot::channel();
    let task_host = Arc::clone(&host);
    let task = tokio::spawn(async move {
        task_host
            .mutate(async {
                task_host
                    .store
                    .enroll_issuer(IssuerPurpose::Message, issuer("issuer:cancelled", 1))
                    .await?;
                let _ = committed.send(());
                std::future::pending::<Result<(), AuthBusAuthorityError>>().await
            })
            .await
    });
    ready.await.expect("commit observed");
    task.abort();
    assert!(task.await.expect_err("aborted").is_cancelled());
    assert_eq!(host.owner_diagnostics().reconcile_required, 1);
    host.enroll_issuer(IssuerPurpose::Message, issuer("issuer:after-cancel", 1))
        .await
        .expect("repair before next");
    assert!(
        host.message_issuer(&id("issuer:cancelled"), epoch(1))
            .await
            .is_ok()
    );
    assert!(!host.owner_diagnostics().checkpoint_pending);
    host.store.pool.close().await;
}

#[tokio::test]
async fn tampered_checkpoint_rejects_before_starting_the_next_mutation() {
    let fixture = Fixture::new();
    let host = fixture.bootstrap().await;
    let original = std::fs::read(&fixture.checkpoint).expect("original");
    let mut document: serde_json::Value = serde_json::from_slice(&original).expect("json");
    document["digest"] = serde_json::Value::String(Digest32::of_bytes(b"tampered").to_string());
    std::fs::write(
        &fixture.checkpoint,
        serde_json::to_vec(&document).expect("encode"),
    )
    .expect("tamper");
    let result = host
        .enroll_issuer(IssuerPurpose::Message, issuer("issuer:forbidden", 1))
        .await
        .expect_err("must reject");
    assert_eq!(
        result.mutation_disposition(),
        AuthBusMutationDisposition::NotStarted
    );
    assert!(matches!(
        host.issuer_record(IssuerPurpose::Message, &id("issuer:forbidden"), epoch(1))
            .await,
        Err(AuthBusAuthorityError::IssuerMissing)
    ));
    std::fs::write(&fixture.checkpoint, original).expect("restore original");
    host.sync_checkpoint().await.expect("repair");
    close(host).await;
}

#[test]
fn commit_driver_error_is_never_classified_as_definite_rejection() {
    let error = crate::authority_store::commit_error(sqlx::Error::PoolClosed);
    assert_eq!(
        error.mutation_disposition(),
        AuthBusMutationDisposition::ReconcileRequired
    );
}
