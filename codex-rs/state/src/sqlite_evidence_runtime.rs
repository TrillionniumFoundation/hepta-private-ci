//! Restricted SQLite runtime connection profile for authoritative evidence stores.
//!
//! Migrations use [`SqliteConfig::open_durable_evidence_pool`]. Once a production
//! store has passed read-only migration and schema verification, runtime traffic
//! reopens the existing lineage through this profile. Every pooled connection
//! installs a SQLite authorizer that rejects schema changes, database attachment,
//! migration-ledger mutation, extension loading, and write-capable PRAGMAs while
//! preserving normal evidence appends and bounded integrity checks.

#![expect(
    clippy::disallowed_methods,
    reason = "this is codex-state's centralized evidence SQLite runtime shim"
)]

use std::ffi::CStr;
use std::os::raw::c_char;
use std::os::raw::c_int;
use std::os::raw::c_void;
use std::path::Path;
use std::time::Duration;

use log::LevelFilter;
use sqlx::ConnectOptions;
use sqlx::Error;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

use crate::SqliteConfig;

impl SqliteConfig {
    /// Open an existing evidence database for normal production runtime writes.
    ///
    /// This constructor never creates a database and never runs migrations. The
    /// caller must first verify the complete migration ledger and schema through
    /// a read-only connection. The installed authorizer is defense in depth on
    /// top of the evidence schema's immutable-row triggers: application DML is
    /// allowed, while control-plane mutations fail during statement preparation.
    pub async fn open_existing_durable_evidence_runtime_pool(
        &self,
        path: &Path,
    ) -> Result<SqlitePool, Error> {
        if path.parent() != Some(self.home()) || path.file_name().is_none() {
            return Err(Error::Protocol(
                "evidence runtime database must be a direct child of the configured SQLite home"
                    .to_string(),
            ));
        }
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(false)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5))
            .pragma("trusted_schema", "OFF")
            .log_statements(LevelFilter::Off);
        SqlitePoolOptions::new()
            .max_connections(5)
            .after_connect(|connection, _metadata| {
                Box::pin(async move {
                    let mut handle = connection.lock_handle().await?;
                    // SAFETY: `lock_handle` excludes SQLx's worker for this
                    // connection. The callback and user-data pointer are static,
                    // retain no connection-owned references, allocate no SQLite
                    // resources, and remain valid for the connection lifetime.
                    let result = unsafe {
                        libsqlite3_sys::sqlite3_set_authorizer(
                            handle.as_raw_handle().as_ptr(),
                            Some(evidence_runtime_authorizer),
                            std::ptr::null_mut(),
                        )
                    };
                    if result != libsqlite3_sys::SQLITE_OK {
                        return Err(Error::Protocol(format!(
                            "failed to install evidence SQLite authorizer: {result}"
                        )));
                    }
                    Ok(())
                })
            })
            .connect_with(options)
            .await
    }
}

unsafe extern "C" fn evidence_runtime_authorizer(
    _context: *mut c_void,
    action: c_int,
    first: *const c_char,
    second: *const c_char,
    _database: *const c_char,
    _trigger: *const c_char,
) -> c_int {
    use libsqlite3_sys::SQLITE_ALTER_TABLE;
    use libsqlite3_sys::SQLITE_ANALYZE;
    use libsqlite3_sys::SQLITE_ATTACH;
    use libsqlite3_sys::SQLITE_CREATE_INDEX;
    use libsqlite3_sys::SQLITE_CREATE_TABLE;
    use libsqlite3_sys::SQLITE_CREATE_TEMP_INDEX;
    use libsqlite3_sys::SQLITE_CREATE_TEMP_TABLE;
    use libsqlite3_sys::SQLITE_CREATE_TEMP_TRIGGER;
    use libsqlite3_sys::SQLITE_CREATE_TEMP_VIEW;
    use libsqlite3_sys::SQLITE_CREATE_TRIGGER;
    use libsqlite3_sys::SQLITE_CREATE_VIEW;
    use libsqlite3_sys::SQLITE_CREATE_VTABLE;
    use libsqlite3_sys::SQLITE_DELETE;
    use libsqlite3_sys::SQLITE_DENY;
    use libsqlite3_sys::SQLITE_DETACH;
    use libsqlite3_sys::SQLITE_DROP_INDEX;
    use libsqlite3_sys::SQLITE_DROP_TABLE;
    use libsqlite3_sys::SQLITE_DROP_TEMP_INDEX;
    use libsqlite3_sys::SQLITE_DROP_TEMP_TABLE;
    use libsqlite3_sys::SQLITE_DROP_TEMP_TRIGGER;
    use libsqlite3_sys::SQLITE_DROP_TEMP_VIEW;
    use libsqlite3_sys::SQLITE_DROP_TRIGGER;
    use libsqlite3_sys::SQLITE_DROP_VIEW;
    use libsqlite3_sys::SQLITE_DROP_VTABLE;
    use libsqlite3_sys::SQLITE_FUNCTION;
    use libsqlite3_sys::SQLITE_INSERT;
    use libsqlite3_sys::SQLITE_OK;
    use libsqlite3_sys::SQLITE_PRAGMA;
    use libsqlite3_sys::SQLITE_REINDEX;
    use libsqlite3_sys::SQLITE_UPDATE;

    match action {
        SQLITE_CREATE_INDEX
        | SQLITE_CREATE_TABLE
        | SQLITE_CREATE_TEMP_INDEX
        | SQLITE_CREATE_TEMP_TABLE
        | SQLITE_CREATE_TEMP_TRIGGER
        | SQLITE_CREATE_TEMP_VIEW
        | SQLITE_CREATE_TRIGGER
        | SQLITE_CREATE_VIEW
        | SQLITE_CREATE_VTABLE
        | SQLITE_DROP_INDEX
        | SQLITE_DROP_TABLE
        | SQLITE_DROP_TEMP_INDEX
        | SQLITE_DROP_TEMP_TABLE
        | SQLITE_DROP_TEMP_TRIGGER
        | SQLITE_DROP_TEMP_VIEW
        | SQLITE_DROP_TRIGGER
        | SQLITE_DROP_VIEW
        | SQLITE_DROP_VTABLE
        | SQLITE_ALTER_TABLE
        | SQLITE_REINDEX
        | SQLITE_ANALYZE
        | SQLITE_ATTACH
        | SQLITE_DETACH => SQLITE_DENY,
        SQLITE_INSERT | SQLITE_UPDATE | SQLITE_DELETE
            if is_control_plane_table(first) =>
        {
            SQLITE_DENY
        }
        SQLITE_PRAGMA => authorize_runtime_pragma(first, second),
        SQLITE_FUNCTION if c_argument_eq(first, "load_extension")
            || c_argument_eq(second, "load_extension") =>
        {
            SQLITE_DENY
        }
        _ => SQLITE_OK,
    }
}

