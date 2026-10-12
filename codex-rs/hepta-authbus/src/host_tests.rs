use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use super::AuthBusAuthorityHost;
use super::set_checkpoint_failpoint;
use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityWorker;
use crate::AuthBusAuthorityWorkerConfig;
use crate::AuthBusMutationDisposition;
use crate::IssuerLifecycleState;
use crate::IssuerPurpose;
use crate::IssuerSpec;
use crate::TrustedTimeSample;

struct Paths {
    _root: TempDir,
    database: PathBuf,
    checkpoint: PathBuf,
}

fn private_paths() -> Paths {
    use std::os::unix::fs::PermissionsExt;

    let root = TempDir::new().expect("temporary root");
    let database_root = root.path().join("database");
    let checkpoint_root = root.path().join("checkpoint");
    std::fs::create_dir_all(&database_root).expect("database root");
    std::fs::create_dir_all(&checkpoint_root).expect("checkpoint root");
    std::fs::set_permissions(&database_root, std::fs::Permissions::from_mode(0o700))
        .expect("database permissions");
    std::fs::set_permissions(&checkpoint_root, std::fs::Permissions::from_mode(0o700))
        .expect("checkpoint permissions");
    Paths {
        database: database_root.join("authority.sqlite"),
        checkpoint: checkpoint_root.join("authority-checkpoint.json"),
        _root: root,
    }
}

fn issuer_spec(issuer_id: &str, epoch: u64, byte: u8) -> IssuerSpec {
    IssuerSpec {
        issuer_id: StableId::new(issuer_id).expect("issuer id"),
        key_epoch: Generation::new(epoch).expect("epoch"),
        verifying_key: SigningKey::from_bytes(&[byte; 32]).verifying_key(),
    }
}

fn assert_committed_needs_reconciliation<T>(result: Result<T, AuthBusAuthorityError>) {
    match result {
        Err(error @ AuthBusAuthorityError::CheckpointReconciliationRequired(_)) => {
            assert_eq!(
                error.mutation_disposition(),
                AuthBusMutationDisposition::CommittedNeedsReconciliation
            );
        }
        Err(error) => panic!("expected committed reconciliation result, got {error}"),
        Ok(_) => panic!("mutation unexpectedly reported full durability"),
    }
}

fn run_owner_probe(paths: &Paths, owner_id: &str, marker_name: &str) -> String {
    let marker = paths._root.path().join(marker_name);
    let _ = std::fs::remove_file(&marker);
    let status = Command::new(std::env::current_exe().expect("current test executable"))
        .arg("host::tests::owner_probe_reports_fence_state")
        .arg("--exact")
        .arg("--nocapture")
        .env("AUTHBUS_OWNER_PROBE", "1")
        .env("AUTHBUS_OWNER_ID", owner_id)
        .env("AUTHBUS_OWNER_DATABASE", &paths.database)
        .env("AUTHBUS_OWNER_CHECKPOINT", &paths.checkpoint)
        .env("AUTHBUS_OWNER_MARKER", &marker)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .expect("run owner probe");
    assert!(status.success(), "owner probe child failed");
    std::fs::read_to_string(marker).expect("owner probe result")
}

#[tokio::test]
async fn bootstrap_requires_both_state_domains_to_be_new() {
    let paths = private_paths();
    std::fs::write(&paths.database, b"preexisting").expect("preexisting database");
    assert!(matches!(
        AuthBusAuthorityHost::bootstrap(
            &paths.database,
            paths.checkpoint.clone(),
            "bootstrap-owner",
        )
        .await,
        Err(AuthBusAuthorityError::RollbackDetected)
    ));
    std::fs::remove_file(&paths.database).expect("remove database");
    std::fs::write(&paths.checkpoint, b"preexisting").expect("preexisting checkpoint");
    assert!(matches!(
        AuthBusAuthorityHost::bootstrap(
            &paths.database,
            paths.checkpoint.clone(),
            "bootstrap-owner",
        )
        .await,
        Err(AuthBusAuthorityError::RollbackDetected)
    ));
}

