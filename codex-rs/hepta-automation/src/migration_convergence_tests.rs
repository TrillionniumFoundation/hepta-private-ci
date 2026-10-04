use sqlx::migrate::Migrate;
use sqlx::sqlite::SqlitePoolOptions;

use super::*;

async fn historical_pool(displaced: bool) -> SqlitePool {
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect("sqlite::memory:")
        .await
        .expect("SQLite owner");
    let mut connection = pool.acquire().await.expect("owner connection");
    connection
        .ensure_migrations_table("_sqlx_migrations")
        .await
        .expect("migration journal");
    for version in 1..=3 {
        let migration = MIGRATOR
            .iter()
            .find(|migration| migration.version == version)
            .expect("base migration");
        connection
            .apply("_sqlx_migrations", migration)
            .await
            .expect("base schema");
    }
    sqlx::query(
        "INSERT INTO automation_meta VALUES (1, 3, '018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12')",
    )
    .execute(&mut *connection)
    .await
    .expect("historical owner");
    for (version, source) in [
        (4, if displaced { 17 } else { 4 }),
        (5, if displaced { 18 } else { 5 }),
    ] {
        let mut migration = MIGRATOR
            .iter()
            .find(|migration| migration.version == source)
            .expect("original SQL")
            .clone();
        migration.version = version;
        connection
            .apply("_sqlx_migrations", &migration)
            .await
            .expect("historical branch migration");
    }
    drop(connection);
    pool
}

#[tokio::test]
async fn both_historical_branches_converge_without_rewriting_checksums() {
    for displaced in [false, true] {
        let pool = historical_pool(displaced).await;
        let before: Vec<Vec<u8>> =
            sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
                .fetch_all(&pool)
                .await
                .expect("original identities");
        reconcile_legacy_migration_ids(&pool)
            .await
            .expect("explicit remapping");
        // A crash at this cut leaves a complete, re-runnable identity transaction.
        reconcile_legacy_migration_ids(&pool)
            .await
            .expect("idempotent reopen");
        MIGRATOR
            .run(&pool)
            .await
            .expect("complete canonical schema");
        let after: Vec<Vec<u8>> =
            sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
                .fetch_all(&pool)
                .await
                .expect("retained checksums");
        assert!(before.iter().all(|checksum| after.contains(checksum)));
        assert_eq!(after.len(), MIGRATOR.iter().count());
        let schema: i64 = sqlx::query_scalar("SELECT schema_version FROM automation_meta")
            .fetch_one(&pool)
            .await
            .expect("schema");
        assert_eq!(schema, i64::from(AUTOMATION_SCHEMA_VERSION));
        for table in [
            "automation_schedule_metadata",
            "automation_occurrence_lifecycle",
            "destination_operation_dedupe",
            "automation_timer_lifecycle",
        ] {
            let count: i64 = sqlx::query_scalar(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
            )
            .bind(table)
            .fetch_one(&pool)
            .await
            .expect("schema inventory");
            assert_eq!(count, 1, "missing {table}");
        }
        pool.close().await;
    }
}

#[tokio::test]
async fn unknown_or_dirty_history_is_not_relabelled() {
    for mutation in [
        "UPDATE _sqlx_migrations SET checksum = x'00' WHERE version=4",
        "UPDATE _sqlx_migrations SET success=0 WHERE version=5",
    ] {
        let pool = historical_pool(true).await;
        sqlx::query(mutation)
            .execute(&pool)
            .await
            .expect("fault injection");
        assert!(matches!(
            reconcile_legacy_migration_ids(&pool).await,
            Err(AutomationError::Corrupt)
        ));
        let versions: Vec<i64> =
            sqlx::query_scalar("SELECT version FROM _sqlx_migrations ORDER BY version")
                .fetch_all(&pool)
                .await
                .expect("unchanged identities");
        assert_eq!(versions, vec![1, 2, 3, 4, 5]);
        pool.close().await;
    }
}

