//! Exercise the original non-empty journal's additive schema migration.
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use tempfile::tempdir;

#[tokio::test]
async fn retirement_migration_keeps_original_rows_foreign_keys_and_immutability()
-> Result<(), Box<dyn std::error::Error>> {
    // Exercise the same FULL-durable, foreign-key-enforcing SQLite shim used by
    // the production journal rather than bypassing the workspace connection policy.
    // The private temporary file keeps this test isolated and is retained through close.
    let temp = tempdir()?;
    let sqlite_home = AbsolutePathBuf::try_from(std::fs::canonicalize(temp.path())?)?;
    let database_path = temp.path().join("retirement_migration.sqlite");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&database_path)
        .await?;
    sqlx::raw_sql(include_str!("../migrations/0005_local_lease_outbox.sql"))
        .execute(&pool)
        .await?;
    for (sequence, event_id, kind) in [
        (1_i64, "original-admission", "admitted"),
        (2, "original-terminal", "reconcile_committed"),
    ] {
        sqlx::query("INSERT INTO cognitive_local_events VALUES ('original-lease', ?, ?, 'original-operation', '018f4f72-5f8f-7cc1-8f55-df9fb3aa2d17', 1, 'original-fence', ?, '{}', ?, ?, ?, 1)")
            .bind(sequence).bind(event_id).bind(kind).bind("a".repeat(64)).bind("b".repeat(64)).bind("c".repeat(64))
            .execute(&pool).await?;
    }
    sqlx::query("INSERT INTO cognitive_local_outbox VALUES ('original-lease', 1, 'original-outbox', 'original-admission', 'original-operation', '018f4f72-5f8f-7cc1-8f55-df9fb3aa2d17', 1, 'original-fence', 'trill.notes.replace.v1', '{}', ?, ?, ?, 'queued', 1)")
        .bind("a".repeat(64)).bind("b".repeat(64)).bind("c".repeat(64)).execute(&pool).await?;
    let original: Vec<(String, String, String, String)> = sqlx::query_as("SELECT event_id, event_kind, payload_json, event_sha256 FROM cognitive_local_events ORDER BY event_sequence")
        .fetch_all(&pool).await?;
    let mut transaction = pool.begin().await?;
    sqlx::raw_sql(include_str!(
        "../migrations/0018_application_retirement_ack.sql"
    ))
    .execute(&mut *transaction)
    .await?;
    transaction.commit().await?;
    let retained: Vec<(String, String, String, String)> = sqlx::query_as("SELECT event_id, event_kind, payload_json, event_sha256 FROM cognitive_local_events ORDER BY event_sequence")
        .fetch_all(&pool).await?;
    assert_eq!(retained, original);
    assert_eq!(
        sqlx::query_scalar::<_, i64>("PRAGMA foreign_keys")
            .fetch_one(&pool)
            .await?,
        1
    );
    assert!(
        sqlx::query("PRAGMA foreign_key_check")
            .fetch_all(&pool)
            .await?
            .is_empty()
    );
    let retained_admission: String =
        sqlx::query_scalar("SELECT event_id FROM cognitive_local_outbox")
            .fetch_one(&pool)
            .await?;
    assert_eq!(retained_admission, "original-admission");
    assert!(
        sqlx::query("UPDATE cognitive_local_events SET payload_json = 'changed'")
            .execute(&pool)
            .await
            .is_err()
    );
    assert!(
        sqlx::query("DELETE FROM cognitive_local_events")
            .execute(&pool)
            .await
            .is_err()
    );
    sqlx::query("INSERT INTO cognitive_local_events VALUES ('original-lease', 3, 'original-ack', 'original-operation', '018f4f72-5f8f-7cc1-8f55-df9fb3aa2d17', 1, 'original-fence', 'retirement_acknowledged', '{}', ?, ?, ?, 1)")
        .bind("a".repeat(64)).bind("c".repeat(64)).bind("d".repeat(64)).execute(&pool).await?;
    assert!(sqlx::query("INSERT INTO cognitive_local_outbox VALUES ('original-lease', 2, 'foreign-outbox', 'absent-admission', 'foreign-operation', '018f4f72-5f8f-7cc1-8f55-df9fb3aa2d17', 1, 'original-fence', 'trill.notes.replace.v1', '{}', ?, ?, ?, 'queued', 1)")
        .bind("a".repeat(64)).bind("b".repeat(64)).bind("c".repeat(64)).execute(&pool).await.is_err());
    pool.close().await;
    Ok(())
}
