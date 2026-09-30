//! Retry-safe bootstrap for the database/checkpoint pair.
//!
//! The only repairable partial state is a database created by the current
//! migration set that contains no authoritative facts, no local checkpoint,
//! no pending frontier change, no dirty frontier and no recovery work. Any
//! other one-sided state fails closed. This is intentionally not a general
//! witness reconstruction API.

use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use sqlx::Row;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityHost;
use crate::AuthBusAuthorityStore;
use crate::owner_fence::OwnerFence;

const EXPECTED_AUTHBUS_MIGRATIONS: i64 = 7;
const AUTHORITATIVE_TABLES: &[&str] = &[
    "authbus_trusted_time",
    "authbus_policy",
    "authbus_policy_history",
    "authbus_policy_archive",
    "authbus_quota_registry",
    "authbus_quota_reservation",
    "authbus_quota_reservation_archive",
    "authbus_issuer_registry",
];

/// Open an already complete pair, create a new pair, or safely retry a failed
/// first bootstrap that left only a provably empty database.
///
/// A checkpoint without a database, a database containing any authoritative
/// row, a local checkpoint row, pending frontier work, a dirty marker or a
/// recovery marker is never repaired. Those states require matched restore or
/// an explicit incident decision.
pub async fn bootstrap_retryable(
    database_path: &Path,
    checkpoint_path: PathBuf,
    owner_id: &str,
) -> Result<AuthBusAuthorityHost, AuthBusAuthorityError> {
    if !database_path.is_absolute() || !checkpoint_path.is_absolute() {
        return Err(AuthBusAuthorityError::InvalidInput(
            "AuthBus bootstrap paths must be absolute",
        ));
    }
    let database_exists = path_exists(database_path)?;
    let checkpoint_exists = path_exists(&checkpoint_path)?;
    match (database_exists, checkpoint_exists) {
        (false, false) => {
            AuthBusAuthorityHost::bootstrap(database_path, checkpoint_path, owner_id).await
        }
        (true, true) => {
            AuthBusAuthorityHost::open(database_path, checkpoint_path, owner_id).await
        }
        (false, true) => Err(AuthBusAuthorityError::RollbackDetected),
        (true, false) => {
            validate_checkpoint_parent(&checkpoint_path, database_path)?;
            remove_pristine_database_orphan(database_path, owner_id).await?;
            AuthBusAuthorityHost::bootstrap(database_path, checkpoint_path, owner_id).await
        }
    }
}

async fn remove_pristine_database_orphan(
    database_path: &Path,
    owner_id: &str,
) -> Result<(), AuthBusAuthorityError> {
    let fence = OwnerFence::acquire(database_path, owner_id).await?;
    let options = SqliteConnectOptions::new()
        .filename(database_path)
        .create_if_missing(false)
        .read_only(true)
        .foreign_keys(true)
        .busy_timeout(Duration::from_secs(5));
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(options)
        .await
        .map_err(storage)?;

    let inspection = async {
        let quick_check: String = sqlx::query_scalar("PRAGMA quick_check")
            .fetch_one(&pool)
            .await
            .map_err(storage)?;
        if quick_check != "ok" {
            return Err(AuthBusAuthorityError::RollbackDetected);
        }
        let migration: (i64, Option<i64>, Option<i64>, i64) = sqlx::query_as(
            "SELECT COUNT(*), MIN(version), MAX(version),
                    COALESCE(SUM(CASE WHEN success = 1 THEN 0 ELSE 1 END), 0)
             FROM _sqlx_migrations",
        )
        .fetch_one(&pool)
        .await
        .map_err(storage)?;
        if migration
            != (
                EXPECTED_AUTHBUS_MIGRATIONS,
                Some(1),
                Some(EXPECTED_AUTHBUS_MIGRATIONS),
                0,
            )
        {
            return Err(AuthBusAuthorityError::RollbackDetected);
        }
        for table in AUTHORITATIVE_TABLES {
            let query = format!("SELECT COUNT(*) FROM {table}");
            let count: i64 = sqlx::query_scalar(&query)
                .fetch_one(&pool)
                .await
                .map_err(storage)?;
            if count != 0 {
                return Err(AuthBusAuthorityError::RollbackDetected);
            }
        }
        let local_checkpoint: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM authbus_authority_checkpoint")
                .fetch_one(&pool)
                .await
                .map_err(storage)?;
        let pending_frontier: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM authbus_frontier_change")
                .fetch_one(&pool)
                .await
                .map_err(storage)?;
        let dirty: (i64, i64) = sqlx::query_as(
            "SELECT singleton, dirty
             FROM authbus_authority_checkpoint_dirty",
        )
        .fetch_one(&pool)
        .await
        .map_err(storage)?;
        let recovery: (i64, i64) = sqlx::query_as(
            "SELECT singleton, recovery_required FROM authbus_recovery_state",
        )
        .fetch_one(&pool)
        .await
        .map_err(storage)?;
        let accumulator = sqlx::query(
            "SELECT singleton, schema_version, length(root_digest), applied_change_id
             FROM authbus_frontier_accumulator",
        )
        .fetch_one(&pool)
        .await
        .map_err(storage)?;
        let root_len: Option<i64> = accumulator.try_get(2).map_err(storage)?;
        if local_checkpoint != 0
            || pending_frontier != 0
            || dirty != (1, 0)
            || recovery != (1, 0)
            || accumulator.try_get::<i64, _>(0).map_err(storage)? != 1
            || accumulator.try_get::<i64, _>(1).map_err(storage)? != 1
            || !matches!(root_len, None | Some(32))
            || accumulator.try_get::<i64, _>(3).map_err(storage)? != 0
        {
            return Err(AuthBusAuthorityError::RollbackDetected);
        }
        Ok(())
    }
    .await;
    pool.close().await;
    inspection?;

    // Re-open through the production store before deleting anything. This runs
    // exact live-schema verification, migration checksum validation and file
    // hardening. It may seed the empty frontier, which remains repairable.
    let store = AuthBusAuthorityStore::open(database_path).await?;
    if store.authority_checkpoint().await?.is_some()
        || store.recovery_required().await?
        || store.authority_frontier_digest().await?.is_zero()
    {
        store.pool.close().await;
        return Err(AuthBusAuthorityError::RollbackDetected);
    }
    store.pool.close().await;

    for suffix in ["-wal", "-shm", "-journal"] {
        remove_optional(&sidecar(database_path, suffix))?;
    }
    std::fs::remove_file(database_path).map_err(storage_io)?;
    sync_parent(database_path)?;
    drop(fence);
    Ok(())
}

