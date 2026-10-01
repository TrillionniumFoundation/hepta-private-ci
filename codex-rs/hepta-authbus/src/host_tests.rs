use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::OnceLock;
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

static CHECKPOINT_TEST_LOCK: OnceLock<tokio::sync::Mutex<()>> = OnceLock::new();

struct CheckpointFailpointReset;

impl CheckpointFailpointReset {
    fn enable(stage: u8) -> Self {
        set_checkpoint_failpoint(stage);
        Self
    }
}

impl Drop for CheckpointFailpointReset {
    fn drop(&mut self) {
        set_checkpoint_failpoint(0);
    }
}

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
    let _serial = CHECKPOINT_TEST_LOCK
        .get_or_init(|| tokio::sync::Mutex::new(()))
        .lock()
        .await;
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
        let failpoint = CheckpointFailpointReset::enable(stage);
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
    let _serial = CHECKPOINT_TEST_LOCK
        .get_or_init(|| tokio::sync::Mutex::new(()))
        .lock()
        .await;
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

    let failpoint = CheckpointFailpointReset::enable(1);
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

    let failpoint = CheckpointFailpointReset::enable(1);
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

    let failpoint = CheckpointFailpointReset::enable(1);
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

    let failpoint = CheckpointFailpointReset::enable(1);
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
