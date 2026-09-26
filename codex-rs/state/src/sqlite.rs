//! Shared SQLite connection configuration.

#![expect(
    clippy::disallowed_methods,
    reason = "this is the centralized SQLite connection shim"
)]

use crate::DbTelemetry;
use crate::migrations::repair_legacy_recency_migration_version;
use crate::runtime::RuntimeDbInitError;
use crate::telemetry;
use crate::telemetry::DbKind;
use codex_utils_absolute_path::AbsolutePathBuf;
use log::LevelFilter;
use sqlx::ConnectOptions;
use sqlx::Connection;
use sqlx::Error;
use sqlx::SqlitePool;
use sqlx::migrate::Migrator;
use sqlx::sqlite::SqliteAutoVacuum;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

const LOGS_DB_FILENAME: &str = "logs_2.sqlite";
const GOALS_DB_FILENAME: &str = "goals_1.sqlite";
const MEMORIES_DB_FILENAME: &str = "memories_1.sqlite";
const QUEUE_DB_FILENAME: &str = "queue_1.sqlite";
const STATE_DB_FILENAME: &str = "state_5.sqlite";
const THREAD_HISTORY_DB_FILENAME: &str = "thread_history_1.sqlite";

#[derive(Clone, Copy)]
struct RuntimeDbSpec {
    label: &'static str,
    filename: &'static str,
    kind: DbKind,
    open_phase: &'static str,
    migrate_phase: &'static str,
}

impl RuntimeDbSpec {
    fn path(self, codex_home: &Path) -> PathBuf {
        codex_home.join(self.filename)
    }
}

const STATE_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "state DB",
    filename: STATE_DB_FILENAME,
    kind: DbKind::State,
    open_phase: "open_state",
    migrate_phase: "migrate_state",
};

const LOGS_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "log DB",
    filename: LOGS_DB_FILENAME,
    kind: DbKind::Logs,
    open_phase: "open_logs",
    migrate_phase: "migrate_logs",
};

const GOALS_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "goals DB",
    filename: GOALS_DB_FILENAME,
    kind: DbKind::Goals,
    open_phase: "open_goals",
    migrate_phase: "migrate_goals",
};

const MEMORIES_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "memories DB",
    filename: MEMORIES_DB_FILENAME,
    kind: DbKind::Memories,
    open_phase: "open_memories",
    migrate_phase: "migrate_memories",
};

const QUEUE_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "queue DB",
    filename: QUEUE_DB_FILENAME,
    kind: DbKind::Queue,
    open_phase: "open_queue",
    migrate_phase: "migrate_queue",
};

const THREAD_HISTORY_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "thread history DB",
    filename: THREAD_HISTORY_DB_FILENAME,
    kind: DbKind::ThreadHistory,
    open_phase: "open_thread_history",
    migrate_phase: "migrate_thread_history",
};

const RUNTIME_DBS: [RuntimeDbSpec; 6] = [
    STATE_DB,
    LOGS_DB,
    GOALS_DB,
    MEMORIES_DB,
    QUEUE_DB,
    THREAD_HISTORY_DB,
];

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeDbPath {
    pub label: &'static str,
    pub path: PathBuf,
}

/// Resolved configuration shared by all Codex SQLite connections.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SqliteConfig {
    sqlite_home: AbsolutePathBuf,
}

impl SqliteConfig {
    pub fn from_sqlite_home(sqlite_home: AbsolutePathBuf) -> Self {
        Self { sqlite_home }
    }

    pub fn new_for_testing(sqlite_home: AbsolutePathBuf) -> Self {
        Self::from_sqlite_home(sqlite_home)
    }

    pub fn home(&self) -> &Path {
        self.sqlite_home.as_path()
    }

    /// Return the path to the primary state database.
    pub fn state_db_path(&self) -> PathBuf {
        STATE_DB.path(self.home())
    }

    /// Return the path to the logs database.
    pub fn logs_db_path(&self) -> PathBuf {
        LOGS_DB.path(self.home())
    }

