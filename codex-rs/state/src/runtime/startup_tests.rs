use super::StateRuntime;
use super::finish_independent_pool_initialization;
use super::test_support::create_private_test_directory;
use super::test_support::unique_temp_dir;
use crate::DB_INIT_METRIC;
use crate::DbTelemetry;
use crate::SqliteConfig;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Notify;

#[derive(Default)]
struct QueueMigrationWitness {
    ready: Notify,
}

impl DbTelemetry for QueueMigrationWitness {
    fn counter(&self, name: &str, _inc: i64, tags: &[(&str, &str)]) {
        if name == DB_INIT_METRIC
            && tags.contains(&("phase", "migrate_queue"))
            && tags.contains(&("status", "success"))
        {
            self.ready.notify_one();
        }
    }

    fn record_duration(&self, _name: &str, _duration: Duration, _tags: &[(&str, &str)]) {}
}

#[tokio::test]
async fn initialization_migrates_independent_databases_while_logs_is_busy() {
    let home = unique_temp_dir();
    let sqlite = SqliteConfig::new_for_testing(home.as_path().abs());
    let runtime = StateRuntime::init(sqlite.clone(), "startup-test".to_string())
        .await
        .expect("initialize original databases");
    runtime.close().await;
    let held_pool = sqlite
        .open_read_write_pool(&sqlite.logs_db_path())
        .await
        .expect("open logs lock owner");
    let mut held = held_pool.acquire().await.expect("logs lock connection");
    sqlx::query("BEGIN EXCLUSIVE")
        .execute(&mut *held)
        .await
        .expect("hold real SQLite migration lock");
    let witness = Arc::new(QueueMigrationWitness::default());
    let worker_witness = Arc::clone(&witness);
    let initializing = tokio::spawn(async move {
        StateRuntime::init_with_telemetry_for_tests(
            sqlite,
            "startup-test".to_string(),
            worker_witness.as_ref(),
        )
        .await
    });
    // This is a dependency barrier, not a startup benchmark: queue migration
    // must make progress while logs remains locked, before releasing that lock.
    let independent_progress =
        tokio::time::timeout(Duration::from_secs(2), witness.ready.notified())
            .await
            .is_ok();
    let prematurely_published = initializing.is_finished();
    sqlx::query("ROLLBACK")
        .execute(&mut *held)
        .await
        .expect("release owned logs lock");
    drop(held);
    let runtime = initializing
        .await
        .expect("initialization task")
        .expect("initialize after releasing logs lock");
    runtime.close().await;
    held_pool.close().await;
    tokio::fs::remove_dir_all(home)
        .await
        .expect("remove owned home");
    assert!(
        independent_progress,
        "queue migration waited behind unrelated logs lock"
    );
    assert!(
        !prematurely_published,
        "runtime was published before logs migration completed"
    );
}

#[tokio::test]
async fn initialization_failure_closes_all_owned_pools_and_keeps_error_priority() {
    for failed in [vec![0], vec![1], vec![2], vec![3], vec![0, 2], vec![1, 3]] {
        let home = unique_temp_dir();
        create_private_test_directory(&home).expect("private home");
        let sqlite = SqliteConfig::new_for_testing(home.as_path().abs());
        let state = sqlite
            .open_read_write_pool(&sqlite.state_db_path())
            .await
            .expect("state pool");
        let mut retained = Vec::new();
        let mut independent = Vec::new();
        for (index, path) in [
            sqlite.logs_db_path(),
            sqlite.goals_db_path(),
            sqlite.memories_db_path(),
            sqlite.queue_db_path(),
        ]
        .into_iter()
        .enumerate()
        {
            if failed.contains(&index) {
                independent.push(Err(anyhow::anyhow!("database {index} failed")));
            } else {
                let pool = sqlite
                    .open_read_write_pool(&path)
                    .await
                    .expect("real successful pool");
                retained.push(pool.clone());
                independent.push(Ok(pool));
            }
        }
        let independent = independent.try_into().expect("four independent results");
        let error = finish_independent_pool_initialization(&state, independent)
            .await
            .expect_err("failed initialization");
        assert_eq!(error.to_string(), format!("database {} failed", failed[0]));
        assert!(state.is_closed());
        retained.push(state);
        for pool in retained {
            assert!(
                pool.is_closed(),
                "successful owned pool remained open after error"
            );
            assert!(matches!(pool.acquire().await, Err(sqlx::Error::PoolClosed)));
        }
        tokio::fs::remove_dir_all(home)
            .await
            .expect("remove private home");
    }
}