#[tokio::test]
async fn second_owner_is_rejected_and_release_allows_reopen() {
    let paths = private_paths();
    let owner =
        AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), "single-owner")
            .await
            .expect("bootstrap owner");
    assert!(matches!(
        AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), "single-owner",)
            .await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));
    drop(owner);
    AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), "single-owner")
        .await
        .expect("reopen after owner release");
}

#[tokio::test]
async fn failed_same_process_duplicate_does_not_release_cross_process_fence() {
    let paths = private_paths();
    let owner_id = "duplicate-fence-owner";
    let owner =
        AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), owner_id)
            .await
            .expect("bootstrap owner");

    assert!(matches!(
        AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), owner_id).await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));
    assert_eq!(
        run_owner_probe(&paths, owner_id, "probe-blocked"),
        "blocked"
    );

    drop(owner);
    assert_eq!(
        run_owner_probe(&paths, owner_id, "probe-acquired"),
        "acquired"
    );
}

#[tokio::test]
async fn worker_retains_host_and_owner_fence_until_worker_drop() {
    let paths = private_paths();
    let owner_id = "worker-owner";
    let host = Arc::new(
        AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), owner_id)
            .await
            .expect("bootstrap owner"),
    );
    let worker =
        AuthBusAuthorityWorker::new(Arc::clone(&host), AuthBusAuthorityWorkerConfig::default())
            .expect("worker");
    drop(host);

    assert!(matches!(
        AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), owner_id).await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));
    drop(worker);
    AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), owner_id)
        .await
        .expect("worker drop releases final host and fence");
}

#[tokio::test]
async fn checkpoint_stage_failures_are_classified_and_recoverable() {
    for stage in 1_u8..=4 {
        let paths = private_paths();
        let host = AuthBusAuthorityHost::bootstrap(
            &paths.database,
            paths.checkpoint.clone(),
            "fault-owner",
        )
        .await
        .expect("bootstrap owner");
        let issuer_id = StableId::new(format!("issuer:fault-{stage}")).expect("issuer id");
        let failpoint = set_checkpoint_failpoint(&paths.checkpoint, stage);
        let result = host
            .enroll_issuer(
                IssuerPurpose::Message,
                IssuerSpec {
                    issuer_id: issuer_id.clone(),
                    key_epoch: Generation::new(1).expect("epoch"),
                    verifying_key: SigningKey::from_bytes(&[stage; 32]).verifying_key(),
                },
            )
            .await;
        drop(failpoint);
        assert_committed_needs_reconciliation(result);

        host.sync_checkpoint().await.expect("recover checkpoint");
        host.message_issuer(&issuer_id, Generation::new(1).expect("epoch"))
            .await
            .expect("committed issuer remains available");

        let snapshot = host
            .operational_snapshot(
                &TrustedTimeSample::new(
                    10_000 + u64::from(stage),
                    u64::from(stage),
                    Digest32::of_bytes(&[stage]),
                )
                .expect("time"),
            )
            .await
            .expect("operational snapshot");
        assert!(snapshot.runtime.checkpoint_sync_failures >= 1);
        assert_eq!(
            snapshot.runtime.mutation_committed_reconciliation_required,
            1
        );
    }
}

