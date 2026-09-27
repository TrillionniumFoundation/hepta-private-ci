use super::*;
use tempfile::TempDir;

async fn fenced_store(
    owner_id: &str,
    root: Digest32,
    token: Digest32,
    manifest: Digest32,
) -> (TempDir, DurableCompactionStoreV1) {
    let temp = TempDir::new().expect("temp dir");
    let database_url =
        format!("sqlite://{}", temp.path().join("fence.db").display());
    let seed = DurableCompactionStoreV1::open(&database_url, owner_id)
        .await
        .expect("seed store");
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
         ) WITHOUT ROWID;",
    )
    .execute(&seed.inner.pool)
    .await
    .expect("metadata schema");
    sqlx::query(
        "INSERT INTO compaction_owner_fence_v2
         VALUES (?, ?, ?, 1, 1000, 1)",
    )
    .bind(owner_id)
    .bind(root.to_string())
    .bind(token.to_string())
    .execute(&seed.inner.pool)
    .await
    .expect("owner fence");
    sqlx::query(
        "INSERT INTO compaction_manifest_log_v2
         VALUES (?, ?, 1, NULL, ?, X'01', 1)",
    )
    .bind(owner_id)
    .bind(manifest.to_string())
    .bind(root.to_string())
    .execute(&seed.inner.pool)
    .await
    .expect("manifest");
    sqlx::query(
        "INSERT INTO active_compaction_manifest_v2
         VALUES (?, ?, 1, 1)",
    )
    .bind(owner_id)
    .bind(manifest.to_string())
    .execute(&seed.inner.pool)
    .await
    .expect("active manifest");
    drop(seed);
    let store = DurableCompactionStoreV1::open(&database_url, owner_id)
        .await
        .expect("fenced store");
    (temp, store)
}

#[tokio::test]
async fn replaced_owner_is_rejected_inside_artifact_transaction() {
    let owner = StableId::new("compact-owner").expect("owner");
    let root = Digest32::of_bytes(b"root");
    let token = Digest32::of_bytes(b"lease-one");
    let manifest = Digest32::of_bytes(b"manifest-one");
    let (_temp, store) =
        fenced_store(owner.as_str(), root, token, manifest).await;

    sqlx::query(
        "UPDATE compaction_owner_fence_v2
         SET lease_token_digest = ?, lease_epoch = 2,
             lease_expires_at_unix_seconds = 2000
         WHERE owner_id = ?",
    )
    .bind(Digest32::of_bytes(b"lease-two").to_string())
    .bind(owner.as_str())
    .execute(&store.inner.pool)
    .await
    .expect("replace lease");

    let mut connection = store.inner.pool.acquire().await.expect("connection");
    sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut *connection)
        .await
        .expect("begin");
    let error = store
        .verify_publication_fence_identity_tx(
            &mut connection,
            &owner,
            root,
            manifest,
        )
        .await
        .expect_err("stale owner must fail");
    assert!(matches!(error, DurableCompactionError::Conflict(_)));
    sqlx::query("ROLLBACK")
        .execute(&mut *connection)
        .await
        .expect("rollback");
}

#[tokio::test]
async fn stale_manifest_is_rejected_inside_artifact_transaction() {
    let owner = StableId::new("compact-owner").expect("owner");
    let root = Digest32::of_bytes(b"root");
    let token = Digest32::of_bytes(b"lease-one");
    let manifest = Digest32::of_bytes(b"manifest-one");
    let (_temp, store) =
        fenced_store(owner.as_str(), root, token, manifest).await;
    let mut connection = store.inner.pool.acquire().await.expect("connection");
    sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut *connection)
        .await
        .expect("begin");
    let error = store
        .verify_publication_fence_identity_tx(
            &mut connection,
            &owner,
            root,
            Digest32::of_bytes(b"stale-manifest"),
        )
        .await
        .expect_err("stale manifest must fail");
    assert!(matches!(error, DurableCompactionError::Conflict(_)));
    sqlx::query("ROLLBACK")
        .execute(&mut *connection)
        .await
        .expect("rollback");
}

#[tokio::test]
async fn null_predecessor_cannot_bypass_monotonic_trigger() {
    assert!(include_str!("compaction_schema_hardening.sql").contains(
        "NEW.predecessor_checkpoint_digest IS NOT OLD.checkpoint_digest"
    ));
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
