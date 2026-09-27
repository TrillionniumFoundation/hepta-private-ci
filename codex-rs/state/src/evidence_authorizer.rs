//! Runtime-only SQLite authorization for the authoritative evidence database.
//!
//! Installed before a connection is published to its pool, and therefore on
//! every reconnect. Migration connections never install this callback and are
//! closed before the runtime pool opens. It is defense against unintended SQL,
//! not protection from a process that owns the database file or SQLite handle.

#![expect(
    clippy::disallowed_methods,
    reason = "centralized authoritative evidence SQLite connection shim"
)]

use std::ffi::CStr;
use std::ffi::c_char;
use std::ffi::c_int;
use std::ffi::c_void;
use std::path::Path;
use std::time::Duration;

use libsqlite3_sys as ffi;
use log::LevelFilter;
use sqlx::ConnectOptions;
use sqlx::SqliteConnection;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

use crate::SqliteConfig;

impl SqliteConfig {
    /// Open a fully migrated evidence database without granting runtime DDL.
    ///
    /// The migration pool must be closed before this is called. Every new
    /// connection is authorized before it becomes visible to a caller; a
    /// reconnect cannot silently regain migration or pragma-write privileges.
    pub async fn open_durable_evidence_runtime_pool(
        &self,
        path: &Path,
    ) -> Result<sqlx::SqlitePool, sqlx::Error> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(false)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .pragma("recursive_triggers", "ON")
            .busy_timeout(Duration::from_secs(5))
            .log_statements(LevelFilter::Off);
        SqlitePoolOptions::new()
            .max_connections(5)
            .after_connect(|connection, _| Box::pin(install(connection)))
            .connect_with(options)
            .await
    }
}

async fn install(connection: &mut SqliteConnection) -> Result<(), sqlx::Error> {
    // SAFETY: SQLx's lock excludes its worker from the SQLite connection. The
    // callback has static lifetime, uses no user data, never accesses SQLite,
    // allocates nothing, and cannot unwind across the C ABI.
    let mut locked = connection.lock_handle().await?;
    let rc = unsafe {
        ffi::sqlite3_set_authorizer(
            locked.as_raw_handle().as_ptr(),
            Some(authorize),
            std::ptr::null_mut(),
        )
    };
    if rc != ffi::SQLITE_OK {
        return Err(sqlx::Error::Protocol(format!(
            "failed to install evidence SQLite runtime authorizer: {rc}"
        )));
    }
    Ok(())
}

unsafe extern "C" fn authorize(
    _context: *mut c_void,
    action: c_int,
    first: *const c_char,
    second: *const c_char,
    database: *const c_char,
    _trigger: *const c_char,
) -> c_int {
    // SAFETY: SQLite supplies either NULL or valid NUL-terminated strings for
    // this callback's duration. Borrowed slices do not escape this invocation.
    let first = unsafe { argument(first) };
    let second = unsafe { argument(second) };
    let database = unsafe { argument(database) };
    decision(action, first, second, database)
}

unsafe fn argument<'a>(value: *const c_char) -> Option<&'a [u8]> {
    if value.is_null() {
        None
    } else {
        // SAFETY: delegated from the documented SQLite authorizer contract.
        Some(unsafe { CStr::from_ptr(value) }.to_bytes())
    }
}

fn eq(value: Option<&[u8]>, expected: &[u8]) -> bool {
    value.is_some_and(|actual| actual.eq_ignore_ascii_case(expected))
}

fn immutable_table(table: Option<&[u8]>) -> bool {
    [
        b"qualification_evidence".as_slice(),
        b"evidence_recovery_identity".as_slice(),
        b"governance_decisions".as_slice(),
        b"governance_receipts".as_slice(),
    ]
    .iter()
    .any(|expected| eq(table, expected))
}

