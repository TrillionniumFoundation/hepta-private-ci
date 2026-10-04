//! Real SQLite and child-process recovery tests for destination-owned effects.
//!
//! The domain counter and dedupe row share the actual product transaction API.
//! This is local store qualification, not a signed topology, remote-effect or
//! full Agentd deployment/longitudinal-efficacy receipt.

use std::fmt::Debug;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_operations::DestinationApplyStart;
use codex_hepta_operations::DestinationApplyTransaction;
use codex_hepta_operations::DestinationDedupeStore;
use codex_hepta_operations::DestinationOperationIdentity;
use codex_hepta_operations::DurableOperationError;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;

const ROOT_ENV: &str = "HEPTA_DESTINATION_RECOVERY_TEST_ROOT";
const MODE_ENV: &str = "HEPTA_DESTINATION_RECOVERY_TEST_MODE";

fn must<T, E: Debug>(result: Result<T, E>, context: &str) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("{context}: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value), "test identity")
}

fn operation(payload: &[u8]) -> DestinationOperationIdentity {
    DestinationOperationIdentity {
        destination: id("feature.41.destination"),
        scope_id: id("recovery-test"),
        operation_id: id("request.1"),
        payload_digest: Digest32::of_bytes(payload),
    }
}

#[allow(
    clippy::disallowed_methods,
    reason = "fault injection and WAL inspection require one existing-database writer; the production shim creates missing databases"
)]
async fn pool(path: &Path) -> SqlitePool {
    must(
        SqlitePoolOptions::new()
            .max_connections(1)
            .connect_with(SqliteConnectOptions::new().filename(path))
            .await,
        "open existing owner database",
    )
}

#[tokio::test]
async fn fault_probe_refuses_to_create_a_missing_database() {
    let dir = tempfile::tempdir().expect("directory");
    let path = dir.path().join("missing.sqlite3");
    let probe_path = path.clone();
    let opened = tokio::spawn(async move { pool(&probe_path).await }).await;
    assert!(matches!(opened, Err(error) if error.is_panic()));
    assert!(
        !path.exists(),
        "fault probe must not create a missing owner database"
    );
}

#[tokio::test]
async fn fault_probe_keeps_exactly_one_connection() {
    let dir = tempfile::tempdir().expect("directory");
    let path = dir.path().join("owner.sqlite3");
    let store = DestinationDedupeStore::open_standalone(&path)
        .await
        .expect("create actual owner database");
    store.close().await;
    let raw = pool(&path).await;
    assert_eq!(raw.options().get_max_connections(), 1);
    let connection = raw.acquire().await.expect("first probe connection");
    assert!(
        raw.try_acquire().is_none(),
        "second connection must not escape the fault probe bound"
    );
    drop(connection);
    let connection = raw.acquire().await.expect("released probe connection");
    drop(connection);
    raw.close().await;
}

async fn stage_effect(
    store: &DestinationDedupeStore,
    identity: &DestinationOperationIdentity,
) -> DestinationApplyTransaction {
    let start = must(store.begin_apply(identity).await, "admit");
    let DestinationApplyStart::Apply(mut apply) = start else {
        panic!("new request must obtain the domain transaction");
    };
    for query in [
        "CREATE TABLE IF NOT EXISTS domain_counter (value INTEGER NOT NULL)",
        "INSERT INTO domain_counter SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM domain_counter)",
        "UPDATE domain_counter SET value = value + 1",
    ] {
        must(
            sqlx::query(query)
                .execute(&mut **must(apply.transaction(), "owner transaction"))
                .await,
            "stage actual owner mutation",
        );
    }
    apply
}

#[tokio::test]
async fn observation_rejects_same_operation_with_different_payload() {
    let dir = tempfile::tempdir().expect("directory");
    let path = dir.path().join("owner.sqlite3");
    let store = DestinationDedupeStore::open_standalone(&path)
        .await
        .expect("store");
    let original = operation(b"original");
    let receipt = stage_effect(&store, &original)
        .await
        .commit_applied(Digest32::of_bytes(b"counter=1"))
        .await
        .expect("commit");
    assert_eq!(
        store.observe(&original).await.expect("exact observation"),
        Some(receipt)
    );
    let drifted = operation(b"different-effect");
    assert!(matches!(
        store.observe(&drifted).await,
        Err(DurableOperationError::Conflict(_))
    ));
    assert!(matches!(
        store.begin_apply(&drifted).await,
        Err(DurableOperationError::Conflict(_))
    ));
    store.close().await;
    let store = DestinationDedupeStore::open_standalone(&path)
        .await
        .expect("recover");
    assert!(matches!(
        store.observe(&drifted).await,
        Err(DurableOperationError::Conflict(_))
    ));
    assert!(
        store
            .observe(&original)
            .await
            .expect("original remains")
            .is_some()
    );
    store.close().await;
}