fn path_exists(path: &Path) -> Result<bool, AuthBusAuthorityError> {
    path.try_exists().map_err(storage_io)
}

fn sidecar(database_path: &Path, suffix: &str) -> PathBuf {
    let mut raw = database_path.as_os_str().to_os_string();
    raw.push(suffix);
    PathBuf::from(raw)
}

fn remove_optional(path: &Path) -> Result<(), AuthBusAuthorityError> {
    match std::fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(storage_io(error)),
    }
}

#[cfg(unix)]
fn validate_checkpoint_parent(
    checkpoint_path: &Path,
    database_path: &Path,
) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    let checkpoint_parent = checkpoint_path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?
        .canonicalize()
        .map_err(storage_io)?;
    let database_parent = database_path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?
        .canonicalize()
        .map_err(storage_io)?;
    let metadata = std::fs::metadata(&checkpoint_parent).map_err(storage_io)?;
    if checkpoint_parent == database_parent
        || !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_checkpoint_parent(
    _checkpoint_path: &Path,
    _database_path: &Path,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn sync_parent(path: &Path) -> Result<(), AuthBusAuthorityError> {
    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    std::fs::File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(storage_io)
}

#[cfg(not(unix))]
fn sync_parent(_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

fn storage(error: sqlx::Error) -> AuthBusAuthorityError {
    AuthBusAuthorityError::Storage(error.to_string())
}

fn storage_io(error: std::io::Error) -> AuthBusAuthorityError {
    AuthBusAuthorityError::Storage(error.to_string())
}

#[cfg(all(test, unix))]
mod tests {
    use std::os::unix::fs::PermissionsExt;

    use super::*;

    fn private_paths() -> (tempfile::TempDir, PathBuf, PathBuf) {
        let root = tempfile::tempdir().expect("temporary root");
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
            .expect("private root");
        let database_parent = root.path().join("database");
        let checkpoint_parent = root.path().join("checkpoint");
        std::fs::create_dir_all(&database_parent).expect("database parent");
        std::fs::create_dir_all(&checkpoint_parent).expect("checkpoint parent");
        std::fs::set_permissions(&database_parent, std::fs::Permissions::from_mode(0o700))
            .expect("private database parent");
        std::fs::set_permissions(&checkpoint_parent, std::fs::Permissions::from_mode(0o700))
            .expect("private checkpoint parent");
        (
            root,
            database_parent.join("authority.sqlite"),
            checkpoint_parent.join("authority.checkpoint.json"),
        )
    }

    #[tokio::test]
    async fn repairs_only_a_pristine_database_orphan() {
        let (_root, database, checkpoint) = private_paths();
        let store = AuthBusAuthorityStore::open(&database)
            .await
            .expect("create migrated orphan");
        let _ = store
            .authority_frontier_digest()
            .await
            .expect("seed empty frontier");
        store.pool.close().await;

        let host = bootstrap_retryable(&database, checkpoint.clone(), "owner:bootstrap")
            .await
            .expect("retry bootstrap");
        drop(host);
        assert!(database.exists());
        assert!(checkpoint.exists());

        let reopened = bootstrap_retryable(&database, checkpoint, "owner:bootstrap")
            .await
            .expect("completed bootstrap is idempotent");
        drop(reopened);
    }

    #[tokio::test]
    async fn refuses_an_orphan_with_authoritative_content() {
        let (_root, database, checkpoint) = private_paths();
        let store = AuthBusAuthorityStore::open(&database)
            .await
            .expect("create migrated orphan");
        let one = 1_u64.to_be_bytes().to_vec();
        sqlx::query(
            "INSERT INTO authbus_trusted_time
             (singleton, wall_time_ms, source_revision, source_digest)
             VALUES (1, ?, ?, ?)",
        )
        .bind(&one)
        .bind(&one)
        .bind(vec![7_u8; 32])
        .execute(&store.pool)
        .await
        .expect("authoritative row");
        store.pool.close().await;

        assert!(matches!(
            bootstrap_retryable(&database, checkpoint, "owner:bootstrap").await,
            Err(AuthBusAuthorityError::RollbackDetected)
        ));
        assert!(database.exists());
    }

    #[tokio::test]
    async fn refuses_checkpoint_without_database() {
        let (_root, database, checkpoint) = private_paths();
        std::fs::write(&checkpoint, b"not a reconstructible checkpoint")
            .expect("checkpoint-only fixture");
        std::fs::set_permissions(&checkpoint, std::fs::Permissions::from_mode(0o600))
            .expect("private checkpoint");
        assert!(matches!(
            bootstrap_retryable(&database, checkpoint, "owner:bootstrap").await,
            Err(AuthBusAuthorityError::RollbackDetected)
        ));
    }
}
