use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use super::AuthBusAuthorityHost;
use crate::AuthBusAuthorityError;
use crate::IssuerPurpose;
use crate::IssuerSpec;

struct Paths {
    _root: TempDir,
    database: PathBuf,
    checkpoint: PathBuf,
}

#[expect(clippy::expect_used, reason = "private test fixture setup must fail the test")]
fn private_paths() -> Paths {
    use std::os::unix::fs::PermissionsExt;

    let root = TempDir::new().expect("temporary root");
    let canonical = root.path().canonicalize().expect("canonical root");
    let database_root = canonical.join("database");
    let checkpoint_root = canonical.join("checkpoint");
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

async fn reopen_after_drain(paths: &Paths, owner_id: &str) -> AuthBusAuthorityHost {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        match AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), owner_id).await
        {
            Ok(host) => return host,
            Err(AuthBusAuthorityError::OwnerAlreadyActive) if Instant::now() < deadline => {
                // Pool driver shutdown is asynchronous. Yield to it without
                // treating a still-live capability as permission to unlock.
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            Err(error) => panic!("reopen after bounded owner drain: {error}"),
        }
    }
}

// A failed assertion must not orphan a subprocess holding the authority fence.
struct OwnerChild(Child);

impl Drop for OwnerChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
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
    owner.close().await.expect("drain owner");
    reopen_after_drain(&paths, "single-owner")
        .await
        .close()
        .await
        .expect("close replacement");
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
        host.set_checkpoint_failpoint(stage);
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
        host.set_checkpoint_failpoint(0);
        assert!(matches!(
            result,
            Err(AuthBusAuthorityError::MutationIncomplete {
                disposition: crate::AuthBusMutationDisposition::Committed,
                ..
            })
        ));
        host.sync_checkpoint().await.expect("recover checkpoint");
        host.message_issuer(&issuer_id, Generation::new(1).expect("epoch"))
            .await
            .expect("committed issuer remains available");
        host.close().await.expect("drain recovered owner");
    }
}

#[tokio::test]
async fn kill_nine_releases_the_process_owner_fence() {
    let paths = private_paths();
    let initial =
        AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), "kill-owner")
            .await
            .expect("bootstrap owner");
    initial.close().await.expect("drain bootstrap owner");

    let marker = paths._root.path().join("owner-ready");
    let mut child = OwnerChild(
        Command::new(std::env::current_exe().expect("current test executable"))
            .arg("host::tests::owner_child_process_holds_fence")
            .arg("--exact")
            .arg("--nocapture")
            .env("AUTHBUS_OWNER_CHILD", "1")
            .env("AUTHBUS_OWNER_DATABASE", &paths.database)
            .env("AUTHBUS_OWNER_CHECKPOINT", &paths.checkpoint)
            .env("AUTHBUS_OWNER_MARKER", &marker)
            .spawn()
            .expect("spawn owner child"),
    );
    let deadline = Instant::now() + Duration::from_secs(10);
    while !marker.exists() && Instant::now() < deadline {
        assert!(
            child.0.try_wait().expect("poll child").is_none(),
            "child exited before acquiring owner fence"
        );
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert!(marker.exists(), "child did not acquire owner fence");
    assert!(matches!(
        AuthBusAuthorityHost::open(&paths.database, paths.checkpoint.clone(), "kill-owner",).await,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));

    // Child::kill is SIGKILL on the Unix targets of this test module.
    child.0.kill().expect("kill child");
    let status = child.0.wait().expect("wait for killed child");
    assert!(!status.success());
    reopen_after_drain(&paths, "kill-owner")
        .await
        .close()
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
    let deadline = Instant::now() + Duration::from_secs(5);
    let _host = loop {
        match AuthBusAuthorityHost::open(&database, checkpoint.clone(), "kill-owner").await {
            Ok(host) => break host,
            Err(AuthBusAuthorityError::OwnerAlreadyActive) if Instant::now() < deadline => {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            Err(error) => panic!("child owner open: {error}"),
        }
    };
    std::fs::write(marker, b"ready").expect("write child marker");
    tokio::time::sleep(Duration::from_secs(60)).await;
}
