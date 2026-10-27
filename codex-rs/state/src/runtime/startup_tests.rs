use super::StateRuntime;
use super::test_support::unique_temp_dir;
use crate::DB_INIT_METRIC;
use crate::DbTelemetry;
use crate::SqliteConfig;
use codex_utils_absolute_path::test_support::PathExt;
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