#[tokio::test]
async fn every_issuer_lifecycle_mutation_has_the_same_checkpoint_failure_contract() {
    let paths = private_paths();
    let host = AuthBusAuthorityHost::bootstrap(
        &paths.database,
        paths.checkpoint.clone(),
        "issuer-lifecycle-owner",
    )
    .await
    .expect("bootstrap owner");
    let issuer_id = StableId::new("issuer:lifecycle").expect("issuer id");
    let epoch_one = Generation::new(1).expect("epoch one");
    let epoch_two = Generation::new(2).expect("epoch two");

    let failpoint = set_checkpoint_failpoint(&paths.checkpoint, 1);
    let enroll = host
        .enroll_issuer(
            IssuerPurpose::Message,
            issuer_spec("issuer:lifecycle", 1, 31),
        )
        .await;
    drop(failpoint);
    assert_committed_needs_reconciliation(enroll);
    host.sync_checkpoint().await.expect("checkpoint enroll");
    let first = host
        .message_issuer(&issuer_id, epoch_one)
        .await
        .expect("first issuer");
    assert!(!first.revoked);
    assert_eq!(first.registry_revision(), 1);

    let failpoint = set_checkpoint_failpoint(&paths.checkpoint, 1);
    let rotate = host
        .rotate_issuer(
            IssuerPurpose::Message,
            issuer_spec("issuer:lifecycle", 2, 32),
            epoch_one,
            1,
        )
        .await;
    drop(failpoint);
    assert_committed_needs_reconciliation(rotate);
    host.sync_checkpoint().await.expect("checkpoint rotation");
    let old = host
        .message_issuer(&issuer_id, epoch_one)
        .await
        .expect("old issuer");
    let current = host
        .message_issuer(&issuer_id, epoch_two)
        .await
        .expect("current issuer");
    assert!(old.revoked);
    assert_eq!(old.registry_revision(), 2);
    assert!(!current.revoked);
    assert_eq!(current.registry_revision(), 1);

    let failpoint = set_checkpoint_failpoint(&paths.checkpoint, 1);
    let revoke = host
        .revoke_issuer(IssuerPurpose::Message, &issuer_id, epoch_two, 1)
        .await;
    drop(failpoint);
    assert_committed_needs_reconciliation(revoke);
    host.sync_checkpoint().await.expect("checkpoint revocation");
    let current = host
        .message_issuer(&issuer_id, epoch_two)
        .await
        .expect("revoked current issuer");
    assert!(current.revoked);
    assert_eq!(current.registry_revision(), 2);

    let failpoint = set_checkpoint_failpoint(&paths.checkpoint, 1);
    let retire = host
        .retire_issuer_epoch(IssuerPurpose::Message, &issuer_id, epoch_one, 2)
        .await;
    drop(failpoint);
    assert_committed_needs_reconciliation(retire);
    host.sync_checkpoint().await.expect("checkpoint retirement");
    let retired = host
        .store
        .issuer_record(IssuerPurpose::Message, &issuer_id, epoch_one)
        .await
        .expect("retired record");
    assert_eq!(retired.state, IssuerLifecycleState::Retired);
    assert_eq!(retired.revision, 3);

    let deterministic_rejection = host
        .rotate_issuer(
            IssuerPurpose::Message,
            issuer_spec("issuer:lifecycle", 3, 33),
            epoch_two,
            999,
        )
        .await
        .expect_err("wrong revision must be rejected");
    assert_eq!(
        deterministic_rejection.mutation_disposition(),
        AuthBusMutationDisposition::NotCommitted
    );
}

#[tokio::test]
async fn kill_nine_releases_the_process_owner_fence() {
    let paths = private_paths();
    let initial =
        AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), "kill-owner")
            .await
            .expect("bootstrap owner");
    drop(initial);

    let marker = paths._root.path().join("owner-ready");
    let mut child = Command::new(std::env::current_exe().expect("current test executable"))
        .arg("host::tests::owner_child_process_holds_fence")
        .arg("--exact")
        .arg("--nocapture")
        .env("AUTHBUS_OWNER_CHILD", "1")
        .env("AUTHBUS_OWNER_DATABASE", &paths.database)
        .env("AUTHBUS_OWNER_CHECKPOINT", &paths.checkpoint)
        .env("AUTHBUS_OWNER_MARKER", &marker)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .expect("spawn owner child");

    for _ in 0..100 {
        if marker.exists() {
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    assert!(marker.exists(), "child did not acquire owner fence");
    assert!(matches!(
        AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), "kill-owner",).await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));

    let status = Command::new("kill")
        .arg("-9")
        .arg(child.id().to_string())
        .status()
        .expect("kill child");
    assert!(status.success());
    let _ = child.wait().expect("wait for killed child");
    AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), "kill-owner")
        .await
        .expect("owner fence released by process death");
}