async fn reopen_persisted_history(displaced: bool, after_rebind: bool) {
    let temp = tempfile::tempdir().expect("private owner root");
    let root = temp.path().join("owner");
    std::fs::create_dir(&root).expect("owner directory");
    let root = root.canonicalize().expect("canonical owner directory");
    let pool = historical_pool(displaced).await;
    let before: Vec<Vec<u8>> =
        sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool)
            .await
            .expect("original history");
    if after_rebind {
        reconcile_legacy_migration_ids(&pool)
            .await
            .expect("bounded repair");
    }
    // Reopen exactly the persisted cut before or after the repair transaction,
    // before later migrations: no live connection supplies hidden state.
    sqlx::query("VACUUM INTO ?")
        .bind(root.join(AUTOMATION_DB_FILENAME).to_str().expect("path"))
        .execute(&pool)
        .await
        .expect("persist historical cut");
    pool.close().await;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner ID");
    let store = AutomationStore::open_root(root.clone(), owner.clone())
        .await
        .expect("real open");
    let after: Vec<Vec<u8>> =
        sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&store.pool)
            .await
            .expect("retained history");
    assert!(before.iter().all(|checksum| after.contains(checksum)));
    assert_eq!(after.len(), MIGRATOR.iter().count());
    store.close().await;
    let reopened = AutomationStore::open_root(root, owner)
        .await
        .expect("idempotent restart");
    assert!(reopened.timer_epoch() > 0);
    reopened.close().await;
}

// Independent on-disk histories retain the default per-test watchdog and all
// checksum/restart assertions; one case cannot consume another case's budget.
#[tokio::test]
async fn canonical_cut_before_rebind_reopens() {
    reopen_persisted_history(false, false).await;
}

#[tokio::test]
async fn canonical_cut_after_rebind_reopens() {
    reopen_persisted_history(false, true).await;
}

#[tokio::test]
async fn displaced_cut_before_rebind_reopens() {
    reopen_persisted_history(true, false).await;
}

#[tokio::test]
async fn displaced_cut_after_rebind_reopens() {
    reopen_persisted_history(true, true).await;
}

