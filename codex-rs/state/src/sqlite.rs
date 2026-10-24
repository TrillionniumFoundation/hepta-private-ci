//! State-runtime migration and telemetry over the shared original SQLite owner.
//! All public connection and physical recovery operations live in codex-sqlite.

use crate::DbTelemetry;
use crate::migrations::repair_legacy_recency_migration_version;
use crate::runtime::RuntimeDbInitError;
use crate::telemetry;
use crate::telemetry::DbKind;
use sqlx::SqlitePool;
use sqlx::migrate::Migrator;
use std::path::PathBuf;
use std::time::Instant;

pub use codex_sqlite::RuntimeDbPath;
pub use codex_sqlite::SqliteConfig;

#[derive(Clone, Copy)]
struct RuntimeDbSpec {
    label: &'static str,
    path: fn(&SqliteConfig) -> PathBuf,
    kind: DbKind,
    open_phase: &'static str,
    migrate_phase: &'static str,
}

const STATE_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "state DB",
    path: SqliteConfig::state_db_path,
    kind: DbKind::State,
    open_phase: "open_state",
    migrate_phase: "migrate_state",
};

const LOGS_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "log DB",
    path: SqliteConfig::logs_db_path,
    kind: DbKind::Logs,
    open_phase: "open_logs",
    migrate_phase: "migrate_logs",
};

const GOALS_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "goals DB",
    path: SqliteConfig::goals_db_path,
    kind: DbKind::Goals,
    open_phase: "open_goals",
    migrate_phase: "migrate_goals",
};

const MEMORIES_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "memories DB",
    path: SqliteConfig::memories_db_path,
    kind: DbKind::Memories,
    open_phase: "open_memories",
    migrate_phase: "migrate_memories",
};

const QUEUE_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "queue DB",
    path: SqliteConfig::queue_db_path,
    kind: DbKind::Queue,
    open_phase: "open_queue",
    migrate_phase: "migrate_queue",
};

const THREAD_HISTORY_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "thread history DB",
    path: SqliteConfig::thread_history_db_path,
    kind: DbKind::ThreadHistory,
    open_phase: "open_thread_history",
    migrate_phase: "migrate_thread_history",
};

pub(crate) trait RuntimeSqliteConfigExt {
    async fn open_state_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool>;

    async fn open_logs_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool>;

    async fn open_goals_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool>;

    async fn open_memories_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool>;

    async fn open_queue_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool>;

    async fn open_thread_history_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool>;
}

impl RuntimeSqliteConfigExt for SqliteConfig {
    async fn open_state_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        // New state DBs should use incremental auto-vacuum, but retrofitting an
        // existing DB requires a full VACUUM. Do not attempt that during process
        // startup: it is maintenance work that can contend with foreground writers.
        open_runtime_db(self, STATE_DB, migrator, telemetry_override).await
    }

    async fn open_logs_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        open_runtime_db(self, LOGS_DB, migrator, telemetry_override).await
    }

    async fn open_goals_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        open_runtime_db(self, GOALS_DB, migrator, telemetry_override).await
    }

    async fn open_memories_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        open_runtime_db(self, MEMORIES_DB, migrator, telemetry_override).await
    }

    async fn open_queue_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        open_runtime_db(self, QUEUE_DB, migrator, telemetry_override).await
    }

    async fn open_thread_history_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        open_runtime_db(self, THREAD_HISTORY_DB, migrator, telemetry_override).await
    }
}

async fn open_runtime_db(
    config: &SqliteConfig,
    spec: RuntimeDbSpec,
    migrator: &Migrator,
    telemetry_override: Option<&dyn DbTelemetry>,
) -> anyhow::Result<SqlitePool> {
    let path = (spec.path)(config);
    let started = Instant::now();
    let pool_result = config
        .open_read_write_pool(&path)
        .await
        .map_err(anyhow::Error::from);
    telemetry::record_init_result(
        telemetry_override,
        spec.kind,
        spec.open_phase,
        started.elapsed(),
        &pool_result,
    );
    let pool = pool_result
        .map_err(|source| RuntimeDbInitError::new(spec.label, "open", path.as_path(), source))?;
    let started = Instant::now();
    let migrate_result = async {
        if matches!(spec.kind, DbKind::State) {
            repair_legacy_recency_migration_version(&pool, migrator).await?;
        }
        migrator.run(&pool).await.map_err(anyhow::Error::from)
    }
    .await;
    telemetry::record_init_result(
        telemetry_override,
        spec.kind,
        spec.migrate_phase,
        started.elapsed(),
        &migrate_result,
    );
    if let Err(source) = migrate_result {
        pool.close().await;
        return Err(RuntimeDbInitError::new(spec.label, "migrate", path.as_path(), source).into());
    }
    Ok(pool)
}
