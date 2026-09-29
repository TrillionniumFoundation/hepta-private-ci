use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::IssuerPurpose;
use crate::IssuerSpec;

struct Fixture {
    _database_root: tempfile::TempDir,
    _checkpoint_root: tempfile::TempDir,
    database: PathBuf,
    checkpoint: PathBuf,
    host: AuthBusAuthorityHost,
}

async fn fixture() -> Fixture {
    let database_root = tempfile::tempdir().expect("database root");
    let checkpoint_root = tempfile::tempdir().expect("checkpoint root");
    std::fs::set_permissions(database_root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("database permissions");
    std::fs::set_permissions(
        checkpoint_root.path(),
        std::fs::Permissions::from_mode(0o700),
    )
    .expect("checkpoint permissions");
    let database = database_root.path().join("authbus.sqlite");
    let checkpoint = checkpoint_root.path().join("authority.json");
    let host = AuthBusAuthorityBootstrap::initialize(
        &database,
        checkpoint.clone(),
        "test-owner",
    )
    .await
    .expect("bootstrap authority owner");
    Fixture {
        _database_root: database_root,
        _checkpoint_root: checkpoint_root,
        database,
        checkpoint,
        host,
    }
}

fn issuer(index: u8) -> IssuerSpec {
    let key = SigningKey::from_bytes(&[index; 32]);
    IssuerSpec {
        issuer_id: StableId::new(format!("issuer:concurrent:{index}"))
            .expect("issuer identifier"),
        key_epoch: Generation::new(1).expect("generation"),
        verifying_key: key.verifying_key(),
    }
}

#[tokio::test]
async fn one_checkpoint_has_exactly_one_live_writer() {
    let fixture = fixture().await;
    assert!(matches!(
        AuthBusAuthorityHost::open(
            &fixture.database,
            fixture.checkpoint.clone(),
            "test-owner",
        )
        .await,
        Err(AuthBusAuthorityError::WriterAlreadyActive)
    ));
    drop(fixture.host);
    AuthBusAuthorityHost::open(
        &fixture.database,
        fixture.checkpoint,
        "test-owner",
    )
    .await
    .expect("writer lock is released with the owner");
}

#[tokio::test]
async fn concurrent_mutations_publish_one_ordered_checkpoint_chain() {
    let fixture = fixture().await;
    let host = Arc::new(fixture.host);
    let mut tasks = Vec::new();
    for index in 1..=16 {
        let host = Arc::clone(&host);
        tasks.push(tokio::spawn(async move {
            host.admin_port()
                .enroll_issuer(IssuerPurpose::Message, issuer(index))
                .await
        }));
    }
    for task in tasks {
        task.await
            .expect("task")
            .expect("serialized issuer enrollment");
    }
    for index in 1..=16 {
        let registration = host
            .read_port()
            .message_issuer(&issuer(index).issuer_id, Generation::new(1).expect("generation"))
            .await
            .expect("issuer registration");
        assert!(!registration.revoked);
    }
    let external = host.checkpoint.read().expect("external checkpoint");
    let local = host
        .store
        .authority_checkpoint()
        .await
        .expect("local checkpoint")
        .expect("initialized checkpoint");
    assert_eq!(external, local);
}

#[tokio::test]
async fn reopen_finishes_a_crash_before_external_publication() {
    let fixture = fixture().await;
    fixture
        .host
        .store
        .enroll_issuer(IssuerPurpose::Message, issuer(31))
        .await
        .expect("commit dirty owner state");
    let before = fixture.host.checkpoint.read().expect("old checkpoint");
    drop(fixture.host);

    let reopened = AuthBusAuthorityHost::open(
        &fixture.database,
        fixture.checkpoint,
        "test-owner",
    )
    .await
    .expect("reconcile dirty local state");
    let after = reopened.checkpoint.read().expect("new checkpoint");
    assert_eq!(after.generation, before.generation + 1);
    assert_eq!(
        Some(after),
        reopened
            .store
            .authority_checkpoint()
            .await
            .expect("local checkpoint")
    );
}

#[tokio::test]
async fn reopen_finishes_a_crash_after_external_publication() {
    let fixture = fixture().await;
    fixture
        .host
        .store
        .enroll_issuer(IssuerPurpose::Message, issuer(32))
        .await
        .expect("commit dirty owner state");
    let current = fixture.host.checkpoint.read().expect("current checkpoint");
    let next = fixture
        .host
        .store
        .reconcile_authority_checkpoint(current)
        .await
        .expect("calculate successor")
        .expect("dirty successor");
    fixture
        .host
        .checkpoint
        .replace(current, next)
        .expect("publish successor");
    drop(fixture.host);

    let reopened = AuthBusAuthorityHost::open(
        &fixture.database,
        fixture.checkpoint,
        "test-owner",
    )
    .await
    .expect("promote already-published successor");
    assert_eq!(
        Some(next),
        reopened
            .store
            .authority_checkpoint()
            .await
            .expect("local checkpoint")
    );
}