#[tokio::test]
async fn primary_state_failure_never_starts_the_other_databases() {
    let home = unique_temp_dir();
    create_private_test_directory(&home).expect("private home");
    let sqlite = SqliteConfig::new_for_testing(home.as_path().abs());
    tokio::fs::write(sqlite.state_db_path(), b"not a sqlite database")
        .await
        .expect("corrupt primary fixture");
    let result = StateRuntime::init(sqlite.clone(), "startup-test".to_string()).await;
    assert!(result.is_err());
    for path in [
        sqlite.logs_db_path(),
        sqlite.goals_db_path(),
        sqlite.memories_db_path(),
        sqlite.queue_db_path(),
    ] {
        assert!(
            !path.exists(),
            "later database started after primary failure: {}",
            path.display()
        );
    }
    tokio::fs::remove_dir_all(home)
        .await
        .expect("remove private home");
}

#[cfg(unix)]
#[tokio::test]
async fn unsafe_shared_home_is_rejected_before_any_database_is_created() {
    use std::os::unix::fs::PermissionsExt;
    let home = unique_temp_dir();
    create_private_test_directory(&home).expect("private home");
    std::fs::set_permissions(&home, std::fs::Permissions::from_mode(0o770))
        .expect("shared fixture");
    let sqlite = SqliteConfig::new_for_testing(home.as_path().abs());
    assert!(
        StateRuntime::init(sqlite, "startup-test".to_string())
            .await
            .is_err()
    );
    assert_eq!(
        std::fs::read_dir(&home)
            .expect("unchanged shared fixture")
            .count(),
        0
    );
    assert_eq!(
        std::fs::metadata(&home)
            .expect("home metadata")
            .permissions()
            .mode()
            & 0o777,
        0o770
    );
    tokio::fs::remove_dir_all(home)
        .await
        .expect("remove fixture home");
}

#[tokio::test]
async fn multiple_corrupt_databases_keep_original_error_and_publish_no_runtime() {
    let home = unique_temp_dir();
    create_private_test_directory(&home).expect("private home");
    let sqlite = SqliteConfig::new_for_testing(home.as_path().abs());
    for path in [sqlite.logs_db_path(), sqlite.memories_db_path()] {
        tokio::fs::write(path, b"not a sqlite database")
            .await
            .expect("corrupt independent fixture");
    }
    let error = StateRuntime::init(sqlite.clone(), "startup-test".to_string())
        .await
        .err()
        .expect("no partial runtime");
    assert_eq!(
        crate::runtime_db_path_for_corruption_error(&error),
        Some(sqlite.logs_db_path())
    );
    // Unlike the former short-circuit sequence, successful independent schemas
    // can persist on failure. This is intentionally not a cross-database rollback.
    for (path, table) in [
        (sqlite.goals_db_path(), "thread_goals"),
        (sqlite.queue_db_path(), "queued_items"),
    ] {
        assert!(
            path.exists(),
            "successful independent schema was not awaited"
        );
        let pool = sqlite
            .open_read_write_pool(&path)
            .await
            .expect("reopen completed schema");
        let table_exists: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
        )
        .bind(table)
        .fetch_one(&pool)
        .await
        .expect("inspect actual schema");
        assert_eq!(table_exists, 1);
        pool.close().await;
    }
    tokio::fs::remove_dir_all(home)
        .await
        .expect("remove private home");
}
