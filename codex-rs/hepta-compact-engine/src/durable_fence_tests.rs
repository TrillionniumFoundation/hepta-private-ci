use std::str::FromStr;

use crate::coordinator::CompactionCoordinatorErrorV2;
use crate::durable::DurableCompactionError;
use crate::mutation_guard::MutationGuardStoreV1;
use codex_hepta_types::{Digest32, StableId};
use sqlx::sqlite::{
    SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions, SqliteSynchronous,
};
use sqlx::{Connection, SqliteConnection, SqlitePool};
use tempfile::TempDir;

struct FenceFixture {
    _temp: TempDir,
    pool: SqlitePool,
    guard: MutationGuardStoreV1,
    owner: StableId,
    root: Digest32,
    manifest: Digest32,
}

async fn fenced_store() -> FenceFixture {
    let temp = TempDir::new().expect("temp dir");
    let database_url = format!("sqlite://{}", temp.path().join("fence.db").display());
    let owner = StableId::new("compact-owner").expect("owner");
    let root = Digest32::of_bytes(b"root");
    let token = Digest32::of_bytes(b"lease-one");
    let manifest = Digest32::of_bytes(b"manifest-one");
    let options = SqliteConnectOptions::from_str(&database_url)
        .expect("database options")
        .create_if_missing(true)
        .foreign_keys(true)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Full);
    let pool = SqlitePoolOptions::new()
        .max_connections(4)
        .connect_with(options)
        .await
        .expect("fixture pool");
    sqlx::raw_sql(include_str!("compaction_schema.sql"))
        .execute(&pool)
        .await
        .expect("durable schema");
    sqlx::raw_sql(
        "CREATE TABLE compaction_owner_fence_v2 (
            owner_id TEXT PRIMARY KEY NOT NULL,
            root_key_digest TEXT NOT NULL,
            lease_token_digest TEXT NOT NULL,
            lease_epoch INTEGER NOT NULL,
            lease_expires_at_unix_seconds INTEGER NOT NULL,
            updated_at_unix_seconds INTEGER NOT NULL
         ) WITHOUT ROWID;
         CREATE TABLE compaction_manifest_log_v2 (
            owner_id TEXT NOT NULL,
            manifest_digest TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            predecessor_manifest_digest TEXT,
            root_key_digest TEXT NOT NULL,
            manifest_bytes BLOB NOT NULL,
            activated_at_unix_seconds INTEGER NOT NULL,
            PRIMARY KEY (owner_id, manifest_digest)
         ) WITHOUT ROWID;
         CREATE TABLE active_compaction_manifest_v2 (
            owner_id TEXT PRIMARY KEY NOT NULL,
            manifest_digest TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            updated_at_unix_seconds INTEGER NOT NULL
         ) WITHOUT ROWID;
         CREATE TABLE compaction_publication_admissions_v2 (
            owner_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_digest TEXT NOT NULL,
            archive_digest TEXT NOT NULL,
            checkpoint_digest TEXT NOT NULL,
            root_key_digest TEXT NOT NULL,
            manifest_digest TEXT NOT NULL,
            publication_digest TEXT,
            state TEXT NOT NULL,
            retain_source_until_unix_seconds INTEGER NOT NULL,
            reserved_at_unix_seconds INTEGER NOT NULL,
            committed_at_unix_seconds INTEGER,
            released_at_unix_seconds INTEGER,
            PRIMARY KEY (owner_id, idempotency_key)
         ) WITHOUT ROWID;",
    )
    .execute(&pool)
    .await
    .expect("fence metadata schema");
    sqlx::query(
        "INSERT INTO compaction_owner_fence_v2
         VALUES (?, ?, ?, 1, 1000, 1)",
    )
    .bind(owner.as_str())
    .bind(root.to_string())
    .bind(token.to_string())
    .execute(&pool)
    .await
    .expect("owner fence");
    sqlx::query(
        "INSERT INTO compaction_manifest_log_v2
         VALUES (?, ?, 1, NULL, ?, X'01', 1)",
    )
    .bind(owner.as_str())
    .bind(manifest.to_string())
    .bind(root.to_string())
    .execute(&pool)
    .await
    .expect("manifest");
    sqlx::query(
        "INSERT INTO active_compaction_manifest_v2
         VALUES (?, ?, 1, 1)",
    )
    .bind(owner.as_str())
    .bind(manifest.to_string())
    .execute(&pool)
    .await
    .expect("active manifest");
    let guard = MutationGuardStoreV1::open(
        &database_url,
        owner.as_str(),
        root,
        manifest,
        token,
        1,
    )
    .await
    .expect("mutation guard");
    FenceFixture {
        _temp: temp,
        pool,
        guard,
        owner,
        root,
        manifest,
    }
}

