//! Crash-bounded durable writer candidate for NDU projection state.
//!
//! The V1 durability profile is Unix-only because it requires atomic replacement
//! of an existing path plus parent-directory synchronization before success is
//! acknowledged. Other platforms fail closed until an equivalent reviewed
//! persistence profile exists.

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
const STORE_MAGIC: &[u8; 8] = b"HNDUPS01";
const STORE_SCHEMA_V1: u32 = 1;
const STORE_HEADER_BYTES: usize = 8 + 4 + 4 + 32;
const MAX_JOURNAL_RECORDS: usize = 4096;
const MAX_BACKUP_BYTES: usize = 12 + MAX_JOURNAL_RECORDS * (8 + 1 + 32 + 32 + 32 + 32 + 32 + 32);
const MAX_STORE_BYTES: usize = STORE_HEADER_BYTES + MAX_BACKUP_BYTES;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NduProjectionRetentionPolicyV1 {
    /// Non-revocation history is bounded below the journal hard ceiling so
    /// safety revocations retain reserved append capacity.
    pub maximum_non_revocation_records: usize,
    pub minimum_revocation_reserve: usize,
    /// V1 never permits compaction that discards revocation history.
    pub retain_revocation_history: bool,
}

impl Default for NduProjectionRetentionPolicyV1 {
    fn default() -> Self {
        Self {
            maximum_non_revocation_records: 3072,
            minimum_revocation_reserve: 1024,
            retain_revocation_history: true,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduProjectionStoreError {
    UnsupportedPlatform,
    Busy,
    NotDirectory,
    NotRegular,
    Symlink,
    BackupTooLarge,
    BackupRegression,
    UnsupportedSchema,
    CorruptStoreImage,
    InvalidRetentionPolicy,
    RetentionExceeded,
    Journal(NduProjectionJournalError),
    Io(io::ErrorKind),
    /// A rename may have committed but directory durability was not
    /// acknowledged. The open handle is poisoned and must be reopened before
    /// authoritative reads, backup export, restore or further mutation.
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
/// authenticated owner. A hostile process that races path replacement after
/// admission or ignores the lock is outside this mechanism's threat model.
/// Existing symlinked root/lock/journal paths are rejected before use.
pub struct NduProjectionStoreV1 {
    root: PathBuf,
    lock: File,
    journal: NduProjectionJournalV1,
    retention_policy: NduProjectionRetentionPolicyV1,
    indeterminate: bool,
}

impl NduProjectionStoreV1 {
    /// Opens or initializes the V1 store. The directory must already exist so
    /// repository code cannot silently widen filesystem authority. V1 is
    /// deliberately unavailable on non-Unix targets rather than silently using
    /// weaker replacement or directory-durability semantics.
    pub fn open(root: impl AsRef<Path>) -> Result<Self, NduProjectionStoreError> {
        Self::open_with_retention_policy(root, NduProjectionRetentionPolicyV1::default())
    }

    pub fn open_with_retention_policy(
        root: impl AsRef<Path>,
        retention_policy: NduProjectionRetentionPolicyV1,
    ) -> Result<Self, NduProjectionStoreError> {
        validate_retention_policy(retention_policy)?;
        if !cfg!(unix) {
            return Err(NduProjectionStoreError::UnsupportedPlatform);
        }
        let root = root.as_ref().to_path_buf();
        let metadata = fs::symlink_metadata(&root)?;
        if metadata.file_type().is_symlink() {
            return Err(NduProjectionStoreError::Symlink);
        }
        if !metadata.is_dir() {
            return Err(NduProjectionStoreError::NotDirectory);
        }

        let lock_path = root.join(LOCK_FILE);
        reject_existing_symlink(&lock_path)?;
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&lock_path)?;
        if !lock.metadata()?.is_file() {
            return Err(NduProjectionStoreError::NotRegular);
        }
        match File::try_lock(&lock) {
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
        reject_existing_symlink(&journal_path)?;
        let journal = match File::open(&journal_path) {
            Ok(mut file) => {
                if !file.metadata()?.is_file() {
                    return Err(NduProjectionStoreError::NotRegular);
                }
                let mut bytes = Vec::new();
                file.read_to_end(&mut bytes)?;
                if bytes.len() > MAX_STORE_BYTES {
                    return Err(NduProjectionStoreError::BackupTooLarge);
                }
                let (journal, requires_migration) = decode_store_or_legacy_image(&bytes)?;
                validate_retention_state(&journal, retention_policy)?;
                if requires_migration {
                    persist_image(&root, &journal)?;
                }
                journal
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                let journal = NduProjectionJournalV1::new();
                validate_retention_state(&journal, retention_policy)?;
                persist_image(&root, &journal)?;
                journal
            }
            Err(error) => return Err(error.into()),
        };

        Ok(Self {
            root,
            lock,
            journal,
            retention_policy,
            indeterminate: false,
        })
    }

    #[must_use]
    pub const fn is_indeterminate(&self) -> bool {
        self.indeterminate
    }

    #[must_use]
    pub const fn schema_version(&self) -> u32 {
        STORE_SCHEMA_V1
    }

    #[must_use]
    pub const fn retention_policy(&self) -> NduProjectionRetentionPolicyV1 {
        self.retention_policy
    }

    pub fn entries(&self) -> Result<&[NduProjectionEntryV1], NduProjectionStoreError> {
        self.ensure_authoritative()?;
        Ok(self.journal.entries())
    }

    pub fn selected_projection_digest(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Result<Option<Digest32>, NduProjectionStoreError> {
        self.ensure_authoritative()?;
        Ok(self
            .journal
            .selected_projection_digest(objective_digest, subject_digest))
    }

    /// Returns a complete, self-validating backup image. The caller owns backup
    /// transport, encryption, retention and external acknowledgement.
    pub fn backup_bytes(&self) -> Result<Vec<u8>, NduProjectionStoreError> {
        self.ensure_authoritative()?;
        Ok(self.journal.export_bytes())
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
    pub fn restore_backup(&mut self, bytes: &[u8]) -> Result<(), NduProjectionStoreError> {
        self.ensure_authoritative()?;
        if bytes.len() > MAX_BACKUP_BYTES {
            return Err(NduProjectionStoreError::BackupTooLarge);
        }
        let restored = NduProjectionJournalV1::reopen(bytes)?;
        validate_retention_state(&restored, self.retention_policy)?;
        let current_len = self.journal.entries().len();
        if restored.entries().len() < current_len
            || &restored.entries()[..current_len] != self.journal.entries()
        {
            return Err(NduProjectionStoreError::BackupRegression);
        }
        match persist_image(&self.root, &restored) {
            Ok(()) => {
                self.journal = restored;
                Ok(())
            }
            Err(NduProjectionStoreError::Indeterminate) => {
                self.indeterminate = true;
                Err(NduProjectionStoreError::Indeterminate)
            }
            Err(error) => Err(error),
        }
    }

    fn ensure_authoritative(&self) -> Result<(), NduProjectionStoreError> {
        if self.indeterminate {
            Err(NduProjectionStoreError::Indeterminate)
        } else {
            Ok(())
        }
    }

    fn commit<F>(&mut self, mutation: F) -> Result<NduProjectionEntryV1, NduProjectionStoreError>
    where
        F: FnOnce(
            &mut NduProjectionJournalV1,
        ) -> Result<NduProjectionEntryV1, NduProjectionJournalError>,
    {
        self.ensure_authoritative()?;
        let mut candidate = self.journal.clone();
        let entry = mutation(&mut candidate)?;
        validate_retention_state(&candidate, self.retention_policy)?;
        match persist_image(&self.root, &candidate) {
            Ok(()) => {
                self.journal = candidate;
                Ok(entry)
            }
            Err(NduProjectionStoreError::Indeterminate) => {
                self.indeterminate = true;
                Err(NduProjectionStoreError::Indeterminate)
            }
            Err(error) => Err(error),
        }
    }
}

impl Drop for NduProjectionStoreV1 {
    fn drop(&mut self) {
        // Mutation methods already synchronize before acknowledgement. Unlocking
        // here is only ownership cleanup, never a durability acknowledgement.
        let _ = File::unlock(&self.lock);
    }
}

fn reject_existing_symlink(path: &Path) -> Result<(), NduProjectionStoreError> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => Err(NduProjectionStoreError::Symlink),
        Ok(_) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn validate_retention_policy(
    policy: NduProjectionRetentionPolicyV1,
) -> Result<(), NduProjectionStoreError> {
    if !policy.retain_revocation_history
        || policy.maximum_non_revocation_records == 0
        || policy.minimum_revocation_reserve == 0
        || policy.maximum_non_revocation_records > MAX_JOURNAL_RECORDS
        || policy.minimum_revocation_reserve > MAX_JOURNAL_RECORDS
        || policy
            .maximum_non_revocation_records
            .checked_add(policy.minimum_revocation_reserve)
            .is_none_or(|value| value > MAX_JOURNAL_RECORDS)
    {
        return Err(NduProjectionStoreError::InvalidRetentionPolicy);
    }
    Ok(())
}

fn validate_retention_state(
    journal: &NduProjectionJournalV1,
    policy: NduProjectionRetentionPolicyV1,
) -> Result<(), NduProjectionStoreError> {
    let non_revocation = journal
        .entries()
        .iter()
        .filter(|entry| entry.kind != NduProjectionKindV1::Revocation)
        .count();
    if non_revocation > policy.maximum_non_revocation_records {
        return Err(NduProjectionStoreError::RetentionExceeded);
    }
    Ok(())
}

fn encode_store_image(journal: &NduProjectionJournalV1) -> Vec<u8> {
    let payload = journal.export_bytes();
    let mut bytes = Vec::with_capacity(STORE_HEADER_BYTES + payload.len());
    bytes.extend_from_slice(STORE_MAGIC);
    bytes.extend_from_slice(&STORE_SCHEMA_V1.to_be_bytes());
    bytes.extend_from_slice(&u32::try_from(payload.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
    bytes.extend_from_slice(&payload);
    bytes
}

fn decode_store_or_legacy_image(
    bytes: &[u8],
) -> Result<(NduProjectionJournalV1, bool), NduProjectionStoreError> {
    if !bytes.starts_with(STORE_MAGIC) {
        return Ok((NduProjectionJournalV1::reopen(bytes)?, true));
    }
    if bytes.len() < STORE_HEADER_BYTES {
        return Err(NduProjectionStoreError::CorruptStoreImage);
    }
    let version = u32::from_be_bytes(
        bytes[8..12]
            .try_into()
            .map_err(|_| NduProjectionStoreError::CorruptStoreImage)?,
    );
    if version != STORE_SCHEMA_V1 {
        return Err(NduProjectionStoreError::UnsupportedSchema);
    }
    let payload_len = usize::try_from(u32::from_be_bytes(
        bytes[12..16]
            .try_into()
            .map_err(|_| NduProjectionStoreError::CorruptStoreImage)?,
    ))
    .map_err(|_| NduProjectionStoreError::CorruptStoreImage)?;
    let expected_len = STORE_HEADER_BYTES
        .checked_add(payload_len)
        .ok_or(NduProjectionStoreError::CorruptStoreImage)?;
    if bytes.len() != expected_len || payload_len > MAX_BACKUP_BYTES {
        return Err(NduProjectionStoreError::CorruptStoreImage);
    }
    let expected_digest = Digest32::from_array(
        bytes[16..48]
            .try_into()
            .map_err(|_| NduProjectionStoreError::CorruptStoreImage)?,
    );
    let payload = &bytes[STORE_HEADER_BYTES..];
    if Digest32::of_bytes(payload) != expected_digest {
        return Err(NduProjectionStoreError::CorruptStoreImage);
    }
    Ok((NduProjectionJournalV1::reopen(payload)?, false))
}

fn persist_image(
    root: &Path,
    journal: &NduProjectionJournalV1,
) -> Result<(), NduProjectionStoreError> {
    if !cfg!(unix) {
        return Err(NduProjectionStoreError::UnsupportedPlatform);
    }
    let temp_path = root.join(TEMP_FILE);
    let journal_path = root.join(JOURNAL_FILE);
    let bytes = encode_store_image(journal);
    if bytes.len() > MAX_STORE_BYTES {
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
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "NDU durable writer V1 requires Unix directory durability semantics",
    ))
}

#[cfg(test)]
#[path = "projection_store_tests.rs"]
mod tests;
