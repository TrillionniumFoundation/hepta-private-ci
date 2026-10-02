//! Isolated test-only SQLite fault and migration-tamper constructors.
//!
//! Cargo consumers declare this only in dev-dependencies; Bazel enforces
//! testonly=true. Production connection policies remain in codex-state.
#![forbid(unsafe_code)]
#![expect(
    clippy::disallowed_methods,
    reason = "isolated centralized SQLite test-only connection shim"
)]

use log::LevelFilter;
use sqlx::ConnectOptions;
use sqlx::Error;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;
use std::num::NonZeroU32;
use std::path::Path;

/// Reproduce disk-full on every connection while preserving the real owner's
/// exact connection options. Refuse pools outside the four-connection profile.
pub async fn open_operation_page_limited_pool(
    owner_pool: &SqlitePool,
    maximum_pages: NonZeroU32,
) -> Result<SqlitePool, Error> {
    if owner_pool.options().get_max_connections() != 4 {
        return Err(Error::Protocol(
            "storage fault requires four-connection owner profile".to_string(),
        ));
    }
    let options = owner_pool
        .connect_options()
        .as_ref()
        .clone()
        .pragma("max_page_count", maximum_pages.to_string());
    SqlitePoolOptions::new()
        .max_connections(4)
        .min_connections(4)
        .connect_with(options)
        .await
}

/// Open exactly one existing fixture for deliberate migration-lineage tampering.
/// Missing history is never created by this helper.
pub async fn open_existing_operation_fixture(path: &Path) -> Result<SqlitePool, Error> {
    SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(
            SqliteConnectOptions::new()
                .filename(path)
                .create_if_missing(false)
                .log_statements(LevelFilter::Off),
        )
        .await
}