    /// Return the path to the goals database.
    pub fn goals_db_path(&self) -> PathBuf {
        GOALS_DB.path(self.home())
    }

    /// Return the path to the memories database.
    pub fn memories_db_path(&self) -> PathBuf {
        MEMORIES_DB.path(self.home())
    }

    /// Return the path to the durable user-message queue database.
    pub fn queue_db_path(&self) -> PathBuf {
        QUEUE_DB.path(self.home())
    }

    /// Return the path to the paginated thread-history database.
    pub fn thread_history_db_path(&self) -> PathBuf {
        THREAD_HISTORY_DB.path(self.home())
    }

    /// Return the paths to every database managed by the state runtime.
    pub fn runtime_db_paths(&self) -> Vec<RuntimeDbPath> {
        RUNTIME_DBS
            .iter()
            .map(|spec| RuntimeDbPath {
                label: spec.label,
                path: spec.path(self.home()),
            })
            .collect()
    }

    pub(super) async fn open_state_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        // New state DBs should use incremental auto-vacuum, but retrofitting an
        // existing DB requires a full VACUUM. Do not attempt that during process
        // startup: it is maintenance work that can contend with foreground writers.
        self.open_runtime_db(STATE_DB, migrator, telemetry_override)
            .await
    }

    pub(super) async fn open_logs_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        self.open_runtime_db(LOGS_DB, migrator, telemetry_override)
            .await
    }

    pub(super) async fn open_goals_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        self.open_runtime_db(GOALS_DB, migrator, telemetry_override)
            .await
    }

    pub(super) async fn open_memories_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        self.open_runtime_db(MEMORIES_DB, migrator, telemetry_override)
            .await
    }

    pub(super) async fn open_queue_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        self.open_runtime_db(QUEUE_DB, migrator, telemetry_override)
            .await
    }

    pub(super) async fn open_thread_history_db(
        &self,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        self.open_runtime_db(THREAD_HISTORY_DB, migrator, telemetry_override)
            .await
    }

    async fn open_runtime_db(
        &self,
        spec: RuntimeDbSpec,
        migrator: &Migrator,
        telemetry_override: Option<&dyn DbTelemetry>,
    ) -> anyhow::Result<SqlitePool> {
        let path = spec.path(self.home());
        let started = Instant::now();
        let pool_result = self
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
        let pool = pool_result.map_err(|source| {
            RuntimeDbInitError::new(spec.label, "open", path.as_path(), source)
        })?;
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
            return Err(
                RuntimeDbInitError::new(spec.label, "migrate", path.as_path(), source).into(),
            );
        }
        Ok(pool)
    }

    /// Open a writable Codex SQLite database, creating it if necessary.
    pub async fn open_read_write_pool(&self, path: &Path) -> Result<SqlitePool, Error> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Normal)
            .auto_vacuum(SqliteAutoVacuum::Incremental)
            .busy_timeout(Duration::from_secs(5))
            .log_statements(LevelFilter::Off);
        SqlitePoolOptions::new()
            .max_connections(5)
            .connect_with(options)
            .await
    }

    /// Open an append-only evidence database with full synchronous durability.
    ///
    /// Evidence owners remain responsible for their own migrations and must
    /// not route authoritative corruption through the rebuildable state-DB
    /// recovery path.
    pub async fn open_durable_evidence_pool(&self, path: &Path) -> Result<SqlitePool, Error> {
        open_durable_sqlite_pool(path, /*max_connections*/ 5).await
    }

    /// Checkpoint a private recovery candidate after all validation handles close.
    ///
    /// The owner must hold its recovery fence and pass a newly materialized copy,
    /// never the suspect source. A single connection permits the journal-mode
    /// switch that a pool's other live handles would otherwise block.
    pub async fn checkpoint_private_recovery_database(&self, path: &Path) -> Result<(), Error> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(false)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5))
            .log_statements(LevelFilter::Off);
        let mut connection = options.connect().await?;
        let checkpoint = async {
            let (busy, _, _): (i32, i32, i32) = sqlx::query_as("PRAGMA wal_checkpoint(TRUNCATE)")
                .fetch_one(&mut connection)
                .await?;
            if busy != 0 {
                return Err(Error::Protocol(
                    "recovery candidate checkpoint is busy".to_string(),
                ));
            }
            let journal_mode: String = sqlx::query_scalar("PRAGMA journal_mode=DELETE")
                .fetch_one(&mut connection)
                .await?;
            if !journal_mode.eq_ignore_ascii_case("delete") {
                return Err(Error::Protocol(
                    "recovery candidate could not checkpoint to a single-file cut".to_string(),
                ));
            }
            Ok(())
        }
        .await;
        let close = connection.close().await;
        checkpoint?;
        close
    }

    /// Retained only so callers fail closed instead of reopening a suspect
    /// lexical source path with a reconnect-capable writer pool.
    ///
    /// Writable recovery binds [`Self::bind_existing_recovery_database`],
    /// captures an identity-checked copy from retained descriptors, validates
    /// that copy against an independently retained current-cut witness, and
    /// opens only the new generation. This path-based source reopen therefore
    /// remains deliberately unavailable.
    pub async fn open_existing_durable_evidence_pool(
        &self,
        path: &Path,
    ) -> Result<SqlitePool, Error> {
        let _ = (self, path);
        Err(Error::Protocol(
            "path-based SQLite recovery is disabled".to_string(),
        ))
    }

    /// Open an existing Codex SQLite database without creating or modifying it.
    pub async fn open_read_only_pool(&self, path: &Path) -> Result<SqlitePool, Error> {
        let pool = self.lazy_read_only_pool(path);
        let connection = pool.acquire().await?;
        drop(connection);
        Ok(pool)
    }

    /// Construct an unopened read-only pool so a caller can install its lifetime
    /// fence before connection I/O starts. This does not validate the database;
    /// the caller must acquire/query it and retain its fence through pool close.
    pub fn lazy_read_only_pool(&self, path: &Path) -> SqlitePool {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(false)
            .read_only(true)
            .log_statements(LevelFilter::Off);
        SqlitePoolOptions::new()
            .max_connections(1)
            .connect_lazy_with(options)
    }
}

