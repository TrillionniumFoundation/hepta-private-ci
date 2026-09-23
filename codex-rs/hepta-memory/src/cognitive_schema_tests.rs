//! Independently derive the schema from compiled migrations, never owner bytes.
use sqlx::sqlite::SqlitePoolOptions;

use super::*;

#[tokio::test]
async fn compiled_migrations_match_schema_oracle_and_weakened_trigger_is_rejected() {
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect("sqlite::memory:")
        .await
        .expect("reference SQLite");
    MIGRATOR.run(&pool).await.expect("compiled migration chain");
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner");
    sqlx::query("INSERT INTO cognitive_meta (singleton, schema_version, owner_agent_id) VALUES (1, ?, ?)")
        .bind(i64::from(COGNITIVE_SCHEMA_VERSION))
        .bind(owner.as_str())
        .execute(&pool).await.expect("owner metadata");
    verify_store(&pool, &owner).await.expect("compiled schema must open");
    sqlx::raw_sql("DROP TRIGGER source_ledger_no_update; CREATE TRIGGER source_ledger_no_update BEFORE UPDATE ON source_ledger WHEN 0 BEGIN SELECT RAISE(ABORT, 'disabled guard'); END;")
        .execute(&pool).await.expect("tamper reference trigger");
    assert!(matches!(verify_store(&pool, &owner).await, Err(CognitiveStoreError::Corrupt(message)) if message.contains("schema definition oracle mismatch")));
    pool.close().await;
}
