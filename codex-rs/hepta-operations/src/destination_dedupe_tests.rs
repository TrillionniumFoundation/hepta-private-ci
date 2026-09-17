use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use super::*;

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

async fn destination_pool(temp: &TempDir) -> sqlx::SqlitePool {
    let sqlite = sqlite_config(temp);
    let path = temp.path().join("destination.sqlite");
    let pool = sqlite
        .open_durable_evidence_pool(&path)
        .await
        .expect("open destination pool");
    sqlx::query(
        "CREATE TABLE kernel_operation_dedupe (
            destination_id TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            payload_digest BLOB NOT NULL CHECK (length(payload_digest) = 32),
            state TEXT NOT NULL CHECK (state IN ('reserved','applied','not_applied','quarantined')),
            evidence_digest BLOB,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            PRIMARY KEY(destination_id, scope_id, operation_id)
        ) WITHOUT ROWID",
    )
    .execute(&pool)
    .await
    .expect("create dedupe table");
    sqlx::query(
        "CREATE TABLE destination_values (
            operation_id TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID",
    )
    .execute(&pool)
    .await
    .expect("create domain table");
    pool
}

fn key(payload: &[u8]) -> DestinationDedupeKey {
    DestinationDedupeKey {
        destination_id: stable_id("destination:test"),
        scope_id: stable_id("scope:test"),
        operation_id: stable_id("operation:dedupe"),
        payload_digest: Digest32::of_bytes(payload),
    }
}

#[tokio::test]
async fn destination_domain_mutation_and_dedupe_commit_atomically() {
    let temp = TempDir::new().expect("temp dir");
    let pool = destination_pool(&temp).await;
    let key = key(b"payload");
    let mut tx = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("begin destination tx");
    assert_eq!(
        reserve_destination_effect(&mut tx, &key, 10)
            .await
            .expect("reserve"),
        DestinationReserveDisposition::Reserved
    );
    sqlx::query("INSERT INTO destination_values(operation_id, value) VALUES (?, ?)")
        .bind(key.operation_id.as_str())
        .bind("applied-once")
        .execute(&mut *tx)
        .await
        .expect("apply domain mutation");
    record_destination_terminal(
        &mut tx,
        &key,
        ReconciliationOutcome::Applied,
        Digest32::of_bytes(b"terminal-receipt"),
        11,
    )
    .await
    .expect("terminal receipt");
    tx.commit().await.expect("commit destination tx");

    let mut replay = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("begin replay tx");
    let existing = reserve_destination_effect(&mut replay, &key, 12)
        .await
        .expect("replay reserve");
    assert!(matches!(
        existing,
        DestinationReserveDisposition::Existing(DestinationDedupeRecord {
            state: DestinationDedupeState::Applied,
            ..
        })
    ));
    replay.commit().await.expect("commit replay observation");
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM destination_values")
        .fetch_one(&pool)
        .await
        .expect("count domain rows");
    assert_eq!(count, 1);
}

#[tokio::test]
async fn rollback_removes_both_destination_mutation_and_reservation() {
    let temp = TempDir::new().expect("temp dir");
    let pool = destination_pool(&temp).await;
    let key = key(b"payload");
    let mut tx = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("begin destination tx");
    assert_eq!(
        reserve_destination_effect(&mut tx, &key, 10)
            .await
            .expect("reserve"),
        DestinationReserveDisposition::Reserved
    );
    sqlx::query("INSERT INTO destination_values(operation_id, value) VALUES (?, ?)")
        .bind(key.operation_id.as_str())
        .bind("must-roll-back")
        .execute(&mut *tx)
        .await
        .expect("apply domain mutation");
    drop(tx);

    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM destination_values")
        .fetch_one(&pool)
        .await
        .expect("count domain rows");
    assert_eq!(count, 0);
    let mut retry = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("begin retry tx");
    assert_eq!(
        reserve_destination_effect(&mut retry, &key, 20)
            .await
            .expect("reserve after rollback"),
        DestinationReserveDisposition::Reserved
    );
}

#[tokio::test]
async fn destination_identity_reuse_with_payload_drift_conflicts() {
    let temp = TempDir::new().expect("temp dir");
    let pool = destination_pool(&temp).await;
    let original = key(b"payload");
    let mut tx = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("begin tx");
    reserve_destination_effect(&mut tx, &original, 10)
        .await
        .expect("reserve original");
    record_destination_terminal(
        &mut tx,
        &original,
        ReconciliationOutcome::Applied,
        Digest32::of_bytes(b"receipt"),
        11,
    )
    .await
    .expect("settle original");
    tx.commit().await.expect("commit original");

    let changed = key(b"changed");
    let mut replay = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("begin replay");
    assert_eq!(
        reserve_destination_effect(&mut replay, &changed, 20).await,
        Err(OperationError::Conflict(changed.operation_id))
    );
}
