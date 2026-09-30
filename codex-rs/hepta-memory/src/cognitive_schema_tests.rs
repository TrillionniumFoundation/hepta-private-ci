//! Independently derive the schema from compiled migrations, never owner bytes.
use std::error::Error;

use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use super::*;

#[tokio::test]
async fn compiled_migrations_match_schema_oracle_and_weakened_trigger_is_rejected()
-> Result<(), Box<dyn Error>> {
    let temp = TempDir::new()?;
    let sqlite_home = AbsolutePathBuf::try_from(temp.path().canonicalize()?)?;
    let path = sqlite_home.as_path().join("schema-oracle.sqlite3");
    let pool = SqliteConfig::new_for_testing(sqlite_home)
        .open_durable_evidence_pool(&path)
        .await?;
    MIGRATOR.run(&pool).await?;
    // Recovery and startup share one canonical schema inventory. A migration
    // adding a logical table must bind its contents, not silently ignore it.
    let actual: Vec<String> = sqlx::query_scalar(
        "SELECT name FROM pragma_table_list WHERE schema = 'main' AND type IN ('table', 'virtual') AND name NOT LIKE 'sqlite_%' ORDER BY name",
    )
    .fetch_all(&pool)
    .await?;
    let mut expected: Vec<String> = REQUIRED_SCHEMA_OBJECTS
        .iter()
        .filter(|&(_, kind)| *kind == "table")
        .map(|(name, _)| (*name).to_owned())
        .collect();
    expected.push("_sqlx_migrations".to_owned());
    expected.sort();
    assert_eq!(actual, expected);
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    sqlx::query(
        "INSERT INTO cognitive_meta (singleton, schema_version, owner_agent_id) VALUES (1, ?, ?)",
    )
    .bind(i64::from(COGNITIVE_SCHEMA_VERSION))
    .bind(owner.as_str())
    .execute(&pool)
    .await?;
    verify_store(&pool, &owner).await?;
    sqlx::raw_sql("DROP TRIGGER source_ledger_no_update; CREATE TRIGGER source_ledger_no_update BEFORE UPDATE ON source_ledger WHEN 0 BEGIN SELECT RAISE(ABORT, 'disabled guard'); END;")
        .execute(&pool)
        .await?;
    assert!(
        matches!(verify_store(&pool, &owner).await, Err(CognitiveStoreError::Corrupt(message)) if message.contains("schema definition oracle mismatch"))
    );
    pool.close().await;
    Ok(())
}
