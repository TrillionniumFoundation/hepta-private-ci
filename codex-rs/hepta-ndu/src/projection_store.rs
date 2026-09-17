//! Crash-bounded durable writer candidate for NDU projection state.
//!
//! The host supplies a private local directory. This module owns only files
//! inside that directory, takes an advisory single-writer lock, validates the
//! complete journal before exposing it, writes a synchronized temporary image,
//! atomically replaces the committed image, and synchronizes the parent
//! directory on Unix before acknowledging a mutation. External enrollment,
//! filesystem trust, backup transport, retention policy, activation and release
//! remain host/governance responsibilities.

use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

use crate::NduProjectionEntryV1;
use crate::NduProjectionJournalError;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;

const LOCK_FILE: &str = ".ndu-projection.lock";
const JOURNAL_FILE: &str = "projection.journal";
const TEMP_FILE: &str = ".projection.journal.tmp";
const MAX_BACKUP_BYTES: usize = 12 + 4096 * (8 + 1 + 32 + 32 + 32 + 32 + 32 + 32);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduProjectionStoreError {
    Busy,
    NotDirectory,
    NotRegular,
    BackupTooLarge,
    BackupRegression,
    Journal(NduProjectionJournalError),
    Io(io::ErrorKind),
    /// The committed rename may have happened but its directory durability
    /// could not be acknowledged. Reopen/reconcile before retrying.
    Indeterminate,
}

impl fmt::Display for NduProjectionStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduProjectionStoreError {}

impl From<io::Error> for NduProjectionStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

impl From<NduProjectionJournalError> for NduProjectionStoreError {
    fn from(error: NduProjectionJournalError) -> Self {
        Self::Journal(error)
    }
}

/// Exclusive writer over one host-authorized projection directory.
///
/// Locks are advisory and therefore assume the directory is private to the
/// authenticated owner. A hostile process that ignores the lock is outside this
/// mechanism's threat model.
pub struct NduProjectionStoreV1 {
    root: PathBuf,
    lock: File,
    journal: NduProjectionJournalV1,
}