#[tokio::test]
async fn unrelated_destination_or_scope_never_borrows_an_applied_receipt() {
    let dir = tempfile::tempdir().expect("directory");
    let path = dir.path().join("owner.sqlite3");
    let store = DestinationDedupeStore::open_standalone(&path)
        .await
        .expect("store");
    let original = operation(b"original");
    stage_effect(&store, &original)
        .await
        .commit_applied(Digest32::of_bytes(b"counter=1"))
        .await
        .expect("commit");
    let mut other = original.clone();
    other.scope_id = id("different-scope");
    assert!(
        store
            .observe(&other)
            .await
            .expect("scope isolation")
            .is_none()
    );
    other = original.clone();
    other.destination = id("different-destination");
    assert!(
        store
            .observe(&other)
            .await
            .expect("destination isolation")
            .is_none()
    );
    store.close().await;
}

#[tokio::test]
async fn valid_width_but_semantically_corrupt_receipts_fail_after_reopen() {
    let original = operation(b"original");
    for (payload, semantic, outcome) in [
        (
            original.payload_digest,
            Digest32::of_bytes(b"wrong-semantic"),
            Digest32::of_bytes(b"ok"),
        ),
        (
            original.payload_digest,
            original.semantic_digest(),
            Digest32::ZERO,
        ),
        (
            Digest32::ZERO,
            original.semantic_digest(),
            Digest32::of_bytes(b"ok"),
        ),
    ] {
        let dir = tempfile::tempdir().expect("directory");
        let path = dir.path().join("owner.sqlite3");
        let store = DestinationDedupeStore::open_standalone(&path)
            .await
            .expect("migrate");
        store.close().await;
        let raw = pool(&path).await;
        // Owner-level fault injection: no trigger, schema or production check is
        // disabled. Width-valid INSERTs demonstrate why quick_check is not enough.
        sqlx::query(
            "INSERT INTO destination_operation_dedupe
             (destination, scope_id, operation_id, payload_digest, semantic_digest,
              outcome_digest, applied_at_ms) VALUES (?, ?, ?, ?, ?, ?, 1)",
        )
        .bind(original.destination.as_str())
        .bind(original.scope_id.as_str())
        .bind(original.operation_id.as_str())
        .bind(payload.as_array().as_slice())
        .bind(semantic.as_array().as_slice())
        .bind(outcome.as_array().as_slice())
        .execute(&raw)
        .await
        .expect("inject width-valid owner row");
        raw.close().await;
        let store = DestinationDedupeStore::open_standalone(&path)
            .await
            .expect("structural reopen");
        assert!(matches!(
            store.observe(&original).await,
            Err(DurableOperationError::Corrupt(_))
        ));
        assert!(matches!(
            store.begin_apply(&original).await,
            Err(DurableOperationError::Corrupt(_))
        ));
        store.close().await;
    }
}

#[tokio::test]
async fn growing_history_keeps_early_identity_and_domain_count_after_restart() {
    let dir = tempfile::tempdir().expect("directory");
    let path = dir.path().join("owner.sqlite3");
    let mut previous = 0;
    let mut first_receipt = None;
    for limit in [1, 16, 64, 256] {
        let started = Instant::now();
        let store = DestinationDedupeStore::open_standalone(&path)
            .await
            .expect("reopen owner");
        let reopen_micros = started.elapsed().as_micros();
        let started = Instant::now();
        for index in previous..limit {
            let mut identity = operation(b"bounded owner payload");
            identity.operation_id = id(&format!("request.{index}"));
            let receipt = stage_effect(&store, &identity)
                .await
                .commit_applied(Digest32::of_bytes(
                    format!("counter={}", index + 1).as_bytes(),
                ))
                .await
                .expect("atomic domain and receipt commit");
            if first_receipt.is_none() {
                first_receipt = Some(receipt);
            }
        }
        let append_micros = started.elapsed().as_micros();
        let first = first_receipt.as_ref().expect("first receipt");
        assert_eq!(
            store
                .observe(&first.identity)
                .await
                .expect("observe early request"),
            Some(first.clone())
        );
        assert!(matches!(
            store
                .begin_apply(&first.identity)
                .await
                .expect("early replay"),
            DestinationApplyStart::AlreadyApplied(_)
        ));
        let raw = pool(&path).await;
        let count: i64 = sqlx::query_scalar("SELECT value FROM domain_counter")
            .fetch_one(&raw)
            .await
            .expect("actual domain count");
        assert_eq!(count, i64::from(limit));
        let checkpoint = sqlx::query("PRAGMA wal_checkpoint(TRUNCATE)")
            .fetch_one(&raw)
            .await
            .expect("checkpoint");
        assert_eq!(checkpoint.try_get::<i64, _>(0).expect("checkpoint busy"), 0);
        raw.close().await;
        store.close().await;
        let bytes = std::fs::metadata(&path).expect("database bytes").len();
        eprintln!(
            "destination_recovery_curve records={limit} reopen_us={reopen_micros} append_us={append_micros} database_bytes={bytes}"
        );
        previous = limit;
    }
}

