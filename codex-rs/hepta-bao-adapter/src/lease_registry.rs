//! Durable local owner for HeptaBao lease identities and operation quarantine.
//!
//! The provider remains authoritative for lease validity. This registry owns
//! only the host's recovery facts: which operation was attempted, whether its
//! outcome is known, and the opaque provider lease ID required for later
//! lookup/revoke after a restart.

use std::fmt;
use std::path::Path;
use std::path::PathBuf;

use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

use crate::SecretLeaseHandle;
use crate::SecretLeaseMetadata;
use crate::SecretLeaseRenewal;

const REGISTRY_FILENAME: &str = "heptabao-leases.sqlite3";

#[derive(Clone)]
pub struct SecretLeaseRegistry {
    pool: SqlitePool,
    path: PathBuf,
}

impl fmt::Debug for SecretLeaseRegistry {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("SecretLeaseRegistry([PRIVATE DURABLE STATE])")
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SecretLeaseRegistryError {
    UnsafeDirectory,
    Unavailable,
    OperationAlreadyRecorded,
    StateConflict,
}

impl fmt::Display for SecretLeaseRegistryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for SecretLeaseRegistryError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SecretLeaseOperationState {
    Pending,
    Applied,
    Rejected,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RegisteredSecretLeaseState {
    Active,
    Revoked,
}

pub struct RegisteredSecretLease {
    pub handle: SecretLeaseHandle,
    pub namespace: String,
    pub expires_at_unix_ms: u64,
    pub renewable: bool,
    pub state: RegisteredSecretLeaseState,
}

impl fmt::Debug for RegisteredSecretLease {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("RegisteredSecretLease")
            .field("handle", &self.handle)
            .field("namespace", &self.namespace)
            .field("expires_at_unix_ms", &self.expires_at_unix_ms)
            .field("renewable", &self.renewable)
            .field("state", &self.state)
            .finish()
    }
}

impl SecretLeaseRegistry {
    /// Open or create one owner-private durable registry.
    ///
    /// The directory is required to be private before the database is opened.
    /// SQLite uses DELETE journaling and FULL synchronous mode so no WAL side
    /// file becomes an untracked lease-identity store.
    pub async fn open(directory: &Path) -> Result<Self, SecretLeaseRegistryError> {
        prepare_private_directory(directory)?;
        let path = directory.join(REGISTRY_FILENAME);
        prepare_private_database_file(&path)?;

        let options = SqliteConnectOptions::new()
            .filename(&path)
            .create_if_missing(true)
            .foreign_keys(true)
            .journal_mode(SqliteJournalMode::Delete)
            .synchronous(SqliteSynchronous::Full);
        let pool = SqlitePoolOptions::new()
            .max_connections(1)
            .connect_with(options)
            .await
            .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        verify_private_database_file(&path)?;
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS heptabao_lease_operations (
                operation_sha256 BLOB PRIMARY KEY NOT NULL CHECK(length(operation_sha256) = 32),
                kind TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending','applied','rejected','indeterminate')),
                lease_id_sha256 BLOB NULL CHECK(lease_id_sha256 IS NULL OR length(lease_id_sha256) = 32),
                updated_at_unix_ms INTEGER NOT NULL
            )",
        )
        .execute(&pool)
        .await
        .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS heptabao_secret_leases (
                lease_id_sha256 BLOB PRIMARY KEY NOT NULL CHECK(length(lease_id_sha256) = 32),
                lease_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                expires_at_unix_ms INTEGER NOT NULL,
                renewable INTEGER NOT NULL CHECK(renewable IN (0,1)),
                state TEXT NOT NULL CHECK(state IN ('active','revoked')),
                updated_at_unix_ms INTEGER NOT NULL
            )",
        )
        .execute(&pool)
        .await
        .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        Ok(Self { pool, path })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Persist the operation before crossing the provider mutation boundary.
    ///
    /// A repeated occurrence is refused even when the earlier result was
    /// indeterminate. This is the local no-blind-retry fence across restart.
    pub async fn begin_operation(
        &self,
        operation_sha256: [u8; 32],
        kind: &str,
        now_unix_ms: u64,
    ) -> Result<(), SecretLeaseRegistryError> {
        let changed = sqlx::query(
            "INSERT OR IGNORE INTO heptabao_lease_operations
             (operation_sha256, kind, state, lease_id_sha256, updated_at_unix_ms)
             VALUES (?, ?, 'pending', NULL, ?)",
        )
        .bind(operation_sha256.to_vec())
        .bind(kind)
        .bind(as_i64(now_unix_ms)?)
        .execute(&self.pool)
        .await
        .map_err(|_| SecretLeaseRegistryError::Unavailable)?
        .rows_affected();
        if changed != 1 {
            return Err(SecretLeaseRegistryError::OperationAlreadyRecorded);
        }
        Ok(())
    }