impl NduProjectionStoreV1 {
    /// Opens or initializes the V1 store. The directory must already exist so
    /// repository code cannot silently widen filesystem authority.
    pub fn open(root: impl AsRef<Path>) -> Result<Self, NduProjectionStoreError> {
        let root = root.as_ref().to_path_buf();
        let metadata = fs::metadata(&root)?;
        if !metadata.is_dir() {
            return Err(NduProjectionStoreError::NotDirectory);
        }

        let lock_path = root.join(LOCK_FILE);
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&lock_path)?;
        if !lock.metadata()?.is_file() {
            return Err(NduProjectionStoreError::NotRegular);
        }
        match lock.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(NduProjectionStoreError::Busy),
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }

        let temp_path = root.join(TEMP_FILE);
        match fs::remove_file(&temp_path) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }

        let journal_path = root.join(JOURNAL_FILE);
        let journal = match File::open(&journal_path) {
            Ok(mut file) => {
                if !file.metadata()?.is_file() {
                    return Err(NduProjectionStoreError::NotRegular);
                }
                let mut bytes = Vec::new();
                file.read_to_end(&mut bytes)?;
                if bytes.len() > MAX_BACKUP_BYTES {
                    return Err(NduProjectionStoreError::BackupTooLarge);
                }
                NduProjectionJournalV1::reopen(&bytes)?
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                let journal = NduProjectionJournalV1::new();
                persist_image(&root, &journal)?;
                journal
            }
            Err(error) => return Err(error.into()),
        };

        Ok(Self {
            root,
            lock,
            journal,
        })
    }

    #[must_use]
    pub fn entries(&self) -> &[NduProjectionEntryV1] {
        self.journal.entries()
    }

    #[must_use]
    pub fn selected_projection_digest(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Option<Digest32> {
        self.journal
            .selected_projection_digest(objective_digest, subject_digest)
    }

    /// Returns a complete, self-validating backup image. The caller owns backup
    /// transport, encryption, retention and external acknowledgement.
    #[must_use]
    pub fn backup_bytes(&self) -> Vec<u8> {
        self.journal.export_bytes()
    }

    pub fn append_projection(
        &mut self,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError> {
        self.commit(|journal| {
            journal.append_projection(
                kind,
                identity_digest,
                objective_digest,
                subject_digest,
                payload_digest,
            )
        })
    }

    pub fn select_projection(
        &mut self,
        operation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError> {
        self.commit(|journal| {
            journal.select_projection(
                operation_identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            )
        })
    }

    pub fn revoke_projection(
        &mut self,
        revocation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError> {
        self.commit(|journal| {
            journal.revoke_projection(
                revocation_identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            )
        })
    }

    /// Replaces the current state from a complete backup only after validating
    /// the whole hash chain and semantic transition history. Restore is
    /// monotonic: the current committed history must be an exact prefix of the
    /// backup. This prevents an older valid backup from deleting a later
    /// revocation or otherwise resurrecting stale selected state.
    pub fn restore_backup(
        &mut self,
        bytes: &[u8],
    ) -> Result<(), NduProjectionStoreError> {
        if bytes.len() > MAX_BACKUP_BYTES {
            return Err(NduProjectionStoreError::BackupTooLarge);
        }
        let restored = NduProjectionJournalV1::reopen(bytes)?;
        let current_len = self.journal.entries().len();
        if restored.entries().len() < current_len
            || &restored.entries()[..current_len] != self.journal.entries()
        {
            return Err(NduProjectionStoreError::BackupRegression);
        }
        persist_image(&self.root, &restored)?;
        self.journal = restored;
        Ok(())
    }

    fn commit<F>(
        &mut self,
        mutation: F,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError>
    where
        F: FnOnce(
            &mut NduProjectionJournalV1,
        ) -> Result<NduProjectionEntryV1, NduProjectionJournalError>,
    {
        let mut candidate = self.journal.clone();
        let entry = mutation(&mut candidate)?;
        persist_image(&self.root, &candidate)?;
        self.journal = candidate;
        Ok(entry)
    }
}

impl Drop for NduProjectionStoreV1 {
    fn drop(&mut self) {
        // Mutation methods already synchronize before acknowledgement. Unlocking
        // here is only ownership cleanup, never a durability acknowledgement.
        let _ = self.lock.unlock();
    }
}

fn persist_image(
    root: &Path,
    journal: &NduProjectionJournalV1,
) -> Result<(), NduProjectionStoreError> {
    let temp_path = root.join(TEMP_FILE);
    let journal_path = root.join(JOURNAL_FILE);
    let bytes = journal.export_bytes();
    if bytes.len() > MAX_BACKUP_BYTES {
        return Err(NduProjectionStoreError::BackupTooLarge);
    }

    let mut temp = match OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp_path)
    {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
            fs::remove_file(&temp_path)?;
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temp_path)?
        }
        Err(error) => return Err(error.into()),
    };
    if let Err(error) = temp.write_all(&bytes).and_then(|()| temp.sync_all()) {
        let _ = fs::remove_file(&temp_path);
        return Err(error.into());
    }
    drop(temp);

    if let Err(error) = fs::rename(&temp_path, &journal_path) {
        let _ = fs::remove_file(&temp_path);
        return Err(error.into());
    }

    sync_parent(root).map_err(|_| NduProjectionStoreError::Indeterminate)
}

#[cfg(unix)]
fn sync_parent(root: &Path) -> io::Result<()> {
    File::open(root)?.sync_all()
}

#[cfg(not(unix))]
fn sync_parent(_root: &Path) -> io::Result<()> {
    // The V1 repository qualification profile is Unix. Other platforms must
    // supply equivalent directory-durability evidence before activation.
    Ok(())
}

#[cfg(test)]
#[path = "projection_store_tests.rs"]
mod tests;
