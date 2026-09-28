use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use super::AuthBusAuthorityHost;
use super::set_checkpoint_failpoint;
use crate::AuthBusAuthorityError;
use crate::IssuerPurpose;
use crate::IssuerSpec;

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

fn issuer_spec(id: &str, seed: u8) -> IssuerSpec {
    IssuerSpec {
        issuer_id: StableId::new(id).expect("issuer id"),
        key_epoch: Generation::new(1).expect("epoch"),
        verifying_key: SigningKey::from_bytes(&[seed; 32]).verifying_key(),
    }
}

#[tokio::test]
async fn bootstrap_requires_both_state_domains_to_be_new() {
    let paths = private_paths();
    std::fs::write(&paths.database, b"preexisting").expect("preexisting database");
    assert!(matches!(
        AuthBusAuthorityHost::bootstrap(
            &paths.database,
            paths.checkpoint.clone(),
            "bootstrap-owner"
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
            "bootstrap-owner"
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
        AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), "single-owner").await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));
    drop(owner);
    AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), "single-owner")
        .await
        .expect("reopen after owner release");
}

#[tokio::test]
async fn checkpoint_stage_failures_remain_recoverable() {
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
        let fault = set_checkpoint_failpoint(&paths.checkpoint, stage);
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
        drop(fault);
        assert!(matches!(result, Err(AuthBusAuthorityError::Storage(_))));
        host.sync_checkpoint().await.expect("recover checkpoint");
        host.message_issuer(&issuer_id, Generation::new(1).expect("epoch"))
            .await
            .expect("committed issuer remains available");
    }
}

struct ChildGuard(std::process::Child);

impl Drop for ChildGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
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
    let mut child = ChildGuard(
        Command::new(std::env::current_exe().expect("current test executable"))
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
            .expect("spawn owner child"),
    );
    let deadline = Instant::now() + Duration::from_secs(10);
    while !marker.exists() {
        assert!(
            Instant::now() < deadline,
            "child did not acquire owner fence"
        );
        assert!(child.0.try_wait().expect("child state").is_none());
        std::thread::sleep(Duration::from_millis(10));
    }
    assert!(matches!(
        AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), "kill-owner").await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));
    child.0.kill().expect("kill owner child");
    child.0.wait().expect("reap owner child");
    AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), "kill-owner")
        .await
        .expect("owner fence released by process death");
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
                issuer_spec(&format!("issuer:concurrent-{index}"), index),
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
async fn cancelled_waiting_mutation_has_no_effect() {
    let paths = private_paths();
    let host =
        AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), "cancel-owner")
            .await
            .expect("bootstrap");
    let guard = host.mutation.lock().await;
    let result = tokio::time::timeout(
        Duration::from_millis(20),
        host.enroll_issuer(
            IssuerPurpose::Message,
            issuer_spec("issuer:cancelled-waiter", 40),
        ),
    )
    .await;
    assert!(
        result.is_err(),
        "mutation must wait for the publication gate"
    );
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
            issuer_spec("issuer:isolated-fault", 42),
        )
        .await
        .expect("unrelated checkpoint must not inherit fault");
    assert!(
        first
            .enroll_issuer(
                IssuerPurpose::Message,
                issuer_spec("issuer:isolated-fault", 42)
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
async fn failed_create_does_not_unlink_an_existing_checkpoint() {
    let paths = private_paths();
    let host =
        AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), "create-owner")
            .await
            .expect("bootstrap");
    let checkpoint = host.checkpoint.read().expect("current checkpoint");
    let before = std::fs::read(&paths.checkpoint).expect("checkpoint bytes");
    assert!(
        super::create_private_checkpoint(&paths.checkpoint, "other-owner", checkpoint).is_err()
    );
    assert_eq!(
        std::fs::read(&paths.checkpoint).expect("checkpoint retained"),
        before
    );
}

#[tokio::test]
async fn failed_temporary_create_preserves_a_preexisting_file() {
    let paths = private_paths();
    let host =
        AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), "temp-owner")
            .await
            .expect("bootstrap");
    let mut next = host.checkpoint.read().expect("checkpoint");
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
    assert_eq!(
        std::fs::read(&temporary).expect("preexisting file retained"),
        b"preexisting"
    );
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
    assert_eq!(
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
            issuer_spec("issuer:witness-owner", 54),
        )
        .await
        .expect("the original owner remains usable");
}