#[tokio::test]
async fn owner_probe_reports_fence_state() {
    if std::env::var_os("AUTHBUS_OWNER_PROBE").is_none() {
        return;
    }
    let owner_id = std::env::var("AUTHBUS_OWNER_ID").expect("child owner id");
    let database =
        PathBuf::from(std::env::var_os("AUTHBUS_OWNER_DATABASE").expect("child database path"));
    let checkpoint =
        PathBuf::from(std::env::var_os("AUTHBUS_OWNER_CHECKPOINT").expect("child checkpoint path"));
    let marker =
        PathBuf::from(std::env::var_os("AUTHBUS_OWNER_MARKER").expect("child marker path"));
    let result = AuthBusAuthorityHost::open(&database, checkpoint, &owner_id).await;
    let state = match result {
        Ok(_host) => "acquired",
        Err(AuthBusAuthorityError::OwnerAlreadyActive) => "blocked",
        Err(error) => panic!("unexpected owner probe result: {error}"),
    };
    std::fs::write(marker, state).expect("write owner probe result");
}

#[tokio::test]
async fn owner_child_process_holds_fence() {
    if std::env::var_os("AUTHBUS_OWNER_CHILD").is_none() {
        return;
    }
    let database =
        PathBuf::from(std::env::var_os("AUTHBUS_OWNER_DATABASE").expect("child database path"));
    let checkpoint =
        PathBuf::from(std::env::var_os("AUTHBUS_OWNER_CHECKPOINT").expect("child checkpoint path"));
    let marker =
        PathBuf::from(std::env::var_os("AUTHBUS_OWNER_MARKER").expect("child marker path"));
    let _host = AuthBusAuthorityHost::open(&database, checkpoint, "kill-owner")
        .await
        .expect("child owner open");
    std::fs::write(marker, b"ready").expect("write child marker");
    tokio::time::sleep(Duration::from_secs(60)).await;
}

#[test]
fn failed_create_does_not_unlink_an_existing_checkpoint() {
    let paths = private_paths();
    let checkpoint = super::AuthorityCheckpoint {
        generation: 1,
        digest: Digest32::of_bytes(b"existing-checkpoint"),
    };
    super::create_private_checkpoint(&paths.checkpoint, "create-owner", checkpoint)
        .expect("create initial checkpoint");
    let before = std::fs::read(&paths.checkpoint).expect("checkpoint bytes");
    let unrelated = paths.checkpoint.with_file_name("unrelated-checkpoint");
    std::fs::write(&unrelated, b"unrelated").expect("unrelated file");

    assert!(
        super::create_private_checkpoint(&paths.checkpoint, "other-owner", checkpoint).is_err()
    );
    pretty_assertions::assert_eq!(
        std::fs::read(&paths.checkpoint).expect("checkpoint retained"),
        before
    );
    pretty_assertions::assert_eq!(
        std::fs::read(&unrelated).expect("unrelated file retained"),
        b"unrelated"
    );
}

