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
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

const LOGS_DB_FILENAME: &str = "logs_2.sqlite";
const GOALS_DB_FILENAME: &str = "goals_1.sqlite";
const MEMORIES_DB_FILENAME: &str = "memories_1.sqlite";
const QUEUE_DB_FILENAME: &str = "queue_1.sqlite";
const STATE_DB_FILENAME: &str = "state_5.sqlite";
const THREAD_HISTORY_DB_FILENAME: &str = "thread_history_1.sqlite";
const COMMIT_GUARD_CUSTODY_COLLATION: &str = "__hepta_commit_guard_custody_v1";

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

    /// Open an isolated, single-connection in-memory database for schema tests.
    ///
    /// Repeated pool acquisitions retain the same in-memory database.
    pub async fn open_in_memory_pool_for_testing() -> Result<SqlitePool, Error> {
        SqlitePoolOptions::new()
            .max_connections(1)
            .connect("sqlite::memory:")
            .await
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
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5))
            .log_statements(LevelFilter::Off);
        SqlitePoolOptions::new()
            .max_connections(5)
            .connect_with(options)
            .await
    }

    /// Open an evidence pool with an explicit synchronous commit guard.
    ///
    /// Every physical connection installs `commit_allowed` before owner code
    /// receives it. Returning false vetoes explicit and implicit SQLite commits.
    /// The callback must be bounded, nonblocking, and must not call SQLite.
    /// The reserved `__hepta_commit_guard_custody_v1` collation retains callback
    /// captures past SQLx hook teardown until SQLite closes this connection's
    /// Btrees. Owners must keep the pool private and must not replace or remove
    /// that collation or the commit hook. The collation name is not a capability.
    /// The same callback captures enter SQLx's native lifetime token before
    /// opening SQLite, retaining their actual resource owners across initial
    /// PRAGMAs, cancellation and native close. They must own the real custody;
    /// this API does not turn a borrowed path or an empty predicate into a fence.
    ///
    /// This method supplies no checkout coordination, authenticated Current
    /// receipt, or recovery authority. Owners that require a protected transition
    /// before checkout must use `open_coordinated_durable_evidence_pool`.
    pub async fn open_commit_guarded_durable_evidence_pool<F>(
        &self,
        path: &Path,
        commit_allowed: F,
    ) -> Result<SqlitePool, Error>
    where
        F: Fn() -> bool + Send + Sync + 'static,
    {
        let commit_allowed = Arc::new(commit_allowed);
        let connection_custody = Arc::clone(&commit_allowed);
        let options = SqliteConnectOptions::new()
            .connection_lifetime_token(connection_custody)
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5))
            .log_statements(LevelFilter::Off);
        SqlitePoolOptions::new()
            .max_connections(5)
            .after_connect(move |connection, _metadata| {
                let commit_allowed = Arc::clone(&commit_allowed);
                Box::pin(install_commit_guard(connection, commit_allowed))
            })
            .connect_with(options)
            .await
    }

    /// Open an evidence writer whose explicit and implicit commits use `commit_allowed`.
    ///
    /// The owner must keep the returned pool private and retain the independently
    /// authenticated Current/writer state checked by the callback. This connection
    /// API does not establish that authority or bind a protected checkpoint.
    ///
    /// Every new connection installs the commit hook before it can be checked out.
    /// Both new and reused connections await `before_checkout`; its completion is
    /// coordination, not permission to commit. A failed witness refresh must leave
    /// `commit_allowed` false. The commit hook remains the final write boundary.
    ///
    /// `commit_allowed` runs synchronously inside SQLite and must be bounded,
    /// nonblocking, and must not call SQLite. `before_checkout` must not acquire
    /// from this pool or retain a lock needed by the commit callback. The SQLite
    /// handle lock is released before awaiting checkout coordination.
    ///
    /// Callback captures use the same native lifetime token and reserved
    /// collation as `open_commit_guarded_durable_evidence_pool`. Callers must
    /// supply the actual resource owner and must not replace the hook or collation.
    /// This is not a replacement for descriptor-bound recovery, authenticated
    /// Current authority, or the owner's whole-store gate.
    pub async fn open_coordinated_durable_evidence_pool<F, C, Fut>(
        &self,
        path: &Path,
        commit_allowed: F,
        before_checkout: C,
    ) -> Result<SqlitePool, Error>
    where
        F: Fn() -> bool + Send + Sync + 'static,
        C: Fn() -> Fut + Send + Sync + 'static,
        Fut: std::future::Future<Output = ()> + Send + 'static,
    {
        let commit_allowed = Arc::new(commit_allowed);
        let connection_custody = Arc::clone(&commit_allowed);
        let before_checkout = Arc::new(before_checkout);
        let before_reuse = Arc::clone(&before_checkout);
        let options = SqliteConnectOptions::new()
            .connection_lifetime_token(connection_custody)
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5))
            .log_statements(LevelFilter::Off);
        SqlitePoolOptions::new()
            .max_connections(5)
            .after_connect(move |connection, _metadata| {
                let commit_allowed = Arc::clone(&commit_allowed);
                let before_checkout = Arc::clone(&before_checkout);
                Box::pin(async move {
                    install_commit_guard(connection, commit_allowed).await?;
                    before_checkout().await;
                    Ok(())
                })
            })
            .before_acquire(move |_connection, _metadata| {
                let before_checkout = Arc::clone(&before_reuse);
                Box::pin(async move {
                    before_checkout().await;
                    Ok(true)
                })
            })
            .connect_with(options)
            .await
    }

    /// Checkpoint a private recovery candidate after all validation handles close.
    ///
    /// The owner must hold its recovery fence and pass a newly materialized copy,
    /// never the suspect source. A single connection permits the journal-mode
    /// switch that a pool's other live handles would otherwise block.
    ///
    /// `connection_custody` must own that actual recovery fence, including any
    /// retained filesystem handles. Native SQLite work can outlive cancellation
    /// of this future; a path or a separately created token is not custody.
    pub async fn checkpoint_private_recovery_database(
        &self,
        path: &Path,
        connection_custody: Arc<dyn Send + Sync + 'static>,
    ) -> Result<(), Error> {
        let options = SqliteConnectOptions::new()
            .connection_lifetime_token(connection_custody)
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

    /// Observe an existing evidence database through read-only file-open flags.
    ///
    /// Every connection also permanently vetoes commits. This does not establish
    /// an authenticated Current witness or exclude other writers; checkpoint
    /// publication must use the separate lock-only barrier and the owner's guard.
    pub async fn open_durable_observation_pool(&self, path: &Path) -> Result<SqlitePool, Error> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(false)
            .read_only(true)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5))
            .log_statements(LevelFilter::Off);
        SqlitePoolOptions::new()
            .max_connections(5)
            .after_connect(|connection, _metadata| {
                Box::pin(async move {
                    connection.lock_handle().await?.set_commit_hook(|| false);
                    Ok(())
                })
            })
            .connect_with(options)
            .await
    }

    /// Open an existing Codex SQLite database without creating or modifying it.
    pub async fn open_read_only_pool(&self, path: &Path) -> Result<SqlitePool, Error> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(false)
            .read_only(true)
            .log_statements(LevelFilter::Off);
        SqlitePoolOptions::new()
            .max_connections(1)
            .connect_with(options)
            .await
    }
}

async fn install_commit_guard<F>(
    connection: &mut sqlx::SqliteConnection,
    commit_allowed: Arc<F>,
) -> Result<(), Error>
where
    F: Fn() -> bool + Send + Sync + 'static,
{
    let mut handle = connection.lock_handle().await?;
    let custody = Arc::clone(&commit_allowed);
    // SQLx removes and drops commit hooks before its native handle closes.
    // SQLite destroys this collation after closing this connection's Btrees.
    // The comparator never invokes the commit predicate or grants write access.
    handle.create_collation(COMMIT_GUARD_CUSTODY_COLLATION, move |left, right| {
        let _retained_custody = &custody;
        left.cmp(right)
    })?;
    handle.set_commit_hook(move || commit_allowed());
    Ok(())
}

#[cfg(test)]
#[path = "sqlite_commit_gate_tests.rs"]
mod commit_gate_tests;

#[cfg(test)]
#[path = "sqlite_native_custody_tests.rs"]
mod native_custody_tests;

#[cfg(test)]
#[path = "sqlite_refused_commit_pool_tests.rs"]
mod refused_commit_pool_tests;