fn assert_fence_conflict(error: CompactionCoordinatorErrorV2) {
    assert!(matches!(
        error,
        CompactionCoordinatorErrorV2::Durable(DurableCompactionError::Conflict(_))
    ));
}

#[tokio::test]
async fn replaced_owner_is_rejected_inside_mutation_transaction() {
    let fixture = fenced_store().await;
    sqlx::query(
        "UPDATE compaction_owner_fence_v2
         SET lease_token_digest = ?, lease_epoch = 2,
             lease_expires_at_unix_seconds = 2000,
             updated_at_unix_seconds = 2
         WHERE owner_id = ?",
    )
    .bind(Digest32::of_bytes(b"lease-two").to_string())
    .bind(fixture.owner.as_str())
    .execute(&fixture.pool)
    .await
    .expect("replace lease");

    let error = fixture
        .guard
        .prepare_retention_release(Digest32::of_bytes(b"checkpoint"), 10)
        .await
        .expect_err("stale owner must fail");
    assert_fence_conflict(error);
}

#[tokio::test]
async fn stale_manifest_is_rejected_inside_mutation_transaction() {
    let fixture = fenced_store().await;
    let successor = Digest32::of_bytes(b"manifest-two");
    sqlx::query(
        "INSERT INTO compaction_manifest_log_v2
         VALUES (?, ?, 2, ?, ?, X'02', 2)",
    )
    .bind(fixture.owner.as_str())
    .bind(successor.to_string())
    .bind(fixture.manifest.to_string())
    .bind(fixture.root.to_string())
    .execute(&fixture.pool)
    .await
    .expect("successor manifest");
    sqlx::query(
        "UPDATE active_compaction_manifest_v2
         SET manifest_digest = ?, sequence = 2, updated_at_unix_seconds = 2
         WHERE owner_id = ?",
    )
    .bind(successor.to_string())
    .bind(fixture.owner.as_str())
    .execute(&fixture.pool)
    .await
    .expect("rotate active manifest");

    let error = fixture
        .guard
        .prepare_retention_release(Digest32::of_bytes(b"checkpoint"), 10)
        .await
        .expect_err("stale manifest must fail");
    assert_fence_conflict(error);
}

#[tokio::test]
async fn null_predecessor_cannot_bypass_monotonic_trigger() {
    assert!(include_str!("compaction_schema_hardening.sql")
        .contains("NEW.predecessor_checkpoint_digest IS NOT OLD.checkpoint_digest"));
    let mut connection = SqliteConnection::connect("sqlite::memory:")
        .await
        .expect("memory database");
    sqlx::raw_sql(
        "CREATE TABLE active_compaction_checkpoint (
            owner_id TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            purpose_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            checkpoint_digest TEXT NOT NULL,
            predecessor_checkpoint_digest TEXT,
            publication_digest TEXT NOT NULL,
            updated_at_unix_seconds INTEGER NOT NULL,
            PRIMARY KEY (owner_id, scope_id, purpose_id)
         ) WITHOUT ROWID;
         CREATE TRIGGER active_compaction_checkpoint_monotonic
         BEFORE UPDATE ON active_compaction_checkpoint
         WHEN NEW.generation != OLD.generation + 1
           OR NEW.predecessor_checkpoint_digest IS NOT OLD.checkpoint_digest
         BEGIN
           SELECT RAISE(ABORT, 'active compaction checkpoint CAS is not monotonic');
         END;
         INSERT INTO active_compaction_checkpoint
         VALUES ('owner', 'scope', 'purpose', 1, 'head-one',
                 NULL, 'publication-one', 1);",
    )
    .execute(&mut connection)
    .await
    .expect("trigger fixture");
    let result = sqlx::query(
        "UPDATE active_compaction_checkpoint
         SET generation = 2, checkpoint_digest = 'head-two',
             predecessor_checkpoint_digest = NULL,
             publication_digest = 'publication-two',
             updated_at_unix_seconds = 2
         WHERE owner_id = 'owner'",
    )
    .execute(&mut connection)
    .await;
    assert!(result.is_err());
}