#[test]
fn failed_temporary_create_preserves_a_preexisting_file() {
    let paths = private_paths();
    let mut next = super::AuthorityCheckpoint {
        generation: 1,
        digest: Digest32::of_bytes(b"existing-checkpoint"),
    };
    super::create_private_checkpoint(&paths.checkpoint, "temp-owner", next)
        .expect("create initial checkpoint");
    let before = std::fs::read(&paths.checkpoint).expect("checkpoint bytes");
    next.generation += 1;
    let name = paths
        .checkpoint
        .file_name()
        .expect("file name")
        .to_str()
        .expect("UTF-8 name");
    let temporary = paths.checkpoint.parent().expect("parent").join(format!(
        ".{name}.{}.{}.tmp",
        std::process::id(),
        next.generation,
    ));
    std::fs::write(&temporary, b"preexisting").expect("existing temporary file");

    assert!(super::write_private_atomic(&paths.checkpoint, "temp-owner", next).is_err());
    pretty_assertions::assert_eq!(
        std::fs::read(&temporary).expect("preexisting file retained"),
        b"preexisting"
    );
    pretty_assertions::assert_eq!(
        std::fs::read(&paths.checkpoint).expect("checkpoint retained"),
        before
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn concurrent_mutations_checkpoint_and_reopen_without_lost_publication() {
    let paths = private_paths();
    let host = Arc::new(
        AuthBusAuthorityHost::bootstrap(
            &paths.database,
            paths.checkpoint.clone(),
            "concurrent-owner",
        )
        .await
        .expect("bootstrap"),
    );
    let barrier = Arc::new(tokio::sync::Barrier::new(24));
    let mut tasks = tokio::task::JoinSet::new();
    for index in 1_u8..=24 {
        let host = Arc::clone(&host);
        let barrier = Arc::clone(&barrier);
        tasks.spawn(async move {
            barrier.wait().await;
            host.enroll_issuer(
                IssuerPurpose::Message,
                issuer_spec(&format!("issuer:concurrent-{index}"), 1, index),
            )
            .await
            .expect("serialized issuer mutation");
            host.sync_checkpoint()
                .await
                .expect("concurrent explicit publication");
        });
    }
    while let Some(result) = tasks.join_next().await {
        result.expect("concurrent task");
    }
    drop(host);
    let reopened = AuthBusAuthorityHost::open(
        &paths.database,
        paths.checkpoint.clone(),
        "concurrent-owner",
    )
    .await
    .expect("reopen exact published state");
    for index in 1_u8..=24 {
        reopened
            .message_issuer(
                &StableId::new(format!("issuer:concurrent-{index}")).expect("issuer id"),
                Generation::new(1).expect("epoch"),
            )
            .await
            .expect("every acknowledged mutation survived");
    }
}

#[tokio::test]
#[expect(
    clippy::await_holding_invalid_type,
    reason = "the test deliberately retains the mutation gate while polling and dropping one waiting mutation"
)]
async fn cancelled_waiting_mutation_has_no_effect() {
    let paths = private_paths();
    let host =
        AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), "cancel-owner")
            .await
            .expect("bootstrap");
    let guard = host.mutation_gate.lock().await;
    {
        let mut mutation = Box::pin(host.enroll_issuer(
            IssuerPurpose::Message,
            issuer_spec("issuer:cancelled-waiter", 1, 40),
        ));
        std::future::poll_fn(|context| {
            assert!(
                std::future::Future::poll(mutation.as_mut(), context).is_pending(),
                "mutation must wait for the publication gate"
            );
            std::task::Poll::Ready(())
        })
        .await;
    }
    drop(guard);
    assert!(
        host.message_issuer(
            &StableId::new("issuer:cancelled-waiter").expect("id"),
            Generation::new(1).expect("epoch")
        )
        .await
        .is_err()
    );
    host.sync_checkpoint()
        .await
        .expect("no abandoned checkpoint transition");
}

#[tokio::test]
async fn checkpoint_faults_do_not_cross_host_boundaries() {
    let first_paths = private_paths();
    let second_paths = private_paths();
    let first = AuthBusAuthorityHost::bootstrap(
        &first_paths.database,
        first_paths.checkpoint.clone(),
        "first",
    )
    .await
    .expect("first host");
    let second = AuthBusAuthorityHost::bootstrap(
        &second_paths.database,
        second_paths.checkpoint.clone(),
        "second",
    )
    .await
    .expect("second host");
    let fault = set_checkpoint_failpoint(&first_paths.checkpoint, 1);
    second
        .enroll_issuer(
            IssuerPurpose::Message,
            issuer_spec("issuer:isolated-fault", 1, 42),
        )
        .await
        .expect("unrelated checkpoint must not inherit fault");
    assert!(
        first
            .enroll_issuer(
                IssuerPurpose::Message,
                issuer_spec("issuer:isolated-fault", 1, 42)
            )
            .await
            .is_err()
    );
    drop(fault);
    first
        .sync_checkpoint()
        .await
        .expect("recover affected host");
}

