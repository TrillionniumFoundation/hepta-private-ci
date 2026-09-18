//! Atomic replay-claim backends for final-use authority.
//!
//! The legacy final-use store keeps replay claims in one local JSON snapshot.
//! This module provides the production-facing atomic replay boundary and a
//! durable SQLite implementation suitable for multiple local processes. Fleet
//! deployments may provide a strongly-consistent distributed implementation of
//! the same trait; the authority library does not infer cross-node consistency
//! from a shared filesystem.

use std::fmt;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use rusqlite::Connection;
use rusqlite::OpenFlags;
use rusqlite::OptionalExtension;
use rusqlite::TransactionBehavior;
use rusqlite::params;

const REPLAY_DB_FILENAME: &str = "final_use_replay.sqlite3";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityReplayClaim {
    Claimed,
    AlreadyClaimed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityReplayEpochAdvance {
    Advanced,
    AlreadyAtTarget,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityReplayError {
    Invalid,
    Conflict,
    EpochMismatch,
    Unavailable,
}

impl fmt::Display for AuthorityReplayError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for AuthorityReplayError {}

/// Strongly consistent replay owner for one final-use authority identity.
///
/// claim must be atomic across all authority replicas that share the owner
/// identity. A successful claim is durable before it returns. There is no
/// library-imposed per-epoch claim cap on this interface; concrete backends may
/// expose operational quotas separately, but they must never evict live claims
/// silently.
///
/// advance_epoch is monotonic. Once it reports Advanced or AlreadyAtTarget,
/// claims for an older epoch must fail with EpochMismatch.
pub trait AuthorityReplayStore: Send + Sync {
    fn current_epoch(&self, owner_id: &str) -> Result<u64, AuthorityReplayError>;

    fn claim(
        &self,
        owner_id: &str,
        authority_epoch: u64,
        nonce: [u8; 32],
    ) -> Result<AuthorityReplayClaim, AuthorityReplayError>;

    fn claimed_count(
        &self,
        owner_id: &str,
        authority_epoch: u64,
    ) -> Result<u64, AuthorityReplayError>;

    fn advance_epoch(
        &self,
        owner_id: &str,
        expected_epoch: u64,
        next_epoch: u64,
    ) -> Result<AuthorityReplayEpochAdvance, AuthorityReplayError>;
}

/// Durable local multi-process replay ledger.
///
/// This implementation uses SQLite uniqueness and BEGIN IMMEDIATE rather
/// than a process-lifetime file lock. Multiple processes may open the same
/// private replay directory and atomically race the same nonce. The directory
/// must still be local/qualified storage; SQLite on an arbitrary NFS/share is
/// not a distributed-consensus backend.
///
/// Cross-host active-active deployments should implement AuthorityReplayStore
/// over a strongly-consistent transactional service.
#[derive(Clone, Debug)]
pub struct SqliteAuthorityReplayStore {
    path: PathBuf,
}

impl SqliteAuthorityReplayStore {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, AuthorityReplayError> {
        let root = root.as_ref();
        prepare_private_directory(root)?;
        let path = root.join(REPLAY_DB_FILENAME);
        let store = Self { path };
        {
            let connection = store.connection()?;
            connection
                .execute_batch(
                    "
                    CREATE TABLE IF NOT EXISTS final_use_replay_meta (
                        owner_id TEXT PRIMARY KEY,
                        authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0)
                    );
                    CREATE TABLE IF NOT EXISTS final_use_replay_claims (
                        owner_id TEXT NOT NULL,
                        authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
                        nonce BLOB NOT NULL CHECK (length(nonce) = 32),
                        PRIMARY KEY (owner_id, authority_epoch, nonce)
                    ) WITHOUT ROWID;
                    CREATE INDEX IF NOT EXISTS final_use_replay_epoch_idx
                        ON final_use_replay_claims(owner_id, authority_epoch);
                    ",
                )
                .map_err(unavailable)?;
        }
        protect_database_file(&store.path)?;
        Ok(store)
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Explicit trusted provisioning. Authority constructors never call this
    /// implicitly, so deleting/replacing a replay database cannot silently
    /// manufacture an empty replay epoch.
    pub fn provision_owner_exact(
        &self,
        owner_id: &str,
        authority_epoch: u64,
    ) -> Result<(), AuthorityReplayError> {
        validate_owner(owner_id)?;
        let epoch = to_i64(authority_epoch)?;
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(unavailable)?;
        let existing: Option<i64> = transaction
            .query_row(
                "SELECT authority_epoch FROM final_use_replay_meta WHERE owner_id = ?1",
                params![owner_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(unavailable)?;
        match existing {
            Some(current) if current == epoch => {}
            Some(_) => return Err(AuthorityReplayError::Conflict),
            None => {
                transaction
                    .execute(
                        "INSERT INTO final_use_replay_meta(owner_id, authority_epoch)
                         VALUES (?1, ?2)",
                        params![owner_id, epoch],
                    )
                    .map_err(unavailable)?;
            }
        }
        transaction.commit().map_err(unavailable)
    }

    /// Retired epochs are not consulted by admission. This explicit maintenance
    /// operation may delete them after the trusted epoch frontier has advanced.
    /// It is never called from the claim hot path.
    pub fn prune_retired_epochs(&self, owner_id: &str) -> Result<u64, AuthorityReplayError> {
        validate_owner(owner_id)?;
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(unavailable)?;
        let current: i64 = transaction
            .query_row(
                "SELECT authority_epoch FROM final_use_replay_meta WHERE owner_id = ?1",
                params![owner_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(unavailable)?
            .ok_or(AuthorityReplayError::Invalid)?;
        let changed = transaction
            .execute(
                "DELETE FROM final_use_replay_claims
                 WHERE owner_id = ?1 AND authority_epoch < ?2",
                params![owner_id, current],
            )
            .map_err(unavailable)?;
        transaction.commit().map_err(unavailable)?;
        u64::try_from(changed).map_err(|_| AuthorityReplayError::Unavailable)
    }

    fn connection(&self) -> Result<Connection, AuthorityReplayError> {
        let connection = Connection::open_with_flags(
            &self.path,
            OpenFlags::SQLITE_OPEN_READ_WRITE
                | OpenFlags::SQLITE_OPEN_CREATE
                | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .map_err(unavailable)?;
        connection
            .busy_timeout(Duration::from_secs(5))
            .map_err(unavailable)?;
        connection
            .pragma_update(None, "journal_mode", "WAL")
            .map_err(unavailable)?;
        connection
            .pragma_update(None, "synchronous", "FULL")
            .map_err(unavailable)?;
        connection
            .pragma_update(None, "foreign_keys", "ON")
            .map_err(unavailable)?;
        Ok(connection)
    }
}

impl AuthorityReplayStore for SqliteAuthorityReplayStore {
    fn current_epoch(&self, owner_id: &str) -> Result<u64, AuthorityReplayError> {
        validate_owner(owner_id)?;
        let connection = self.connection()?;
        let epoch: i64 = connection
            .query_row(
                "SELECT authority_epoch FROM final_use_replay_meta WHERE owner_id = ?1",
                params![owner_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(unavailable)?
            .ok_or(AuthorityReplayError::Invalid)?;
        to_u64(epoch)
    }

    fn claim(
        &self,
        owner_id: &str,
        authority_epoch: u64,
        nonce: [u8; 32],
    ) -> Result<AuthorityReplayClaim, AuthorityReplayError> {
        validate_owner(owner_id)?;
        if nonce == [0; 32] {
            return Err(AuthorityReplayError::Invalid);
        }
        let epoch = to_i64(authority_epoch)?;
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(unavailable)?;
        let current: i64 = transaction
            .query_row(
                "SELECT authority_epoch FROM final_use_replay_meta WHERE owner_id = ?1",
                params![owner_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(unavailable)?
            .ok_or(AuthorityReplayError::Invalid)?;
        if current != epoch {
            return Err(AuthorityReplayError::EpochMismatch);
        }
        let changed = transaction
            .execute(
                "INSERT OR IGNORE INTO final_use_replay_claims(
                    owner_id, authority_epoch, nonce
                 ) VALUES (?1, ?2, ?3)",
                params![owner_id, epoch, nonce.as_slice()],
            )
            .map_err(unavailable)?;
        transaction.commit().map_err(unavailable)?;
        match changed {
            1 => Ok(AuthorityReplayClaim::Claimed),
            0 => Ok(AuthorityReplayClaim::AlreadyClaimed),
            _ => Err(AuthorityReplayError::Unavailable),
        }
    }

    fn claimed_count(
        &self,
        owner_id: &str,
        authority_epoch: u64,
    ) -> Result<u64, AuthorityReplayError> {
        validate_owner(owner_id)?;
        let epoch = to_i64(authority_epoch)?;
        let connection = self.connection()?;
        let count: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM final_use_replay_claims
                 WHERE owner_id = ?1 AND authority_epoch = ?2",
                params![owner_id, epoch],
                |row| row.get(0),
            )
            .map_err(unavailable)?;
        to_u64(count)
    }

    fn advance_epoch(
        &self,
        owner_id: &str,
        expected_epoch: u64,
        next_epoch: u64,
    ) -> Result<AuthorityReplayEpochAdvance, AuthorityReplayError> {
        validate_owner(owner_id)?;
        if expected_epoch == 0 || next_epoch <= expected_epoch {
            return Err(AuthorityReplayError::Invalid);
        }
        let expected = to_i64(expected_epoch)?;
        let next = to_i64(next_epoch)?;
        let mut connection = self.connection()?;
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(unavailable)?;
        let current: i64 = transaction
            .query_row(
                "SELECT authority_epoch FROM final_use_replay_meta WHERE owner_id = ?1",
                params![owner_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(unavailable)?
            .ok_or(AuthorityReplayError::Invalid)?;
        if current == next {
            transaction.commit().map_err(unavailable)?;
            return Ok(AuthorityReplayEpochAdvance::AlreadyAtTarget);
        }
        if current != expected {
            return Err(AuthorityReplayError::Conflict);
        }
        let changed = transaction
            .execute(
                "UPDATE final_use_replay_meta
                 SET authority_epoch = ?1
                 WHERE owner_id = ?2 AND authority_epoch = ?3",
                params![next, owner_id, expected],
            )
            .map_err(unavailable)?;
        if changed != 1 {
            return Err(AuthorityReplayError::Conflict);
        }
        transaction.commit().map_err(unavailable)?;
        Ok(AuthorityReplayEpochAdvance::Advanced)
    }
}

fn validate_owner(value: &str) -> Result<(), AuthorityReplayError> {
    if value.is_empty()
        || value.len() > 128
        || value == "."
        || value == ".."
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
    {
        Err(AuthorityReplayError::Invalid)
    } else {
        Ok(())
    }
}

fn to_i64(value: u64) -> Result<i64, AuthorityReplayError> {
    i64::try_from(value).map_err(|_| AuthorityReplayError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, AuthorityReplayError> {
    u64::try_from(value).map_err(|_| AuthorityReplayError::Unavailable)
}

fn unavailable(_error: impl fmt::Display) -> AuthorityReplayError {
    AuthorityReplayError::Unavailable
}

fn prepare_private_directory(path: &Path) -> Result<(), AuthorityReplayError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;

        if let Err(error) = fs::DirBuilder::new().mode(0o700).create(path)
            && error.kind() != std::io::ErrorKind::AlreadyExists
        {
            return Err(AuthorityReplayError::Unavailable);
        }
        let metadata = fs::symlink_metadata(path).map_err(unavailable)?;
        if !metadata.is_dir()
            || metadata.file_type().is_symlink()
            || metadata.mode() & 0o077 != 0
            || metadata.uid() != rustix::process::geteuid().as_raw()
        {
            return Err(AuthorityReplayError::Invalid);
        }
        fs::set_permissions(path, fs::Permissions::from_mode(0o700)).map_err(unavailable)?;
        Ok(())
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        Err(AuthorityReplayError::Invalid)
    }
}

fn protect_database_file(path: &Path) -> Result<(), AuthorityReplayError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;

        let metadata = fs::symlink_metadata(path).map_err(unavailable)?;
        if !metadata.is_file()
            || metadata.file_type().is_symlink()
            || metadata.nlink() != 1
            || metadata.uid() != rustix::process::geteuid().as_raw()
        {
            return Err(AuthorityReplayError::Invalid);
        }
        fs::set_permissions(path, fs::Permissions::from_mode(0o600)).map_err(unavailable)?;
        Ok(())
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        Err(AuthorityReplayError::Invalid)
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    #[test]
    fn two_handles_share_atomic_claim_truth_without_process_lock() {
        let directory = tempfile::tempdir().unwrap();
        let first = SqliteAuthorityReplayStore::open(directory.path()).unwrap();
        first.provision_owner_exact("owner", 7).unwrap();
        let second = SqliteAuthorityReplayStore::open(directory.path()).unwrap();

        assert_eq!(
            first.claim("owner", 7, [1; 32]).unwrap(),
            AuthorityReplayClaim::Claimed
        );
        assert_eq!(
            second.claim("owner", 7, [1; 32]).unwrap(),
            AuthorityReplayClaim::AlreadyClaimed
        );
        assert_eq!(
            second.claim("owner", 7, [2; 32]).unwrap(),
            AuthorityReplayClaim::Claimed
        );
        assert_eq!(first.claimed_count("owner", 7).unwrap(), 2);
    }

    #[test]
    fn epoch_advance_fences_old_claims_and_retired_rows_prune_off_hot_path() {
        let directory = tempfile::tempdir().unwrap();
        let store = SqliteAuthorityReplayStore::open(directory.path()).unwrap();
        store.provision_owner_exact("owner", 3).unwrap();
        assert_eq!(
            store.claim("owner", 3, [3; 32]).unwrap(),
            AuthorityReplayClaim::Claimed
        );
        assert_eq!(
            store.advance_epoch("owner", 3, 4).unwrap(),
            AuthorityReplayEpochAdvance::Advanced
        );
        assert_eq!(
            store.advance_epoch("owner", 3, 4).unwrap(),
            AuthorityReplayEpochAdvance::AlreadyAtTarget
        );
        assert_eq!(
            store.claim("owner", 3, [4; 32]),
            Err(AuthorityReplayError::EpochMismatch)
        );
        assert_eq!(
            store.claim("owner", 4, [4; 32]).unwrap(),
            AuthorityReplayClaim::Claimed
        );
        assert_eq!(store.prune_retired_epochs("owner").unwrap(), 1);
        assert_eq!(store.claimed_count("owner", 3).unwrap(), 0);
        assert_eq!(store.claimed_count("owner", 4).unwrap(), 1);
    }
}
