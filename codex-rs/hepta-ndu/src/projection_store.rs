use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

use crate::NduProjectionEntryV1;
use crate::NduProjectionJournalError;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;

#[cfg(unix)]
const MAX_STORE_BYTES: usize = 12 + 4096 * (8 + 1 + 32 * 6);

/// Single-writer, crash-consistent file persistence for the owner-local NDU
/// projection journal. This is a native durability primitive, not evidence that
/// a product has selected this store, configured retention/backup, or activated
/// a production writer.
#[derive(Debug)]
pub struct NduProjectionFileStoreV1 {
    path: PathBuf,
    _lock_path: PathBuf,
    _lock_file: File,
    journal: NduProjectionJournalV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduProjectionStoreError {
    UnsupportedPlatform,
    InvalidPath,
    Symlink,
    NotRegular,
    InsecurePermissions,
    WriterBusy,
    Oversize,
    Io,
    Journal(NduProjectionJournalError),
}

impl fmt::Display for NduProjectionStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduProjectionStoreError {}

impl From<NduProjectionJournalError> for NduProjectionStoreError {
    fn from(error: NduProjectionJournalError) -> Self {
        Self::Journal(error)
    }
}

impl NduProjectionFileStoreV1 {
    /// Opens one owner-local journal with an OS-backed nonblocking exclusive
    /// writer lock. Unix is the admitted durability profile because this path
    /// requires a same-directory atomic rename plus containing-directory fsync.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, NduProjectionStoreError> {
        open_store(path.as_ref())
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

    pub fn append_projection(
        &mut self,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError> {
        self.mutate(|journal| {
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
        self.mutate(|journal| {
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
        self.mutate(|journal| {
            journal.revoke_projection(
                revocation_identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            )
        })
    }

    fn mutate(
        &mut self,
        operation: impl FnOnce(
            &mut NduProjectionJournalV1,
        ) -> Result<NduProjectionEntryV1, NduProjectionJournalError>,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError> {
        let mut next = self.journal.clone();
        let entry = operation(&mut next)?;
        persist(&self.path, &next)?;
        self.journal = next;
        Ok(entry)
    }
}

#[cfg(unix)]
fn open_store(path: &Path) -> Result<NduProjectionFileStoreV1, NduProjectionStoreError> {
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;

    let parent = path
        .parent()
        .filter(|value| !value.as_os_str().is_empty())
        .ok_or(NduProjectionStoreError::InvalidPath)?;
    let parent_metadata =
        std::fs::symlink_metadata(parent).map_err(|_| NduProjectionStoreError::Io)?;
    if parent_metadata.file_type().is_symlink() || !parent_metadata.is_dir() {
        return Err(NduProjectionStoreError::InvalidPath);
    }

    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(NduProjectionStoreError::InvalidPath)?;
    let lock_path = parent.join(format!(".{file_name}.lock"));
    let temp_path = parent.join(format!(".{file_name}.next"));

    let mut lock_options = OpenOptions::new();
    lock_options
        .read(true)
        .write(true)
        .create(true)
        .mode(0o600)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
    let lock_file = lock_options
        .open(&lock_path)
        .map_err(|_| NduProjectionStoreError::Io)?;
    if lock_file
        .metadata()
        .map_err(|_| NduProjectionStoreError::Io)?
        .permissions()
        .mode()
        & 0o077
        != 0
    {
        return Err(NduProjectionStoreError::InsecurePermissions);
    }
    match lock_file.try_lock() {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
            return Err(NduProjectionStoreError::WriterBusy);
        }
        Err(_) => return Err(NduProjectionStoreError::Io),
    }

    if let Ok(metadata) = std::fs::symlink_metadata(&temp_path) {
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(NduProjectionStoreError::Symlink);
        }
        std::fs::remove_file(&temp_path).map_err(|_| NduProjectionStoreError::Io)?;
    }

    let journal = match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() {
                return Err(NduProjectionStoreError::Symlink);
            }
            if !metadata.is_file() {
                return Err(NduProjectionStoreError::NotRegular);
            }
            if metadata.permissions().mode() & 0o077 != 0 {
                return Err(NduProjectionStoreError::InsecurePermissions);
            }
            if usize::try_from(metadata.len()).map_err(|_| NduProjectionStoreError::Oversize)?
                > MAX_STORE_BYTES
            {
                return Err(NduProjectionStoreError::Oversize);
            }
            let mut options = OpenOptions::new();
            options
                .read(true)
                .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
            let file = options
                .open(path)
                .map_err(|_| NduProjectionStoreError::Io)?;
            let mut bytes = Vec::new();
            file.take((MAX_STORE_BYTES + 1) as u64)
                .read_to_end(&mut bytes)
                .map_err(|_| NduProjectionStoreError::Io)?;
            if bytes.len() > MAX_STORE_BYTES {
                return Err(NduProjectionStoreError::Oversize);
            }
            NduProjectionJournalV1::reopen(&bytes)?
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => NduProjectionJournalV1::new(),
        Err(_) => return Err(NduProjectionStoreError::Io),
    };

    Ok(NduProjectionFileStoreV1 {
        path: path.to_path_buf(),
        _lock_path: lock_path,
        _lock_file: lock_file,
        journal,
    })
}

#[cfg(not(unix))]
fn open_store(_path: &Path) -> Result<NduProjectionFileStoreV1, NduProjectionStoreError> {
    Err(NduProjectionStoreError::UnsupportedPlatform)
}

#[cfg(unix)]
fn persist(path: &Path, journal: &NduProjectionJournalV1) -> Result<(), NduProjectionStoreError> {
    use std::os::unix::fs::OpenOptionsExt;

    let bytes = journal.export_bytes();
    if bytes.len() > MAX_STORE_BYTES {
        return Err(NduProjectionStoreError::Oversize);
    }
    // Validate the complete next image before touching the durable path.
    NduProjectionJournalV1::reopen(&bytes)?;

    let parent = path.parent().ok_or(NduProjectionStoreError::InvalidPath)?;
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(NduProjectionStoreError::InvalidPath)?;
    let temp_path = parent.join(format!(".{file_name}.next"));

    let mut options = OpenOptions::new();
    options
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
    let mut file = options
        .open(&temp_path)
        .map_err(|_| NduProjectionStoreError::Io)?;
    let result = (|| {
        file.write_all(&bytes)
            .map_err(|_| NduProjectionStoreError::Io)?;
        file.sync_all().map_err(|_| NduProjectionStoreError::Io)?;
        drop(file);
        std::fs::rename(&temp_path, path).map_err(|_| NduProjectionStoreError::Io)?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|_| NduProjectionStoreError::Io)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temp_path);
    }
    result
}

#[cfg(not(unix))]
fn persist(_path: &Path, _journal: &NduProjectionJournalV1) -> Result<(), NduProjectionStoreError> {
    Err(NduProjectionStoreError::UnsupportedPlatform)
}

#[cfg(test)]
#[path = "projection_store_tests.rs"]
mod tests;