    pub async fn mark_indeterminate(
        &self,
        operation_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<(), SecretLeaseRegistryError> {
        self.finish_without_lease(operation_sha256, "indeterminate", now_unix_ms)
            .await
    }

    pub async fn mark_rejected(
        &self,
        operation_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<(), SecretLeaseRegistryError> {
        self.finish_without_lease(operation_sha256, "rejected", now_unix_ms)
            .await
    }

    /// Persist a provider-issued handle before secret callback entry.
    pub async fn record_issued(
        &self,
        operation_sha256: [u8; 32],
        handle: &SecretLeaseHandle,
        namespace: &str,
        metadata: &SecretLeaseMetadata,
        now_unix_ms: u64,
    ) -> Result<(), SecretLeaseRegistryError> {
        let lease_digest = handle.lease_id_sha256();
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        if let Some(row) = sqlx::query(
            "SELECT lease_id FROM heptabao_secret_leases WHERE lease_id_sha256 = ?",
        )
        .bind(lease_digest.to_vec())
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| SecretLeaseRegistryError::Unavailable)?
        {
            let existing: String = row
                .try_get("lease_id")
                .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
            if existing != handle.0.as_str() {
                return Err(SecretLeaseRegistryError::StateConflict);
            }
        } else {
            sqlx::query(
                "INSERT INTO heptabao_secret_leases
                 (lease_id_sha256, lease_id, namespace, expires_at_unix_ms, renewable, state, updated_at_unix_ms)
                 VALUES (?, ?, ?, ?, ?, 'active', ?)",
            )
            .bind(lease_digest.to_vec())
            .bind(handle.0.as_str())
            .bind(namespace)
            .bind(as_i64(metadata.expires_at_unix_ms)?)
            .bind(if metadata.renewable { 1_i64 } else { 0_i64 })
            .bind(as_i64(now_unix_ms)?)
            .execute(&mut *tx)
            .await
            .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        }
        let changed = sqlx::query(
            "UPDATE heptabao_lease_operations
             SET state='applied', lease_id_sha256=?, updated_at_unix_ms=?
             WHERE operation_sha256=? AND state='pending'",
        )
        .bind(lease_digest.to_vec())
        .bind(as_i64(now_unix_ms)?)
        .bind(operation_sha256.to_vec())
        .execute(&mut *tx)
        .await
        .map_err(|_| SecretLeaseRegistryError::Unavailable)?
        .rows_affected();
        if changed != 1 {
            return Err(SecretLeaseRegistryError::StateConflict);
        }
        tx.commit()
            .await
            .map_err(|_| SecretLeaseRegistryError::Unavailable)
    }

    pub async fn record_renewed(
        &self,
        operation_sha256: [u8; 32],
        lease_id_sha256: [u8; 32],
        renewal: &SecretLeaseRenewal,
        now_unix_ms: u64,
    ) -> Result<(), SecretLeaseRegistryError> {
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        let lease_changed = sqlx::query(
            "UPDATE heptabao_secret_leases
             SET expires_at_unix_ms=?, renewable=?, state='active', updated_at_unix_ms=?
             WHERE lease_id_sha256=?",
        )
        .bind(as_i64(renewal.expires_at_unix_ms)?)
        .bind(if renewal.renewable { 1_i64 } else { 0_i64 })
        .bind(as_i64(now_unix_ms)?)
        .bind(lease_id_sha256.to_vec())
        .execute(&mut *tx)
        .await
        .map_err(|_| SecretLeaseRegistryError::Unavailable)?
        .rows_affected();
        if lease_changed != 1 {
            return Err(SecretLeaseRegistryError::StateConflict);
        }
        finish_operation_tx(
            &mut tx,
            operation_sha256,
            "applied",
            Some(lease_id_sha256),
            now_unix_ms,
        )
        .await?;
        tx.commit()
            .await
            .map_err(|_| SecretLeaseRegistryError::Unavailable)
    }

    pub async fn record_revoked(
        &self,
        operation_sha256: [u8; 32],
        lease_id_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<(), SecretLeaseRegistryError> {
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        let lease_changed = sqlx::query(
            "UPDATE heptabao_secret_leases
             SET state='revoked', updated_at_unix_ms=?
             WHERE lease_id_sha256=?",
        )
        .bind(as_i64(now_unix_ms)?)
        .bind(lease_id_sha256.to_vec())
        .execute(&mut *tx)
        .await
        .map_err(|_| SecretLeaseRegistryError::Unavailable)?
        .rows_affected();
        if lease_changed != 1 {
            return Err(SecretLeaseRegistryError::StateConflict);
        }
        finish_operation_tx(
            &mut tx,
            operation_sha256,
            "applied",
            Some(lease_id_sha256),
            now_unix_ms,
        )
        .await?;
        tx.commit()
            .await
            .map_err(|_| SecretLeaseRegistryError::Unavailable)
    }


    pub async fn observe_active(
        &self,
        lease_id_sha256: [u8; 32],
        expires_at_unix_ms: u64,
        renewable: bool,
        now_unix_ms: u64,
    ) -> Result<(), SecretLeaseRegistryError> {
        let changed = sqlx::query(
            "UPDATE heptabao_secret_leases
             SET expires_at_unix_ms=?, renewable=?, state='active', updated_at_unix_ms=?
             WHERE lease_id_sha256=?",
        )
        .bind(as_i64(expires_at_unix_ms)?)
        .bind(if renewable { 1_i64 } else { 0_i64 })
        .bind(as_i64(now_unix_ms)?)
        .bind(lease_id_sha256.to_vec())
        .execute(&self.pool)
        .await
        .map_err(|_| SecretLeaseRegistryError::Unavailable)?
        .rows_affected();
        if changed != 1 {
            return Err(SecretLeaseRegistryError::StateConflict);
        }
        Ok(())
    }

    pub async fn observe_absent(
        &self,
        lease_id_sha256: [u8; 32],
        now_unix_ms: u64,
    ) -> Result<(), SecretLeaseRegistryError> {
        let changed = sqlx::query(
            "UPDATE heptabao_secret_leases
             SET state='revoked', updated_at_unix_ms=?
             WHERE lease_id_sha256=?",
        )
        .bind(as_i64(now_unix_ms)?)
        .bind(lease_id_sha256.to_vec())
        .execute(&self.pool)
        .await
        .map_err(|_| SecretLeaseRegistryError::Unavailable)?
        .rows_affected();
        if changed != 1 {
            return Err(SecretLeaseRegistryError::StateConflict);
        }
        Ok(())
    }

    pub async fn operation_state(
        &self,
        operation_sha256: [u8; 32],
    ) -> Result<Option<SecretLeaseOperationState>, SecretLeaseRegistryError> {
        let row = sqlx::query(
            "SELECT state FROM heptabao_lease_operations WHERE operation_sha256=?",
        )
        .bind(operation_sha256.to_vec())
        .fetch_optional(&self.pool)
        .await
        .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        row.map(|row| {
            let state: String = row
                .try_get("state")
                .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
            parse_operation_state(&state)
        })
        .transpose()
    }

    /// Recover a known opaque lease after process restart.
    pub async fn recover_lease(
        &self,
        lease_id_sha256: [u8; 32],
    ) -> Result<Option<RegisteredSecretLease>, SecretLeaseRegistryError> {
        let row = sqlx::query(
            "SELECT lease_id, namespace, expires_at_unix_ms, renewable, state
             FROM heptabao_secret_leases WHERE lease_id_sha256=?",
        )
        .bind(lease_id_sha256.to_vec())
        .fetch_optional(&self.pool)
        .await
        .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let lease_id: String = row
            .try_get("lease_id")
            .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        let namespace: String = row
            .try_get("namespace")
            .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        let expires: i64 = row
            .try_get("expires_at_unix_ms")
            .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        let renewable: i64 = row
            .try_get("renewable")
            .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        let state: String = row
            .try_get("state")
            .map_err(|_| SecretLeaseRegistryError::Unavailable)?;
        Ok(Some(RegisteredSecretLease {
            handle: SecretLeaseHandle(zeroize::Zeroizing::new(lease_id)),
            namespace,
            expires_at_unix_ms: u64::try_from(expires)
                .map_err(|_| SecretLeaseRegistryError::StateConflict)?,
            renewable: match renewable {
                0 => false,
                1 => true,
                _ => return Err(SecretLeaseRegistryError::StateConflict),
            },
            state: match state.as_str() {
                "active" => RegisteredSecretLeaseState::Active,
                "revoked" => RegisteredSecretLeaseState::Revoked,
                _ => return Err(SecretLeaseRegistryError::StateConflict),
            },
        }))
    }

    async fn finish_without_lease(
        &self,
        operation_sha256: [u8; 32],
        state: &str,
        now_unix_ms: u64,
    ) -> Result<(), SecretLeaseRegistryError> {
        let changed = sqlx::query(
            "UPDATE heptabao_lease_operations
             SET state=?, updated_at_unix_ms=?
             WHERE operation_sha256=? AND state='pending'",
        )
        .bind(state)
        .bind(as_i64(now_unix_ms)?)
        .bind(operation_sha256.to_vec())
        .execute(&self.pool)
        .await
        .map_err(|_| SecretLeaseRegistryError::Unavailable)?
        .rows_affected();
        if changed != 1 {
            return Err(SecretLeaseRegistryError::StateConflict);
        }
        Ok(())
    }
}

async fn finish_operation_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    operation_sha256: [u8; 32],
    state: &str,
    lease_id_sha256: Option<[u8; 32]>,
    now_unix_ms: u64,
) -> Result<(), SecretLeaseRegistryError> {
    let changed = sqlx::query(
        "UPDATE heptabao_lease_operations
         SET state=?, lease_id_sha256=?, updated_at_unix_ms=?
         WHERE operation_sha256=? AND state='pending'",
    )
    .bind(state)
    .bind(lease_id_sha256.map(|value| value.to_vec()))
    .bind(as_i64(now_unix_ms)?)
    .bind(operation_sha256.to_vec())
    .execute(&mut **tx)
    .await
    .map_err(|_| SecretLeaseRegistryError::Unavailable)?
    .rows_affected();
    if changed != 1 {
        return Err(SecretLeaseRegistryError::StateConflict);
    }
    Ok(())
}

fn parse_operation_state(
    state: &str,
) -> Result<SecretLeaseOperationState, SecretLeaseRegistryError> {
    match state {
        "pending" => Ok(SecretLeaseOperationState::Pending),
        "applied" => Ok(SecretLeaseOperationState::Applied),
        "rejected" => Ok(SecretLeaseOperationState::Rejected),
        "indeterminate" => Ok(SecretLeaseOperationState::Indeterminate),
        _ => Err(SecretLeaseRegistryError::StateConflict),
    }
}

fn as_i64(value: u64) -> Result<i64, SecretLeaseRegistryError> {
    i64::try_from(value).map_err(|_| SecretLeaseRegistryError::StateConflict)
}

#[cfg(unix)]
fn prepare_private_database_file(path: &Path) -> Result<(), SecretLeaseRegistryError> {
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;

    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink()
                || !metadata.is_file()
                || metadata.permissions().mode() & 0o077 != 0
            {
                return Err(SecretLeaseRegistryError::UnsafeDirectory);
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            std::fs::OpenOptions::new()
                .create_new(true)
                .write(true)
                .mode(0o600)
                .open(path)
                .map_err(|_| SecretLeaseRegistryError::UnsafeDirectory)?;
        }
        Err(_) => return Err(SecretLeaseRegistryError::UnsafeDirectory),
    }
    Ok(())
}