#[tokio::test]
async fn distinct_databases_cannot_share_an_active_checkpoint_owner() {
    let first_paths = private_paths();
    let second_paths = private_paths();
    let first = AuthBusAuthorityHost::bootstrap(
        &first_paths.database,
        first_paths.checkpoint.clone(),
        "shared-owner",
    )
    .await
    .expect("first owner");
    let second = AuthBusAuthorityHost::bootstrap(
        &second_paths.database,
        second_paths.checkpoint.clone(),
        "shared-owner",
    )
    .await
    .expect("second independent owner");
    drop(second);
    let before = std::fs::read(&first_paths.checkpoint).expect("first checkpoint");
    assert!(matches!(
        AuthBusAuthorityHost::open(
            &second_paths.database,
            first_paths.checkpoint.clone(),
            "shared-owner"
        )
        .await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));
    pretty_assertions::assert_eq!(
        std::fs::read(&first_paths.checkpoint).expect("unchanged witness"),
        before
    );
    AuthBusAuthorityHost::open(
        &second_paths.database,
        second_paths.checkpoint.clone(),
        "shared-owner",
    )
    .await
    .expect("failed witness acquisition releases the database fence");
    first
        .enroll_issuer(
            IssuerPurpose::Message,
            issuer_spec("issuer:witness-owner", 1, 54),
        )
        .await
        .expect("the original owner remains usable");
}

// Observe the persisted checkpoint/dirty pair with a read-only SELECT that
// bypasses the authority-read and reconciliation paths being tested.
async fn persisted_checkpoint_state(pool: &sqlx::SqlitePool) -> (Vec<u8>, Vec<u8>, i64) {
    sqlx::query_as(
        "SELECT checkpoint.generation, checkpoint.checkpoint_digest, dirty.dirty
         FROM authbus_authority_checkpoint AS checkpoint
         JOIN authbus_authority_checkpoint_dirty AS dirty
           ON checkpoint.singleton = dirty.singleton
         WHERE checkpoint.singleton = 1",
    )
    .fetch_one(pool)
    .await
    .expect("persisted checkpoint and dirty state")
}

