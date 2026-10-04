use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use sqlx::migrate::Migrate;

use super::*;

fn file_bundle(root: &std::path::Path) -> std::collections::BTreeMap<std::ffi::OsString, Vec<u8>> {
    std::fs::read_dir(root)
        .expect("owner file inventory")
        .map(|entry| {
            let entry = entry.expect("owner file");
            (
                entry.file_name(),
                std::fs::read(entry.path()).expect("owner bytes"),
            )
        })
        .collect()
}

fn fixture_config(root: &std::path::Path) -> SqliteConfig {
    SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::try_from(root.to_path_buf()).expect("absolute fixture root"),
    )
}

async fn assert_foreign_owner_preserves_database(branch: &str) {
    let directory = tempfile::tempdir().expect("isolated diagnostic owner");
    let root = directory
        .path()
        .canonicalize()
        .expect("canonical fixture root");
    let path = root.as_path().join(AUTOMATION_DB_FILENAME);
    let pool = fixture_config(root.as_path())
        .open_durable_evidence_pool(&path)
        .await
        .expect("historical owner");
    let mut connection = pool.acquire().await.expect("migration connection");
    connection
        .ensure_migrations_table("_sqlx_migrations")
        .await
        .expect("migration identities");
    for migration in MIGRATOR.iter().filter(|migration| migration.version <= 3) {
        connection
            .apply("_sqlx_migrations", migration)
            .await
            .expect("original schema");
    }
    sqlx::query(
        "INSERT INTO automation_meta VALUES (1, 3, '018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12')",
    )
    .execute(&mut *connection)
    .await
    .expect("original owner identity");
    sqlx::query("INSERT INTO automation_tasks(task_id, owner_agent_id, thread_id, prompt, schedule_kind, state, next_occurrence, created_at_ms, updated_at_ms) VALUES ('018f4f72-5f8f-7cc1-8f55-df9fb3aa2c30', '018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12', 'retained-thread', 'retained foreign owner', 'once', 'cancelled', 1, 10, 20)")
            .execute(&mut *connection).await.expect("original owner fact");
    if branch != "v3" {
        for (version, source) in [
            (4, if branch == "displaced-v5" { 17 } else { 4 }),
            (5, if branch == "displaced-v5" { 18 } else { 5 }),
        ] {
            let mut migration = MIGRATOR
                .iter()
                .find(|migration| migration.version == source)
                .expect("known historical SQL")
                .clone();
            migration.version = version;
            connection
                .apply("_sqlx_migrations", &migration)
                .await
                .expect("historical branch");
        }
    }
    let before_schema: i64 = sqlx::query_scalar("SELECT schema_version FROM automation_meta")
        .fetch_one(&mut *connection)
        .await
        .expect("before schema");
    let before_versions: Vec<(i64, String, String, Vec<u8>, bool, i64)> = sqlx::query_as("SELECT version,description,CAST(installed_on AS TEXT),checksum,success,execution_time FROM _sqlx_migrations ORDER BY version").fetch_all(&mut *connection).await.expect("before versions");
    drop(connection);
    pool.close().await;
    // The owned fixture models a historical DELETE-journal image. Any later
    // journal-mode byte changes must be reported, never mislabeled as no I/O.
    fixture_config(root.as_path())
        .checkpoint_private_recovery_database(&path)
        .await
        .expect("cold fixture checkpoint");
    let before_bytes = std::fs::read(&path).expect("before file bytes");
    let before_bundle = file_bundle(root.as_path());
    let wrong_owner =
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").expect("different owner");
    let result = AutomationStore::open_root(root.as_path().to_path_buf(), wrong_owner).await;
    assert!(
        matches!(result, Err(AutomationError::AccessDenied)),
        "foreign owner must remain rejected"
    );
    let after_bundle = file_bundle(root.as_path());
    eprintln!(
        "OWNER_PREFLIGHT branch={branch} incidental_file_bundle_changed={} before_files={:?} after_files={:?}",
        before_bundle != after_bundle,
        before_bundle.keys(),
        after_bundle.keys()
    );
    let observed = fixture_config(root.as_path())
        .open_read_only_pool(&path)
        .await
        .expect("read-only observation");
    let after: (i64, String) =
        sqlx::query_as("SELECT schema_version, owner_agent_id FROM automation_meta")
            .fetch_one(&observed)
            .await
            .expect("after schema and owner");
    let after_versions: Vec<(i64, String, String, Vec<u8>, bool, i64)> = sqlx::query_as("SELECT version,description,CAST(installed_on AS TEXT),checksum,success,execution_time FROM _sqlx_migrations ORDER BY version").fetch_all(&observed).await.expect("after versions");
    let facts: Vec<(String, String)> = sqlx::query_as("SELECT prompt,state FROM automation_tasks")
        .fetch_all(&observed)
        .await
        .expect("retained foreign facts");
    observed.close().await;
    let after_bytes = std::fs::read(&path).expect("after file bytes");
    assert_eq!(after.1, "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12");
    assert_eq!(
        facts,
        vec![("retained foreign owner".to_owned(), "cancelled".to_owned())]
    );
    assert_eq!(
        after.0, before_schema,
        "wrong-owner rejection migrated schema: {branch}"
    );
    assert_eq!(
        after_versions, before_versions,
        "wrong-owner rejection rewrote migration history: {branch}"
    );
    eprintln!(
        "OWNER_PREFLIGHT branch={branch} incidental_database_bytes_changed={}",
        before_bytes != after_bytes
    );
    // Force the final migration to fail after any historical remapping.
    // The outer owner transaction must undo every newly attempted change.
    let blocker = fixture_config(root.as_path())
        .open_durable_evidence_pool(&path)
        .await
        .expect("migration blocker fixture");
    sqlx::query("CREATE INDEX automation_tasks_listing_idx ON automation_tasks(task_id)")
        .execute(&blocker)
        .await
        .expect("late migration conflict");
    let original_owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner");
    assert!(matches!(
        AutomationStore::open_root(root.as_path().to_path_buf(), original_owner).await,
        Err(AutomationError::Unavailable)
    ));
    let rolled_back: Vec<(i64, String, String, Vec<u8>, bool, i64)> = sqlx::query_as("SELECT version,description,CAST(installed_on AS TEXT),checksum,success,execution_time FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&blocker).await.expect("rolled back history");
    assert_eq!(rolled_back, before_versions);
    let rolled_back_schema: i64 = sqlx::query_scalar("SELECT schema_version FROM automation_meta")
        .fetch_one(&blocker)
        .await
        .expect("rolled back schema");
    assert_eq!(rolled_back_schema, before_schema);
    sqlx::query("DROP INDEX automation_tasks_listing_idx")
        .execute(&blocker)
        .await
        .expect("remove fixture conflict");
    blocker.close().await;
    let accepted = AutomationStore::open_root(
        root.as_path().to_path_buf(),
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("original owner"),
    )
    .await
    .expect("matching legacy owner upgrades");
    let retained: Vec<(String, String)> =
        sqlx::query_as("SELECT prompt,state FROM automation_tasks")
            .fetch_all(&accepted.pool)
            .await
            .expect("upgraded retained facts");
    assert_eq!(retained, facts);
    accepted.close().await;
    let reopened = AutomationStore::open_root(
        root.as_path().to_path_buf(),
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("original owner"),
    )
    .await
    .expect("matching current owner reopens");
    reopened.close().await;
}

#[tokio::test]
async fn foreign_v3_owner_rejection_preserves_database() {
    assert_foreign_owner_preserves_database("v3").await;
}

#[tokio::test]
async fn foreign_canonical_v5_owner_rejection_preserves_database() {
    assert_foreign_owner_preserves_database("canonical-v5").await;
}

#[tokio::test]
async fn foreign_displaced_v5_owner_rejection_preserves_database() {
    assert_foreign_owner_preserves_database("displaced-v5").await;
}

#[tokio::test]
async fn wal_backed_owner_is_qualified_without_rejecting_live_reopens() {
    let directory = tempfile::tempdir().expect("owner root");
    let root = directory
        .path()
        .canonicalize()
        .expect("canonical fixture root");
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner");
    let store = AutomationStore::open_root(root.as_path().to_path_buf(), owner.clone())
        .await
        .expect("new owner");
    let path = root.as_path().join(AUTOMATION_DB_FILENAME);
    assert!(
        std::fs::metadata(format!("{}-wal", path.display()))
            .expect("live WAL")
            .len()
            > 0
    );
    // A separately copied main file has no metadata table: the committed
    // owner's schema and identity currently exist only in the live WAL.
    let cold = tempfile::tempdir().expect("independent main-only copy");
    let cold_path = cold.path().join("main-only.sqlite3");
    std::fs::copy(&path, &cold_path).expect("copy owned fixture main file");
    let cold_pool = fixture_config(cold.path())
        .open_read_only_pool(&cold_path)
        .await
        .expect("inspect main-only copy");
    let cold_meta: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM sqlite_master WHERE name='automation_meta'")
            .fetch_one(&cold_pool)
            .await
            .expect("main-only inventory");
    assert_eq!(cold_meta, 0);
    cold_pool.close().await;
    let before: Vec<(i64, Vec<u8>)> =
        sqlx::query_as("SELECT version,checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&store.pool)
            .await
            .expect("migration history");
    let wrong = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").expect("other owner");
    assert!(matches!(
        AutomationStore::open_root(root.as_path().to_path_buf(), wrong).await,
        Err(AutomationError::AccessDenied)
    ));
    let after: Vec<(i64, Vec<u8>)> =
        sqlx::query_as("SELECT version,checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&store.pool)
            .await
            .expect("unchanged migration history");
    assert_eq!(after, before);
    let second = AutomationStore::open_root(root.as_path().to_path_buf(), owner)
        .await
        .expect("live matching owner reopen");
    second.close().await;
    store.close().await;
}

#[tokio::test]
async fn unknown_owner_metadata_is_not_adopted_or_overwritten() {
    for metadata in [
        "",
        "CREATE TABLE automation_meta(singleton, schema_version, owner_agent_id)",
        "CREATE TABLE automation_meta(singleton, schema_version, owner_agent_id); INSERT INTO automation_meta VALUES(2,3,'018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12')",
        "CREATE TABLE automation_meta(singleton, schema_version, owner_agent_id); INSERT INTO automation_meta VALUES(1,'3','018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12')",
        "CREATE VIEW automation_meta AS SELECT 1 AS singleton, 3 AS schema_version, '018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12' AS owner_agent_id",
        "CREATE TABLE automation_meta(singleton, schema_version, owner_agent_id); INSERT INTO automation_meta VALUES(1,3,'bad-owner')",
        "CREATE TABLE automation_meta(singleton, schema_version, owner_agent_id); INSERT INTO automation_meta VALUES(1,17,'018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12')",
        "CREATE TABLE automation_meta(singleton, schema_version, owner_agent_id); INSERT INTO automation_meta VALUES(1,999,'018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12')",
        "CREATE TABLE automation_meta(singleton, schema_version, owner_agent_id); INSERT INTO automation_meta VALUES(1,3,NULL)",
        "CREATE TABLE automation_meta(singleton, schema_version, owner_agent_id); INSERT INTO automation_meta VALUES(1,3,'018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12'),(1,3,'018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12')",
    ] {
        let directory = tempfile::tempdir().expect("unowned root");
        let root = directory
            .path()
            .canonicalize()
            .expect("canonical fixture root");
        let path = root.as_path().join(AUTOMATION_DB_FILENAME);
        let pool = fixture_config(root.as_path())
            .open_durable_evidence_pool(&path)
            .await
            .expect("source fixture");
        sqlx::raw_sql(
            "CREATE TABLE sentinel(payload TEXT); INSERT INTO sentinel VALUES('must retain')",
        )
        .execute(&pool)
        .await
        .expect("unowned data");
        sqlx::raw_sql(metadata)
            .execute(&pool)
            .await
            .expect("malformed owner metadata");
        let before: Vec<(String, Option<String>)> =
            sqlx::query_as("SELECT name,sql FROM sqlite_master ORDER BY name")
                .fetch_all(&pool)
                .await
                .expect("schema inventory");
        pool.close().await;
        let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner");
        assert!(
            matches!(
                AutomationStore::open_root(root.as_path().to_path_buf(), owner).await,
                Err(AutomationError::Corrupt)
            ),
            "metadata: {metadata}"
        );
        let observed = fixture_config(root.as_path())
            .open_read_only_pool(&path)
            .await
            .expect("read-only observation");
        let after: Vec<(String, Option<String>)> =
            sqlx::query_as("SELECT name,sql FROM sqlite_master ORDER BY name")
                .fetch_all(&observed)
                .await
                .expect("unchanged schema inventory");
        assert_eq!(after, before);
        let facts: Vec<String> = sqlx::query_scalar("SELECT payload FROM sentinel")
            .fetch_all(&observed)
            .await
            .expect("retained data");
        assert_eq!(facts, vec!["must retain".to_owned()]);
        observed.close().await;
    }
}

#[tokio::test]
async fn fresh_and_empty_database_initialization_still_succeeds() {
    for existing_empty in [false, true] {
        let directory = tempfile::tempdir().expect("new root");
        let root = directory
            .path()
            .canonicalize()
            .expect("canonical fixture root");
        if existing_empty {
            std::fs::File::create(root.as_path().join(AUTOMATION_DB_FILENAME))
                .expect("empty database");
        }
        let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner");
        let store = AutomationStore::open_root(root.as_path().to_path_buf(), owner.clone())
            .await
            .expect("initialize owner");
        assert_eq!(store.owner_agent_id(), &owner);
        store.close().await;
    }
}

#[tokio::test]
async fn competing_fresh_owners_cannot_both_initialize() {
    let directory = tempfile::tempdir().expect("new owner root");
    let root = directory
        .path()
        .canonicalize()
        .expect("canonical fixture root");
    let first = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("first owner");
    let second = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").expect("second owner");
    let (first_result, second_result) = tokio::join!(
        AutomationStore::open_root(root.as_path().to_path_buf(), first.clone()),
        AutomationStore::open_root(root.as_path().to_path_buf(), second.clone()),
    );
    match (first_result, second_result) {
        (Ok(store), Err(AutomationError::AccessDenied))
        | (Err(AutomationError::AccessDenied), Ok(store)) => {
            store.close().await;
        }
        // Initial pool WAL configuration precedes the logical owner fence.
        // A simultaneous first open can fail there with a retriable busy error.
        (Ok(store), Err(AutomationError::Unavailable))
        | (Err(AutomationError::Unavailable), Ok(store)) => {
            let winner = store.owner_agent_id().clone();
            let loser = if winner == first { second } else { first };
            store.close().await;
            assert!(matches!(
                AutomationStore::open_root(root.as_path().to_path_buf(), loser).await,
                Err(AutomationError::AccessDenied)
            ));
            let reopened = AutomationStore::open_root(root.as_path().to_path_buf(), winner)
                .await
                .expect("winning owner persists");
            reopened.close().await;
        }
        _ => panic!("competing fresh initialization must admit exactly one owner"),
    }
}