#[cfg(not(unix))]
fn prepare_private_database_file(_path: &Path) -> Result<(), SecretLeaseRegistryError> {
    Err(SecretLeaseRegistryError::UnsafeDirectory)
}

#[cfg(unix)]
fn prepare_private_directory(path: &Path) -> Result<(), SecretLeaseRegistryError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    if !path.exists() {
        let mut builder = std::fs::DirBuilder::new();
        builder.mode(0o700);
        builder
            .create(path)
            .map_err(|_| SecretLeaseRegistryError::UnsafeDirectory)?;
    }
    let metadata =
        std::fs::symlink_metadata(path).map_err(|_| SecretLeaseRegistryError::UnsafeDirectory)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_dir()
        || metadata.permissions().mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(SecretLeaseRegistryError::UnsafeDirectory);
    }
    Ok(())
}

#[cfg(not(unix))]
fn prepare_private_directory(_path: &Path) -> Result<(), SecretLeaseRegistryError> {
    Err(SecretLeaseRegistryError::UnsafeDirectory)
}

#[cfg(unix)]
fn verify_private_database_file(path: &Path) -> Result<(), SecretLeaseRegistryError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;
    let metadata =
        std::fs::symlink_metadata(path).map_err(|_| SecretLeaseRegistryError::UnsafeDirectory)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.permissions().mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(SecretLeaseRegistryError::UnsafeDirectory);
    }
    Ok(())
}