fn run_crash_worker(path: &Path, mode: &str, expected: i32) {
    let mut child = must(
        Command::new(must(std::env::current_exe(), "test executable"))
            .args([
                "--ignored",
                "--exact",
                "destination_crash_worker",
                "--nocapture",
            ])
            .env(ROOT_ENV, path)
            .env(MODE_ENV, mode)
            .stdin(Stdio::null())
            .spawn(),
        "spawn real owner process",
    );
    let deadline = Instant::now() + Duration::from_secs(30);
    loop {
        if let Some(status) = must(child.try_wait(), "observe child") {
            assert_eq!(
                status.code(),
                Some(expected),
                "owner did not reach crash point"
            );
            break;
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            panic!("owner subprocess exceeded recovery test deadline");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[test]
#[ignore = "only the parent recovery tests run this fresh-process crash fixture"]
fn destination_crash_worker() {
    let path = std::env::var_os(ROOT_ENV).expect("parent-provided database path");
    let mode = std::env::var(MODE_ENV).expect("parent-provided crash mode");
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    runtime.block_on(async {
        let store = DestinationDedupeStore::open_standalone(Path::new(&path))
            .await
            .expect("child store");
        let apply = stage_effect(&store, &operation(b"crash-test")).await;
        match mode.as_str() {
            "after-commit" => {
                apply
                    .commit_applied(Digest32::of_bytes(b"counter=1"))
                    .await
                    .expect("durable commit before lost acknowledgement");
                // No destructors, pool close or graceful owner shutdown runs.
                std::process::exit(73);
            }
            "before-commit" => std::process::exit(74),
            _ => panic!("unsupported crash mode"),
        }
    });
}

#[tokio::test]
async fn process_loss_after_commit_reconciles_without_repeating_domain_effect() {
    let dir = tempfile::tempdir().expect("directory");
    let path = dir.path().join("owner.sqlite3");
    run_crash_worker(&path, "after-commit", 73);
    let identity = operation(b"crash-test");
    // Each reopen is a new owner handle. The original process has terminated.
    for _ in 0..4 {
        let store = DestinationDedupeStore::open_standalone(&path)
            .await
            .expect("recover owner");
        let receipt = store
            .observe(&identity)
            .await
            .expect("reconcile")
            .expect("committed fact");
        assert_eq!(receipt.outcome_digest, Digest32::of_bytes(b"counter=1"));
        assert!(matches!(
            store.begin_apply(&identity).await.expect("same request"),
            DestinationApplyStart::AlreadyApplied(_)
        ));
        assert!(matches!(
            store.observe(&operation(b"substituted")).await,
            Err(DurableOperationError::Conflict(_))
        ));
        let raw = pool(&path).await;
        let count: i64 = sqlx::query_scalar("SELECT value FROM domain_counter")
            .fetch_one(&raw)
            .await
            .expect("counter");
        assert_eq!(count, 1);
        raw.close().await;
        store.close().await;
    }
}

#[tokio::test]
async fn process_loss_before_commit_rolls_back_domain_and_receipt_together() {
    let dir = tempfile::tempdir().expect("directory");
    let path = dir.path().join("owner.sqlite3");
    run_crash_worker(&path, "before-commit", 74);
    let store = DestinationDedupeStore::open_standalone(&path)
        .await
        .expect("recover owner");
    let identity = operation(b"crash-test");
    assert!(
        store
            .observe(&identity)
            .await
            .expect("no committed receipt")
            .is_none()
    );
    stage_effect(&store, &identity)
        .await
        .commit_applied(Digest32::of_bytes(b"counter=1"))
        .await
        .expect("first actual commit after rollback");
    let raw = pool(&path).await;
    let count: i64 = sqlx::query_scalar("SELECT value FROM domain_counter")
        .fetch_one(&raw)
        .await
        .expect("counter");
    assert_eq!(count, 1);
    raw.close().await;
    store.close().await;
}