#[tokio::test]
async fn directory_sync_failure_blocks_live_successor_promotion_until_recovery() {
    let paths = private_paths();
    let host = AuthBusAuthorityHost::bootstrap(
        &paths.database,
        paths.checkpoint.clone(),
        "directory-sync-live-owner",
    )
    .await
    .expect("bootstrap");
    let before = host.checkpoint.read().expect("initial durable checkpoint");
    let pending_state = (
        before.generation.to_be_bytes().to_vec(),
        before.digest.as_array().to_vec(),
        1_i64,
    );
    let issuer_id = StableId::new("issuer:directory-sync-live").expect("issuer id");
    let epoch = Generation::new(1).expect("epoch");
    let fault = set_checkpoint_failpoint(&paths.checkpoint, 4);
    assert_committed_needs_reconciliation(
        host.enroll_issuer(
            IssuerPurpose::Message,
            issuer_spec(issuer_id.as_str(), 1, 61),
        )
        .await,
    );
    let visible = host.checkpoint.read().expect("visible renamed successor");
    assert_eq!(visible.generation, before.generation + 1);
    assert_ne!(visible.digest, before.digest);
    pretty_assertions::assert_eq!(
        persisted_checkpoint_state(&host.store.pool).await,
        pending_state
    );

    for _ in 0..2 {
        assert!(matches!(
            host.sync_checkpoint().await,
            Err(AuthBusAuthorityError::Storage(detail))
                if detail == "injected checkpoint I/O failure at stage 4"
        ));
        assert!(matches!(
            host.message_issuer(&issuer_id, epoch).await,
            Err(AuthBusAuthorityError::AuthorityUseBlocked(_))
        ));
        assert!(matches!(
            host.enroll_issuer(
                IssuerPurpose::Message,
                issuer_spec("issuer:directory-sync-never-admitted", 1, 62),
            )
            .await,
            Err(AuthBusAuthorityError::AuthorityUseBlocked(_))
        ));
        pretty_assertions::assert_eq!(
            persisted_checkpoint_state(&host.store.pool).await,
            pending_state
        );
        assert_eq!(host.checkpoint.read().expect("same successor"), visible);
    }

    drop(fault);
    host.sync_checkpoint()
        .await
        .expect("directory sync retry permits promotion");
    pretty_assertions::assert_eq!(
        persisted_checkpoint_state(&host.store.pool).await,
        (
            visible.generation.to_be_bytes().to_vec(),
            visible.digest.as_array().to_vec(),
            0_i64,
        )
    );
    host.message_issuer(&issuer_id, epoch)
        .await
        .expect("committed issuer is usable after durable promotion");
    assert!(matches!(
        host.message_issuer(
            &StableId::new("issuer:directory-sync-never-admitted").expect("issuer id"),
            epoch,
        )
        .await,
        Err(AuthBusAuthorityError::IssuerMissing)
    ));
}

#[tokio::test]
async fn directory_sync_failure_blocks_startup_successor_promotion_until_recovery() {
    let paths = private_paths();
    let owner_id = "directory-sync-startup-owner";
    let host = AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), owner_id)
        .await
        .expect("bootstrap");
    let before = host.checkpoint.read().expect("initial durable checkpoint");
    let pending_state = (
        before.generation.to_be_bytes().to_vec(),
        before.digest.as_array().to_vec(),
        1_i64,
    );
    let issuer_id = StableId::new("issuer:directory-sync-startup").expect("issuer id");
    let fault = set_checkpoint_failpoint(&paths.checkpoint, 4);
    assert_committed_needs_reconciliation(
        host.enroll_issuer(
            IssuerPurpose::Message,
            issuer_spec(issuer_id.as_str(), 1, 63),
        )
        .await,
    );
    let visible = host.checkpoint.read().expect("visible renamed successor");
    assert_eq!(visible.generation, before.generation + 1);
    assert_ne!(visible.digest, before.digest);
    pretty_assertions::assert_eq!(
        persisted_checkpoint_state(&host.store.pool).await,
        pending_state
    );
    // Keep only the query pool as a state observer, never a host/owner reference.
    // This tests startup promotion, not SQLx shutdown or final-reference drainage.
    let inspection_pool = host.store.pool.clone();
    drop(host);

    for _ in 0..2 {
        assert!(matches!(
            AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), owner_id)
                .await,
            Err(AuthBusAuthorityError::Storage(detail))
                if detail == "injected checkpoint I/O failure at stage 4"
        ));
        pretty_assertions::assert_eq!(
            persisted_checkpoint_state(&inspection_pool).await,
            pending_state
        );
    }

    inspection_pool.close().await;
    drop(inspection_pool);
    drop(fault);
    let reopened = AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), owner_id)
        .await
        .expect("startup succeeds after directory sync recovers");
    pretty_assertions::assert_eq!(
        persisted_checkpoint_state(&reopened.store.pool).await,
        (
            visible.generation.to_be_bytes().to_vec(),
            visible.digest.as_array().to_vec(),
            0_i64,
        )
    );
    assert_eq!(reopened.checkpoint.read().expect("same successor"), visible);
    reopened
        .message_issuer(&issuer_id, Generation::new(1).expect("epoch"))
        .await
        .expect("committed issuer survives startup recovery");
}