#[cfg(not(unix))]
fn verify_private_database_file(_path: &Path) -> Result<(), SecretLeaseRegistryError> {
    Err(SecretLeaseRegistryError::UnsafeDirectory)
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use tempfile::TempDir;
    use zeroize::Zeroizing;

    #[tokio::test]
    async fn indeterminate_operation_survives_reopen_and_blocks_duplicate() {
        let temp = TempDir::new().unwrap();
        let registry = SecretLeaseRegistry::open(temp.path()).await.unwrap();
        let operation = [9; 32];
        registry.begin_operation(operation, "issue", 1).await.unwrap();
        registry.mark_indeterminate(operation, 2).await.unwrap();
        drop(registry);

        let reopened = SecretLeaseRegistry::open(temp.path()).await.unwrap();
        assert_eq!(
            reopened.operation_state(operation).await.unwrap(),
            Some(SecretLeaseOperationState::Indeterminate)
        );
        assert_eq!(
            reopened.begin_operation(operation, "issue", 3).await,
            Err(SecretLeaseRegistryError::OperationAlreadyRecorded)
        );
    }

    #[tokio::test]
    async fn issued_handle_is_recoverable_after_reopen() {
        let temp = TempDir::new().unwrap();
        let registry = SecretLeaseRegistry::open(temp.path()).await.unwrap();
        let operation = [7; 32];
        let handle = SecretLeaseHandle(Zeroizing::new("database/creds/role/id".into()));
        let metadata = SecretLeaseMetadata {
            lease_id_sha256: handle.lease_id_sha256(),
            operation_sha256: operation,
            secret_sha256: [3; 32],
            issued_at_unix_ms: 10,
            expires_at_unix_ms: 20,
            renewable: true,
            secret_bytes: 16,
        };
        registry.begin_operation(operation, "issue", 10).await.unwrap();
        registry
            .record_issued(operation, &handle, "team/one", &metadata, 11)
            .await
            .unwrap();
        let digest = handle.lease_id_sha256();
        drop(registry);

        let reopened = SecretLeaseRegistry::open(temp.path()).await.unwrap();
        let recovered = reopened.recover_lease(digest).await.unwrap().unwrap();
        assert_eq!(recovered.handle.lease_id_sha256(), digest);
        assert_eq!(recovered.namespace, "team/one");
        assert_eq!(recovered.state, RegisteredSecretLeaseState::Active);
    }
}