fn decision(
    action: c_int,
    first: Option<&[u8]>,
    second: Option<&[u8]>,
    database: Option<&[u8]>,
) -> c_int {
    let allowed = match action {
        // Runtime connections never have migration or attachment capability.
        ffi::SQLITE_CREATE_INDEX
        | ffi::SQLITE_CREATE_TABLE
        | ffi::SQLITE_CREATE_TEMP_INDEX
        | ffi::SQLITE_CREATE_TEMP_TABLE
        | ffi::SQLITE_CREATE_TEMP_TRIGGER
        | ffi::SQLITE_CREATE_TEMP_VIEW
        | ffi::SQLITE_CREATE_TRIGGER
        | ffi::SQLITE_CREATE_VIEW
        | ffi::SQLITE_DROP_INDEX
        | ffi::SQLITE_DROP_TABLE
        | ffi::SQLITE_DROP_TEMP_INDEX
        | ffi::SQLITE_DROP_TEMP_TABLE
        | ffi::SQLITE_DROP_TEMP_TRIGGER
        | ffi::SQLITE_DROP_TEMP_VIEW
        | ffi::SQLITE_DROP_TRIGGER
        | ffi::SQLITE_DROP_VIEW
        | ffi::SQLITE_ALTER_TABLE
        | ffi::SQLITE_ATTACH
        | ffi::SQLITE_DETACH
        | ffi::SQLITE_CREATE_VTABLE
        | ffi::SQLITE_DROP_VTABLE
        | ffi::SQLITE_REINDEX
        | ffi::SQLITE_ANALYZE => false,
        ffi::SQLITE_INSERT | ffi::SQLITE_UPDATE | ffi::SQLITE_DELETE => {
            eq(database, b"main")
                && first.is_some()
                && !eq(first, b"_sqlx_migrations")
                && !eq(first, b"sqlite_master")
                && !eq(first, b"sqlite_schema")
                && !eq(first, b"sqlite_sequence")
                && (action == ffi::SQLITE_INSERT || !immutable_table(first))
        }
        ffi::SQLITE_PRAGMA => {
            // Introspection pragmas accept a table/index argument. Everything
            // else with an argument is denied, including all durability and
            // trigger/constraint toggles. Bare pragmas below cannot mutate DB.
            [
                b"table_info".as_slice(),
                b"table_xinfo".as_slice(),
                b"index_info".as_slice(),
                b"index_xinfo".as_slice(),
                b"index_list".as_slice(),
                b"foreign_key_list".as_slice(),
                b"foreign_key_check".as_slice(),
                b"quick_check".as_slice(),
                b"integrity_check".as_slice(),
            ]
            .iter()
            .any(|name| eq(first, name))
                || (second.is_none()
                    && [
                        b"schema_version".as_slice(),
                        b"user_version".as_slice(),
                        b"database_list".as_slice(),
                        b"foreign_keys".as_slice(),
                        b"recursive_triggers".as_slice(),
                        b"synchronous".as_slice(),
                        b"journal_mode".as_slice(),
                        b"page_count".as_slice(),
                        b"page_size".as_slice(),
                        b"freelist_count".as_slice(),
                        b"compile_options".as_slice(),
                    ]
                    .iter()
                    .any(|name| eq(first, name)))
        }
        ffi::SQLITE_FUNCTION => {
            // Stock SQLite is used; runtime cannot load extensions or invoke
            // filesystem-writing functions provided by optional extensions.
            second.is_some()
                && ![b"load_extension".as_slice(), b"writefile".as_slice()]
                    .iter()
                    .any(|name| eq(second, name))
        }
        ffi::SQLITE_READ => {
            eq(database, b"main")
                || eq(database, b"temp")
                // SQLite emits a no-column table read (e.g. COUNT(*) or an
                // INTEGER PRIMARY KEY scan) with an empty column and NULL DB.
                || (database.is_none() && first.is_some() && second == Some(b"".as_slice()))
        }
        ffi::SQLITE_SELECT
        | ffi::SQLITE_TRANSACTION
        | ffi::SQLITE_SAVEPOINT
        | ffi::SQLITE_RECURSIVE => true,
        // New or unrecognized SQLite authorization actions fail closed.
        _ => false,
    };
    if allowed {
        ffi::SQLITE_OK
    } else {
        ffi::SQLITE_DENY
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn null_and_unknown_actions_fail_closed() {
        for action in [-1, ffi::SQLITE_INSERT, ffi::SQLITE_PRAGMA, ffi::SQLITE_FUNCTION] {
            assert_eq!(decision(action, None, None, None), ffi::SQLITE_DENY);
        }
    }

    #[test]
    fn policy_is_case_insensitive_and_does_not_grant_migration_writes() {
        for table in [
            b"QUALIFICATION_EVIDENCE".as_slice(),
            b"Evidence_Recovery_Identity".as_slice(),
        ] {
            for action in [ffi::SQLITE_UPDATE, ffi::SQLITE_DELETE] {
                assert_eq!(
                    decision(action, Some(table), None, Some(b"MAIN")),
                    ffi::SQLITE_DENY
                );
            }
        }
        for action in [ffi::SQLITE_INSERT, ffi::SQLITE_UPDATE, ffi::SQLITE_DELETE] {
            assert_eq!(
                decision(action, Some(b"_sqlx_migrations"), None, Some(b"main")),
                ffi::SQLITE_DENY
            );
        }
        assert_eq!(
            decision(ffi::SQLITE_PRAGMA, Some(b"recursive_triggers"), Some(b"off"), None),
            ffi::SQLITE_DENY
        );
        assert_eq!(
            decision(ffi::SQLITE_PRAGMA, Some(b"table_info"), Some(b"qualification_evidence"), None),
            ffi::SQLITE_OK
        );
        assert_eq!(
            decision(ffi::SQLITE_READ, Some(b"qualification_evidence"), Some(b""), None),
            ffi::SQLITE_OK
        );
    }
}
