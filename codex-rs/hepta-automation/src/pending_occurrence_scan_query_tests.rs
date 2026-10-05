//! Exact production SQL work probes, separate from durable owner-integrity tests.
use super::*;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[tokio::test]
async fn physical_window_and_point_lookup_do_not_scan_the_retained_frontier() {
    let mut measured = Vec::new();
    for retained in [100_i64, 1_000, 10_000] {
        for state in ["running", "succeeded"] {
            let directory = tempfile::tempdir().expect("private query probe");
            let sqlite = SqliteConfig::from_sqlite_home(
                AbsolutePathBuf::try_from(directory.path().to_path_buf())
                    .expect("absolute probe root"),
            );
            let pool = sqlite
                .open_durable_evidence_pool(&directory.path().join("query-probe.sqlite3"))
                .await
                .expect("query probe through owner SQLite shim");
            let mut connection = pool.acquire().await.expect("probe connection");
            // Preserve actual PK/index shape and all columns used by the SQL.
            // No occurrence parsing is performed on these synthetic probe rows.
            sqlx::raw_sql("CREATE TABLE automation_tasks (task_id TEXT PRIMARY KEY, owner_agent_id TEXT, thread_id TEXT, prompt TEXT);
                CREATE TABLE automation_occurrence_lifecycle (task_id TEXT, occurrence INTEGER, owner_agent_id TEXT, state TEXT, recovery_phase TEXT, updated_at_ms INTEGER, PRIMARY KEY(task_id, occurrence));
                CREATE INDEX automation_occurrence_recovery_idx ON automation_occurrence_lifecycle(owner_agent_id, recovery_phase, updated_at_ms, task_id, occurrence);
                CREATE INDEX automation_occurrence_task_state_idx ON automation_occurrence_lifecycle(task_id, state, occurrence);")
                .execute(&mut *connection).await.expect("query schema");
            sqlx::query("WITH RECURSIVE seq(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM seq WHERE i < ?) INSERT INTO automation_tasks SELECT printf('task-%06d', i), 'owner', 'thread', 'prompt' FROM seq")
                .bind(retained).execute(&mut *connection).await.expect("retained tasks");
            sqlx::query("INSERT INTO automation_occurrence_lifecycle SELECT task_id, 1, owner_agent_id, ?, 'awaiting_terminal', 1 FROM automation_tasks")
                .bind(state).execute(&mut *connection).await.expect("retained metadata");
            let plan = sqlx::query(PENDING_OCCURRENCE_EXPLAIN_SQL)
                .bind(0_i64)
                .bind(retained)
                .fetch_all(&mut *connection)
                .await
                .expect("query plan");
            let details: Vec<String> = plan.iter().map(|row| row.get("detail")).collect();
            assert!(
                details
                    .iter()
                    .any(|line| line.contains("INTEGER PRIMARY KEY")),
                "{details:?}"
            );
            assert!(
                details.iter().all(|line| !line.contains("TEMP B-TREE")),
                "{details:?}"
            );
            let operations = Arc::new(AtomicUsize::new(0));
            let observed = Arc::clone(&operations);
            connection
                .lock_handle()
                .await
                .expect("SQLite handle")
                .set_progress_handler(
                    /*num_ops*/ 1,
                    move || observed.fetch_add(1, Ordering::SeqCst) < 8_192,
                );
            let (first_sql, last_sql) = RecoveryScanTable::Occurrences.endpoint_queries();
            let first: i64 = sqlx::query_scalar(first_sql)
                .fetch_one(&mut *connection)
                .await
                .expect("constant first endpoint");
            let last: i64 = sqlx::query_scalar(last_sql)
                .fetch_one(&mut *connection)
                .await
                .expect("constant last endpoint");
            assert_eq!(first, 1);
            assert_eq!(last, retained);
            let rows = sqlx::query(PENDING_OCCURRENCE_WINDOW_SQL)
                .bind(0_i64)
                .bind(last)
                .fetch_all(&mut *connection)
                .await
                .expect("bounded physical work before filtering");
            assert_eq!(rows.len(), 64);
            assert_eq!(rows.last().expect("window").get::<i64, _>("scan_rowid"), 64);
            let selected = sqlx::query(PENDING_OCCURRENCE_LOOKUP_SQL)
                .bind("task-000001")
                .bind(1_i64)
                .bind("owner")
                .fetch_optional(&mut *connection)
                .await
                .expect("unique point lookup");
            assert_eq!(selected.is_some(), state == "running");
            connection
                .lock_handle()
                .await
                .expect("handle")
                .set_progress_handler(/*num_ops*/ 0, || true);
            let count = operations.load(Ordering::SeqCst);
            assert!(count < 8_192, "unbounded work at {retained}: {count}");
            measured.push((state, retained, count));
            drop(connection);
            pool.close().await;
        }
    }
    for state in ["running", "succeeded"] {
        let counts: Vec<usize> = measured
            .iter()
            .filter(|entry| entry.0 == state)
            .map(|entry| entry.2)
            .collect();
        let low = *counts.iter().min().expect("measurements");
        let high = *counts.iter().max().expect("measurements");
        assert!(
            high - low <= 64,
            "frontier length must not grow scan work: {measured:?}"
        );
    }
}