/// Open a durable owner database through the single Codex SQLite connection shim.
///
/// Callers retain schema/migration ownership. This function centralizes only the
/// connection invariants: WAL, FULL synchronous durability, foreign keys and the
/// bounded busy timeout. The caller supplies its bounded pool size.
pub async fn open_durable_sqlite_pool(
    path: &Path,
    max_connections: u32,
) -> Result<SqlitePool, Error> {
    if max_connections == 0 {
        return Err(Error::Protocol(
            "SQLite pool must have at least one connection".to_string(),
        ));
    }
    let options = SqliteConnectOptions::new()
        .filename(path)
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Full)
        .foreign_keys(true)
        .busy_timeout(Duration::from_secs(5))
        .log_statements(LevelFilter::Off);
    SqlitePoolOptions::new()
        .max_connections(max_connections)
        .connect_with(options)
        .await
}

/// Open a transient in-memory SQLite reference through the centralized shim.
///
/// This is intended for migration/schema comparison, never as an authoritative
/// durable owner.
pub async fn open_in_memory_sqlite_pool(max_connections: u32) -> Result<SqlitePool, Error> {
    if max_connections != 1 {
        return Err(Error::Protocol(
            "in-memory SQLite reference must use exactly one connection".to_string(),
        ));
    }
    let options = SqliteConnectOptions::new()
        .filename(":memory:")
        .create_if_missing(true)
        .foreign_keys(true)
        .log_statements(LevelFilter::Off);
    SqlitePoolOptions::new()
        .max_connections(max_connections)
        .connect_with(options)
        .await
}

#[cfg(test)]
#[path = "sqlite_owner_pool_tests.rs"]
mod owner_pool_tests;