fn is_control_plane_table(table: *const c_char) -> bool {
    c_argument_eq(table, "_sqlx_migrations")
        || c_argument_eq(table, "sqlite_schema")
        || c_argument_eq(table, "sqlite_master")
        || c_argument_eq(table, "sqlite_temp_schema")
        || c_argument_eq(table, "sqlite_temp_master")
}

fn authorize_runtime_pragma(name: *const c_char, argument: *const c_char) -> c_int {
    use libsqlite3_sys::SQLITE_DENY;
    use libsqlite3_sys::SQLITE_OK;

    if c_argument_eq(name, "quick_check") || c_argument_eq(name, "integrity_check") {
        return if argument.is_null() || c_argument_is_positive_decimal(argument) {
            SQLITE_OK
        } else {
            SQLITE_DENY
        };
    }
    if [
        "foreign_key_check",
        "table_info",
        "table_xinfo",
        "index_list",
        "index_info",
        "index_xinfo",
    ]
    .iter()
    .any(|expected| c_argument_eq(name, expected))
    {
        // These PRAGMAs only inspect schema or constraint state. Their optional
        // first argument names a table or index and cannot alter the database.
        return SQLITE_OK;
    }
    if [
        "database_list",
        "compile_options",
        "data_version",
        "schema_version",
        "user_version",
        "foreign_keys",
        "defer_foreign_keys",
        "journal_mode",
        "synchronous",
        "trusted_schema",
        "query_only",
    ]
    .iter()
    .any(|expected| c_argument_eq(name, expected))
    {
        // Read forms have no argument. Assignment forms are denied even where
        // SQLite would otherwise accept them as connection-local changes.
        return if argument.is_null() {
            SQLITE_OK
        } else {
            SQLITE_DENY
        };
    }
    if c_argument_eq(name, "wal_checkpoint") {
        return if argument.is_null()
            || ["PASSIVE", "FULL", "RESTART", "TRUNCATE", "NOOP"]
                .iter()
                .any(|mode| c_argument_eq(argument, mode))
        {
            SQLITE_OK
        } else {
            SQLITE_DENY
        };
    }
    // A default-deny policy matters here: several mutating PRAGMAs, including
    // incremental_vacuum and optimize, can be invoked without an assignment.
    SQLITE_DENY
}

fn c_argument_is_positive_decimal(argument: *const c_char) -> bool {
    let Some(bytes) = c_argument_bytes(argument) else {
        return false;
    };
    !bytes.is_empty() && bytes.iter().all(u8::is_ascii_digit) && bytes != b"0"
}

fn c_argument_eq(argument: *const c_char, expected: &str) -> bool {
    c_argument_bytes(argument)
        .is_some_and(|bytes| bytes.eq_ignore_ascii_case(expected.as_bytes()))
}

fn c_argument_bytes<'a>(argument: *const c_char) -> Option<&'a [u8]> {
    if argument.is_null() {
        return None;
    }
    // SAFETY: SQLite guarantees authorizer string arguments, when non-null,
    // remain valid NUL-terminated strings for the duration of the callback.
    Some(unsafe { CStr::from_ptr(argument) }.to_bytes())
}
