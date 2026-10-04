//! Independently derive the schema from compiled migrations, never owner bytes.
use std::time::Duration;

use tempfile::TempDir;

use super::*;

#[tokio::test]
async fn compiled_migrations_match_schema_oracle_and_weakened_trigger_is_rejected() {
    let fixture = TempDir::new().expect("reference fixture identity");
    let name = fixture
        .path()
        .file_name()
        .and_then(|name| name.to_str())
        .expect("temporary fixture name");
    // The shim permits multiple connections. A unique named-memory database
    // preserves one private schema oracle across them without creating a file.
    let memory = format!("file:hepta-cognitive-schema-{name}?mode=memory&cache=shared");
    let pool = SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::try_from(fixture.path().to_path_buf()).expect("absolute fixture root"),
    )
    .open_durable_evidence_pool(Path::new(&memory))
    .await
    .expect("reference SQLite");
    MIGRATOR.run(&pool).await.expect("compiled migration chain");
    let mut first = pool.acquire().await.expect("first physical connection");
    let mut peer = tokio::time::timeout(Duration::from_secs(5), pool.acquire())
        .await
        .expect("second connection deadline")
        .expect("second physical connection");
    let compiled_history: Vec<(i64, Vec<u8>)> = MIGRATOR
        .iter()
        .map(|migration| (migration.version, migration.checksum.to_vec()))
        .collect();
    for connection in [&mut first, &mut peer] {
        let filename: String =
            sqlx::query_scalar("SELECT file FROM pragma_database_list WHERE name = 'main'")
                .fetch_one(&mut **connection)
                .await
                .expect("physical database location");
        assert_eq!(filename, "", "schema oracle must remain in memory");
        let history: Vec<(i64, Vec<u8>)> =
            sqlx::query_as("SELECT version, checksum FROM _sqlx_migrations ORDER BY version")
                .fetch_all(&mut **connection)
                .await
                .expect("shared compiled migration history");
        assert_eq!(history, compiled_history);
    }
    drop(first);
    drop(peer);
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