#[tokio::test]
async fn occupied_relocation_rolls_back_all_history_rebinding() {
    let pool = historical_pool(/*displaced*/ true).await;
    sqlx::query("INSERT INTO _sqlx_migrations(version,description,installed_on,success,checksum,execution_time) SELECT 17,description,installed_on,success,checksum,execution_time FROM _sqlx_migrations WHERE version=4")
        .execute(&pool).await.expect("inject conflicting target identity");
    let before: Vec<(i64, Vec<u8>)> =
        sqlx::query_as("SELECT version,checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool)
            .await
            .expect("before repair");
    assert!(reconcile_legacy_migration_ids(&pool).await.is_err());
    let after: Vec<(i64, Vec<u8>)> =
        sqlx::query_as("SELECT version,checksum FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool)
            .await
            .expect("after rollback");
    assert_eq!(before, after);
    pool.close().await;
}

const MIGRATION_CRASH_ROOT: &str = "HEPTA_AUTOMATION_MIGRATION_CRASH_ROOT";
const MIGRATION_CRASH_CUT: &str = "HEPTA_AUTOMATION_MIGRATION_CRASH_CUT";
const RETAINED_TASK: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c30";

#[tokio::test]
async fn migration_crash_worker() {
    let Some(root) = std::env::var_os(MIGRATION_CRASH_ROOT) else {
        return;
    };
    let root = std::path::PathBuf::from(root);
    let cut: i64 = std::env::var(MIGRATION_CRASH_CUT)
        .expect("cut")
        .parse()
        .expect("version");
    let path = root.join(AUTOMATION_DB_FILENAME);
    let options = sqlx::sqlite::SqliteConnectOptions::new()
        .filename(&path)
        .create_if_missing(true);
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(options)
        .await
        .expect("historical on-disk owner");
    let mut connection = pool.acquire().await.expect("historical connection");
    connection
        .ensure_migrations_table("_sqlx_migrations")
        .await
        .expect("migration table");
    for migration in MIGRATOR.iter().filter(|migration| migration.version <= 3) {
        connection
            .apply("_sqlx_migrations", migration)
            .await
            .expect("historical schema");
    }
    drop(connection);
    sqlx::query(
        "INSERT INTO automation_meta VALUES (1, 3, '018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12')",
    )
    .execute(&pool)
    .await
    .expect("historical owner identity");
    sqlx::query("INSERT INTO automation_tasks(task_id, owner_agent_id, thread_id, prompt, schedule_kind, state, next_occurrence, created_at_ms, updated_at_ms) VALUES (?, '018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12', 'retained-thread', 'retained-cancelled-task', 'once', 'cancelled', 2, 10, 20)")
        .bind(RETAINED_TASK).execute(&pool).await.expect("committed historical task");
    sqlx::query("INSERT INTO automation_runs(task_id, occurrence, scheduled_for_ms, client_user_message_id, state) VALUES (?, 1, 15, 'retained-client-id', 'cancelled')")
        .bind(RETAINED_TASK).execute(&pool).await.expect("committed historical occurrence");
    let mut connection = pool.acquire().await.expect("migration connection");
    // Use the actual SQLx migration transaction/checksum implementation used by
    // the product opener. Crash after each possible committed migration prefix.
    for migration in MIGRATOR
        .iter()
        .filter(|migration| migration.version > 3 && migration.version <= cut)
    {
        connection
            .apply("_sqlx_migrations", migration)
            .await
            .expect("committed migration");
    }
    std::process::exit(37);
}

#[tokio::test]
async fn every_committed_migration_prefix_recovers_retained_history_after_process_loss() {
    for cut in MIGRATOR
        .iter()
        .filter(|migration| migration.version >= 3)
        .map(|migration| migration.version)
    {
        let temp = tempfile::tempdir().expect("private migration root");
        let stdout = temp.path().join("migration.stdout");
        let stderr = temp.path().join("migration.stderr");
        let mut child =
            std::process::Command::new(std::env::current_exe().expect("test executable"))
                .args([
                    "--exact",
                    "store::migration_convergence_tests::migration_crash_worker",
                    "--nocapture",
                ])
                .env(MIGRATION_CRASH_ROOT, temp.path())
                .env(MIGRATION_CRASH_CUT, cut.to_string())
                .stdout(std::fs::File::create(&stdout).expect("child stdout"))
                .stderr(std::fs::File::create(&stderr).expect("child stderr"))
                .spawn()
                .expect("migration process");
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
        let status = loop {
            if let Some(status) = child.try_wait().expect("observe owned migration process") {
                break status;
            }
            if std::time::Instant::now() >= deadline {
                // The child can exit between try_wait and kill. Reap it even
                // if kill reports that race instead of panicking beforehand.
                let killed = child.kill();
                let reaped = child.wait();
                panic!(
                    "migration process exceeded its 10-second budget at cut {cut}: \
                     kill={killed:?}, reap={reaped:?}"
                );
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        };
        assert_eq!(
            status.code(),
            Some(37),
            "cut {cut}: {} {}",
            std::fs::read_to_string(stdout).expect("child stdout"),
            std::fs::read_to_string(stderr).expect("child stderr")
        );
        let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("owner");
        let store = AutomationStore::open_root(temp.path().to_path_buf(), owner)
            .await
            .expect("ordinary owner recovery");
        let task: (String, String, i64, i64, i64) = sqlx::query_as("SELECT prompt,state,next_occurrence,created_at_ms,updated_at_ms FROM automation_tasks WHERE task_id=?")
            .bind(RETAINED_TASK).fetch_one(&store.pool).await.expect("retained task");
        assert_eq!(
            task,
            (
                "retained-cancelled-task".to_owned(),
                "cancelled".to_owned(),
                2,
                10,
                20
            ),
            "cut {cut}"
        );
        let occurrence: (String, String, i64) = sqlx::query_as("SELECT client_user_message_id,state,scheduled_for_ms FROM automation_runs WHERE task_id=? AND occurrence=1")
            .bind(RETAINED_TASK).fetch_one(&store.pool).await.expect("retained occurrence");
        assert_eq!(
            occurrence,
            ("retained-client-id".to_owned(), "cancelled".to_owned(), 15),
            "cut {cut}"
        );
        let versions: Vec<i64> = sqlx::query_scalar(
            "SELECT version FROM _sqlx_migrations WHERE success=1 ORDER BY version",
        )
        .fetch_all(&store.pool)
        .await
        .expect("complete migration history");
        assert_eq!(
            versions,
            MIGRATOR
                .iter()
                .map(|migration| migration.version)
                .collect::<Vec<_>>()
        );
        store.close().await;
    }
}
