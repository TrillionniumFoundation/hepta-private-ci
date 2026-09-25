use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::Arc;

use ed25519_dalek::SigningKey;
use tempfile::TempDir;
use tokio::task::JoinSet;

use super::*;
use crate::IssuerLifecycleState;

const OWNER_ID: &str = "authbus-owner:test";

type FixtureResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

fn id(value: &str) -> FixtureResult<StableId> {
    Ok(StableId::new(value)?)
}

fn issuer_spec(value: &str, key_byte: u8) -> FixtureResult<IssuerSpec> {
    Ok(IssuerSpec {
        issuer_id: id(value)?,
        key_epoch: Generation::new(1)?,
        verifying_key: SigningKey::from_bytes(&[key_byte; 32]).verifying_key(),
    })
}

async fn initialized_host() -> FixtureResult<(
    TempDir,
    PathBuf,
    PathBuf,
    AuthBusAuthorityHost,
    AuthorityCheckpoint,
)> {
    let root = TempDir::new()?;
    let database_root = root.path().join("database");
    let checkpoint_root = root.path().join("checkpoint");
    std::fs::create_dir(&database_root)?;
    std::fs::create_dir(&checkpoint_root)?;
    std::fs::set_permissions(&database_root, std::fs::Permissions::from_mode(0o700))?;
    std::fs::set_permissions(&checkpoint_root, std::fs::Permissions::from_mode(0o700))?;
    let database = database_root.join("authbus.sqlite");
    let checkpoint = checkpoint_root.join("authority.checkpoint.json");

    let host = AuthBusAuthorityHost::bootstrap(&database, checkpoint.clone(), OWNER_ID).await?;
    let first = host
        .store
        .authority_checkpoint()
        .await?
        .ok_or("missing initialized checkpoint")?;
    assert_eq!(host.store.authority_checkpoint().await?, Some(first));
    assert_eq!(host.checkpoint.read()?, first);
    Ok((root, database, checkpoint, host, first))
}

#[tokio::test]
async fn bootstrap_rejects_populated_database_without_external_witness() {
    let root = TempDir::new().expect("temporary root");
    let database_root = root.path().join("database");
    let checkpoint_root = root.path().join("checkpoint");
    std::fs::create_dir(&database_root).expect("database root");
    std::fs::create_dir(&checkpoint_root).expect("checkpoint root");
    std::fs::set_permissions(&database_root, std::fs::Permissions::from_mode(0o700))
        .expect("private database root");
    std::fs::set_permissions(&checkpoint_root, std::fs::Permissions::from_mode(0o700))
        .expect("private checkpoint root");
    let database = database_root.join("authbus.sqlite");
    let checkpoint = checkpoint_root.join("authority.checkpoint.json");

    let store = AuthBusAuthorityStore::open(&database)
        .await
        .expect("open low-level fixture store");
    store
        .enroll_issuer(
            IssuerPurpose::Message,
            issuer_spec("issuer:unwitnessed", 40).unwrap(),
        )
        .await
        .expect("create unwitnessed state");
    store.pool.close().await;

    assert!(matches!(
        AuthBusAuthorityHost::bootstrap(&database, checkpoint, OWNER_ID).await,
        Err(AuthBusAuthorityError::UnsafeCheckpoint)
    ));
}

#[tokio::test]
async fn reopen_promotes_checkpoint_already_published_externally() {
    let (_root, database, checkpoint, host, first) = initialized_host().await.unwrap();
    let record = host
        .store
        .enroll_issuer(
            IssuerPurpose::Settlement,
            issuer_spec("issuer:published-before-reopen", 41).unwrap(),
        )
        .await
        .expect("commit issuer before publication");
    let published = host
        .store
        .reconcile_authority_checkpoint(first)
        .await
        .expect("stage successor")
        .expect("dirty frontier");
    host.checkpoint
        .replace(first, published)
        .expect("publish external successor");
    assert_eq!(
        host.store
            .authority_checkpoint()
            .await
            .expect("local checkpoint before crash"),
        Some(first)
    );
    drop(host);

    let reopened = AuthBusAuthorityHost::open(&database, checkpoint, OWNER_ID)
        .await
        .expect("reopen after external publication");
    assert_eq!(
        reopened
            .store
            .authority_checkpoint()
            .await
            .expect("promoted checkpoint"),
        Some(published)
    );
    assert_eq!(
        reopened.checkpoint.read().expect("external checkpoint"),
        published
    );
    assert_eq!(
        reopened
            .store
            .issuer_record(
                IssuerPurpose::Settlement,
                &record.issuer_id,
                record.key_epoch,
            )
            .await
            .expect("issuer survives reopen")
            .state,
        IssuerLifecycleState::Active
    );
}

