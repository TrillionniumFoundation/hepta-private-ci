//! The original shared SQLite connection, commit guard and physical recovery owner.
//!
//! State-runtime migrations and telemetry stay in codex-state. This crate
//! contains the same connection/admission implementations and public types so
//! a storage owner need not link the unrelated rollout/protocol dependency.

const _: () = assert!(
    libsqlite3_sys::SQLITE_VERSION_NUMBER >= 3_051_003,
    "bundled SQLite must include the WAL-reset corruption fix",
);

mod sqlite;
mod sqlite_read_barrier;
mod sqlite_recovery;

pub use sqlite::RuntimeDbPath;
pub use sqlite::SqliteConfig;
pub use sqlite_read_barrier::SqliteReadBarrier;
pub use sqlite_recovery::ExistingSqliteRecoveryGuard;
pub use sqlite_recovery::RootSqliteMaterialIdentity;
pub use sqlite_recovery::RootSqliteMaterialRegistration;
pub use sqlite_recovery::RootSqliteMaterialSource;
pub use sqlite_recovery::RootSqliteOwnerCandidate;
pub use sqlite_recovery::RootSqliteOwnerCopy;
pub use sqlite_recovery::RootSqliteOwnerPublication;
pub use sqlite_recovery::RootSqliteOwnerPublished;
pub use sqlite_recovery::SqliteRecoveryError;

#[cfg(test)]
mod test_support;
