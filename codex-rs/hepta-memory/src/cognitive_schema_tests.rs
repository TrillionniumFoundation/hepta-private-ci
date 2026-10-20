//! Independently derive the schema from compiled migrations, never owner bytes.
use super::*;

async fn compiled_schema_reference() -> (tempfile::TempDir, SqlitePool, AgentId) {
    let directory = tempfile::tempdir().expect("reference SQLite directory");
    let sqlite_home =
        AbsolutePathBuf::try_from(directory.path().to_path_buf()).expect("absolute SQLite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&directory.path().join("schema.sqlite3"))
        .await
        .expect("reference SQLite");
    MIGRATOR.run(&pool).await.expect("compiled migration chain");
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner");
    sqlx::query(
        "INSERT INTO cognitive_meta (singleton, schema_version, owner_agent_id) VALUES (1, ?, ?)",
    )
    .bind(i64::from(COGNITIVE_SCHEMA_VERSION))
    .bind(owner.as_str())
    .execute(&pool)
    .await
    .expect("owner metadata");
    (directory, pool, owner)
}

#[tokio::test]
async fn compiled_migrations_match_schema_oracle_and_weakened_trigger_is_rejected() {
    let (_directory, pool, owner) = compiled_schema_reference().await;
    // Compare every logical object against the compiled typed inventory. A
    // source-text regex can silently omit multiline tuples with trailing commas.
    // SQLite-owned FTS shadow tables retain the existing table/virtual boundary.
    let actual: Vec<(String, String)> = sqlx::query_as(
        "SELECT objects.name, objects.type
         FROM sqlite_schema AS objects
         LEFT JOIN pragma_table_list AS tables
           ON tables.schema = 'main' AND tables.name = objects.name
         WHERE objects.name NOT LIKE 'sqlite_%' AND objects.sql IS NOT NULL
           AND (objects.type != 'table' OR tables.type IN ('table', 'virtual'))
         ORDER BY objects.name, objects.type",
    )
    .fetch_all(&pool)
    .await
    .expect("canonical typed schema inventory");
    let mut expected: Vec<(String, String)> = REQUIRED_SCHEMA_OBJECTS
        .iter()
        .map(|(name, kind)| ((*name).to_owned(), (*kind).to_owned()))
        .collect();
    expected.push(("_sqlx_migrations".to_owned(), "table".to_owned()));
    expected.sort();
    assert_eq!(actual, expected);
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

#[tokio::test]
async fn compiled_schema_oracle_rejects_weakened_destination_insert_guard() {
    let (_directory, pool, owner) = compiled_schema_reference().await;
    verify_store(&pool, &owner)
        .await
        .expect("compiled schema must open before tampering");
    sqlx::raw_sql(
        "DROP TRIGGER cognitive_operation_destination_terminal_no_reinsert;
         CREATE TRIGGER cognitive_operation_destination_terminal_no_reinsert
         BEFORE INSERT ON cognitive_operation_destination_terminal WHEN 0 BEGIN
             SELECT RAISE(ABORT, 'disabled guard');
         END;",
    )
    .execute(&pool)
    .await
    .expect("tamper destination insert guard");
    assert!(
        matches!(verify_store(&pool, &owner).await, Err(CognitiveStoreError::Corrupt(message)) if message.contains("schema definition oracle mismatch"))
    );
    pool.close().await;
}