#[tokio::test]
async fn next_mutation_promotes_published_predecessor_before_appending() {
    let (_root, _database, _checkpoint, host, first) = initialized_host().await.unwrap();
    let predecessor = host
        .store
        .enroll_issuer(
            IssuerPurpose::Message,
            issuer_spec("issuer:published-predecessor", 42).unwrap(),
        )
        .await
        .expect("commit predecessor");
    let published = host
        .store
        .reconcile_authority_checkpoint(first)
        .await
        .expect("stage predecessor checkpoint")
        .expect("dirty predecessor");
    host.checkpoint
        .replace(first, published)
        .expect("publish predecessor externally");

    let successor = host
        .enroll_issuer(
            IssuerPurpose::Settlement,
            issuer_spec("issuer:successor-after-recovery", 43).unwrap(),
        )
        .await
        .expect("recover predecessor before successor");
    let local = host
        .store
        .authority_checkpoint()
        .await
        .expect("local checkpoint")
        .expect("initialized checkpoint");
    assert_eq!(local.generation, published.generation + 1);
    assert_eq!(host.checkpoint.read().expect("external checkpoint"), local);
    assert_eq!(
        host.store
            .issuer_record(
                IssuerPurpose::Message,
                &predecessor.issuer_id,
                predecessor.key_epoch,
            )
            .await
            .expect("predecessor issuer")
            .state,
        IssuerLifecycleState::Active
    );
    assert_eq!(
        host.store
            .issuer_record(
                IssuerPurpose::Settlement,
                &successor.issuer_id,
                successor.key_epoch,
            )
            .await
            .expect("successor issuer")
            .state,
        IssuerLifecycleState::Active
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn concurrent_host_mutations_publish_one_monotonic_generation_each() {
    let (_root, _database, _checkpoint, host, first) = initialized_host().await.unwrap();
    let host = Arc::new(host);
    let mut tasks = JoinSet::new();
    for index in 0_u8..8 {
        let host = Arc::clone(&host);
        tasks.spawn(async move {
            host.enroll_issuer(
                IssuerPurpose::Message,
                issuer_spec(&format!("issuer:concurrent:{index}"), 60 + index).unwrap(),
            )
            .await
        });
    }
    while let Some(result) = tasks.join_next().await {
        result.expect("join concurrent mutation").expect("mutation");
    }
    let local = host
        .store
        .authority_checkpoint()
        .await
        .expect("local checkpoint")
        .expect("initialized checkpoint");
    assert_eq!(local.generation, first.generation + 8);
    assert_eq!(host.checkpoint.read().expect("external checkpoint"), local);
}

#[tokio::test]
async fn separate_hosts_fail_closed_while_the_owner_lock_is_held() {
    let (_root, database, checkpoint, host, first) = initialized_host().await.unwrap();
    let contender = AuthBusAuthorityHost::open(&database, checkpoint, OWNER_ID)
        .await
        .expect("open second host instance");

    let local_gate = host
        .mutation_gate
        .acquire()
        .await
        .expect("hold local mutation permit");
    let process_guard = try_owner_lock(&host.owner_file).expect("hold cross-process owner lock");
    assert!(matches!(
        contender
            .enroll_issuer(
                IssuerPurpose::Message,
                issuer_spec("issuer:blocked-contender", 90).unwrap(),
            )
            .await,
        Err(AuthBusAuthorityError::OwnerBusy)
    ));
    drop(process_guard);
    drop(local_gate);

    let enrolled = contender
        .enroll_issuer(
            IssuerPurpose::Message,
            issuer_spec("issuer:blocked-contender", 90).unwrap(),
        )
        .await
        .expect("retry after owner lock release");
    let local = contender
        .store
        .authority_checkpoint()
        .await
        .expect("local checkpoint")
        .expect("initialized checkpoint");
    assert_eq!(local.generation, first.generation + 1);
    assert_eq!(
        contender
            .checkpoint
            .read()
            .expect("external checkpoint after retry"),
        local
    );
    assert_eq!(
        contender
            .store
            .issuer_record(
                IssuerPurpose::Message,
                &enrolled.issuer_id,
                enrolled.key_epoch,
            )
            .await
            .expect("enrolled issuer")
            .state,
        IssuerLifecycleState::Active
    );
}

#[tokio::test]
async fn failed_external_publication_is_reconciled_before_the_next_write() {
    let (_root, _, checkpoint, host, first) = initialized_host().await.unwrap();
    let name = checkpoint.file_name().unwrap().to_str().unwrap();
    let temporary = checkpoint.parent().unwrap().join(format!(
        ".{name}.{}.{}.tmp",
        std::process::id(),
        first.generation + 1
    ));
    std::fs::write(&temporary, b"occupied temporary publication path").unwrap();
    let previous = issuer_spec("issuer:unacknowledged", 91).unwrap();
    assert!(matches!(
        host.enroll_issuer(
            IssuerPurpose::Message,
            issuer_spec("issuer:unacknowledged", 91).unwrap()
        )
        .await,
        Err(AuthBusAuthorityError::Storage(_))
    ));
    assert_eq!(host.checkpoint.read().unwrap(), first);
    host.enroll_issuer(
        IssuerPurpose::Message,
        issuer_spec("issuer:after-failure", 92).unwrap(),
    )
    .await
    .expect("recover previous publication before appending");
    let local = host.store.authority_checkpoint().await.unwrap().unwrap();
    assert_eq!(local.generation, first.generation + 2);
    assert_eq!(host.checkpoint.read().unwrap(), local);
    assert_eq!(
        host.store
            .issuer_record(
                IssuerPurpose::Message,
                &previous.issuer_id,
                previous.key_epoch
            )
            .await
            .unwrap()
            .state,
        IssuerLifecycleState::Active
    );
}

#[tokio::test]
async fn a_second_witness_path_cannot_bypass_database_writer_exclusion() {
    let (_root, database, checkpoint, host, _) = initialized_host().await.unwrap();
    let alternate = checkpoint.with_file_name("alternate.checkpoint.json");
    std::fs::copy(&checkpoint, &alternate).unwrap();
    let contender = AuthBusAuthorityHost::open(&database, alternate, OWNER_ID)
        .await
        .unwrap();
    let database_guard = try_owner_lock(&host.database_file).unwrap();
    assert!(matches!(
        contender
            .enroll_issuer(
                IssuerPurpose::Message,
                issuer_spec("issuer:fork", 93).unwrap()
            )
            .await,
        Err(AuthBusAuthorityError::OwnerBusy)
    ));
    drop(database_guard);
}

#[tokio::test]
async fn owner_lock_fences_a_separate_process() {
    const PROBE: &str = "HEPTA_AUTHBUS_LOCK_PROBE_PATH";
    if let Some(path) = std::env::var_os(PROBE) {
        let file = open_private_owner_lock(Path::new(&path)).unwrap();
        assert!(matches!(
            try_owner_lock(&file),
            Err(AuthBusAuthorityError::OwnerBusy)
        ));
        return;
    }
    let (_root, database, _, host, _) = initialized_host().await.unwrap();
    let _guard = try_owner_lock(&host.database_file).unwrap();
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "host::tests::owner_lock_fences_a_separate_process",
            "--nocapture",
        ])
        .env(PROBE, database)
        .status()
        .expect("execute independent process");
    assert!(status.success());
}

#[path = "host_lock_tests.rs"]
mod lock_tests;
