//! Independently derive the schema from compiled migrations, never owner bytes.
use codex_state::open_in_memory_sqlite_pool;

use super::*;

#[tokio::test]
async fn compiled_migrations_match_schema_oracle_and_weakened_trigger_is_rejected() {
    let pool = open_in_memory_sqlite_pool(1)
        .await
        .expect("reference SQLite");
    MIGRATOR.run(&pool).await.expect("compiled migration chain");
    // Recovery and startup share one canonical schema inventory. A migration
    // adding a logical table must bind its contents, not silently ignore it.
    let actual: Vec<String> = sqlx::query_scalar(
        "SELECT name FROM pragma_table_list WHERE schema = 'main' AND type IN ('table', 'virtual') AND name NOT LIKE 'sqlite_%' ORDER BY name",
    ).fetch_all(&pool).await.expect("canonical table inventory");
    let mut expected: Vec<String> = REQUIRED_SCHEMA_OBJECTS
        .iter()
        .filter(|&(_, kind)| *kind == "table")
        .map(|(name, _)| (*name).to_owned())
        .collect();
    expected.push("_sqlx_migrations".to_owned());
    expected.sort();
    assert_eq!(actual, expected);
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner");
    sqlx::query(
        "INSERT INTO cognitive_meta (singleton, schema_version, owner_agent_id) VALUES (1, ?, ?)",
    )
    .bind(i64::from(COGNITIVE_SCHEMA_VERSION))
    .bind(owner.as_str())
    .execute(&pool)
    .await
    .expect("owner metadata");
    verify_store(&pool, &owner)
        .await
        .expect("compiled schema must open");
    sqlx::raw_sql("DROP TRIGGER source_ledger_no_update; CREATE TRIGGER source_ledger_no_update BEFORE UPDATE ON source_ledger WHEN 0 BEGIN SELECT RAISE(ABORT, 'disabled guard'); END;")
        .execute(&pool).await.expect("tamper reference trigger");
    assert!(
        matches!(verify_store(&pool, &owner).await, Err(CognitiveStoreError::Corrupt(message)) if message.contains("schema definition oracle mismatch"))
    );
    pool.close().await;
}
