use std::error::Error as StdError;
use std::fmt;
#[cfg(unix)]
use std::fs;
use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::fs::TryLockError;
#[cfg(unix)]
use std::io;
#[cfg(unix)]
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

use crate::NduProjectionCheckpointV1;
use crate::NduProjectionEntryV1;
use crate::NduProjectionJournalError;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;

#[cfg(unix)]
const STORE_MAGIC: &[u8; 8] = b"HNDUPS01";
#[cfg(unix)]
const STORE_SCHEMA_VERSION: u32 = 1;
#[cfg(unix)]
const STORE_FILENAME: &str = "ndu_projection_store_v1.bin";
#[cfg(unix)]
const LOCK_FILENAME: &str = "ndu_projection_store_v1.lock";
#[cfg(unix)]
const TEMP_FILENAME: &str = ".ndu_projection_store_v1.tmp";
#[cfg(unix)]
const STORE_SCHEMA_V1: &[u8] = b"hepta.ndu.projection-store.v1|wrapper:magic,u32-version,32-byte-schema-digest,u32-journal-length,journal-bytes,32-byte-store-digest|journal:HNDUPJ01";

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduProjectionStoreError {
    UnsupportedPlatform,
    WriterBusy,
    InvalidRoot,
    InsecurePermissions,
    UnexpectedFileType,
    SchemaVersion(u32),
    SchemaDigestMismatch,
    CorruptStore,
    Io(String),
    Journal(NduProjectionJournalError),
}

impl fmt::Display for NduProjectionStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduProjectionStoreError {}

impl From<NduProjectionJournalError> for NduProjectionStoreError {
    fn from(value: NduProjectionJournalError) -> Self {
        Self::Journal(value)
    }
}

/// Durable owner-local projection-store candidate.
///
/// On Unix this store requires an owner-private directory, holds a kernel
/// exclusive file lock for the lifetime of the writer, replaces the complete
/// bounded journal atomically, fsyncs the replacement and containing directory,
/// and verifies a version/checksum-bound store envelope on every reopen.
///
/// It is not an activation claim: a product host must still choose this store,
/// qualify the target filesystem and backup/restore behavior, distribute a
/// trusted checkpoint anchor, and prove writer ownership operationally.
#[derive(Debug)]
pub struct NduProjectionStoreV1 {
    root: PathBuf,
    journal: NduProjectionJournalV1,
    _writer_lock: File,
}

impl NduProjectionStoreV1 {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, NduProjectionStoreError> {
        #[cfg(not(unix))]
        {
            let _ = root;
            return Err(NduProjectionStoreError::UnsupportedPlatform);
        }

        #[cfg(unix)]
        {
            let root = root.as_ref().to_path_buf();
            prepare_private_root(&root)?;
            let writer_lock = acquire_writer_lock(&root)?;
            let store_path = root.join(STORE_FILENAME);
            let journal = if store_path.exists() {
                validate_regular_private_file(&store_path)?;
                decode_store(&fs::read(&store_path).map_err(io_error)?)?
            } else {
                let journal = NduProjectionJournalV1::new();
                persist_journal(&root, &journal)?;
                journal
            };
            Ok(Self {
                root,
                journal,
                _writer_lock: writer_lock,
            })
        }
    }

    pub fn restore_create_new(
        backup_path: impl AsRef<Path>,
        root: impl AsRef<Path>,
    ) -> Result<Self, NduProjectionStoreError> {
        #[cfg(not(unix))]
        {
            let _ = (backup_path, root);
            return Err(NduProjectionStoreError::UnsupportedPlatform);
        }

        #[cfg(unix)]
        {
            let backup_path = backup_path.as_ref();
            validate_regular_private_file(backup_path)?;
            let journal = decode_store(&fs::read(backup_path).map_err(io_error)?)?;
            let root = root.as_ref();
            if root.exists() {
                return Err(NduProjectionStoreError::InvalidRoot);
            }
            prepare_private_root(root)?;
            let writer_lock = acquire_writer_lock(root)?;
            persist_journal(root, &journal)?;
            Ok(Self {
                root: root.to_path_buf(),
                journal,
                _writer_lock: writer_lock,
            })
        }
    }

    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }

    #[must_use]
    pub fn checkpoint(&self) -> NduProjectionCheckpointV1 {
        self.journal.checkpoint()
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
        self.apply_mutation(|journal| {
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
        self.apply_mutation(|journal| {
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
        self.apply_mutation(|journal| {
            journal.revoke_projection(
                revocation_identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            )
        })
    }

    pub fn backup_create_new(
        &self,
        backup_path: impl AsRef<Path>,
    ) -> Result<NduProjectionCheckpointV1, NduProjectionStoreError> {
        #[cfg(not(unix))]
        {
            let _ = backup_path;
            return Err(NduProjectionStoreError::UnsupportedPlatform);
        }

        #[cfg(unix)]
        {
            let backup_path = backup_path.as_ref();
            let parent = backup_path
                .parent()
                .ok_or(NduProjectionStoreError::InvalidRoot)?;
            if backup_path.exists() {
                return Err(NduProjectionStoreError::InvalidRoot);
            }
            validate_private_directory(parent)?;
            let temporary = backup_path.with_extension("ndu-backup-tmp");
            if temporary.exists() {
                return Err(NduProjectionStoreError::InvalidRoot);
            }
            atomic_write_create_new(&temporary, backup_path, &encode_store(&self.journal)?)?;
            Ok(self.checkpoint())
        }
    }

    fn apply_mutation<T>(
        &mut self,
        mutation: impl FnOnce(&mut NduProjectionJournalV1) -> Result<T, NduProjectionJournalError>,
    ) -> Result<T, NduProjectionStoreError> {
        let predecessor = self.journal.clone();
        let predecessor_checkpoint = predecessor.checkpoint();
        let result = mutation(&mut self.journal)?;
        if self.journal.checkpoint() == predecessor_checkpoint {
            return Ok(result);
        }
        if let Err(error) = persist_journal(&self.root, &self.journal) {
            self.journal = predecessor;
            return Err(error);
        }
        Ok(result)
    }
}

#[cfg(unix)]
fn prepare_private_root(root: &Path) -> Result<(), NduProjectionStoreError> {
    use std::os::unix::fs::PermissionsExt;

    match fs::symlink_metadata(root) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err(NduProjectionStoreError::UnexpectedFileType);
            }
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            fs::create_dir(root).map_err(io_error)?;
            fs::set_permissions(root, fs::Permissions::from_mode(0o700)).map_err(io_error)?;
            if let Some(parent) = root.parent() {
                sync_directory(parent)?;
            }
        }
        Err(error) => return Err(io_error(error)),
    }
    validate_private_directory(root)
}

#[cfg(unix)]
fn validate_private_directory(path: &Path) -> Result<(), NduProjectionStoreError> {
    use std::os::unix::fs::PermissionsExt;

    let metadata = fs::symlink_metadata(path).map_err(io_error)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(NduProjectionStoreError::UnexpectedFileType);
    }
    if metadata.permissions().mode() & 0o077 != 0 {
        return Err(NduProjectionStoreError::InsecurePermissions);
    }
    Ok(())
}

#[cfg(unix)]
fn validate_regular_private_file(path: &Path) -> Result<(), NduProjectionStoreError> {
    use std::os::unix::fs::PermissionsExt;

    let metadata = fs::symlink_metadata(path).map_err(io_error)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(NduProjectionStoreError::UnexpectedFileType);
    }
    if metadata.permissions().mode() & 0o077 != 0 {
        return Err(NduProjectionStoreError::InsecurePermissions);
    }
    Ok(())
}

#[cfg(unix)]
fn acquire_writer_lock(root: &Path) -> Result<File, NduProjectionStoreError> {
    use std::os::unix::fs::PermissionsExt;

    let path = root.join(LOCK_FILENAME);
    if path.exists() {
        validate_regular_private_file(&path)?;
    }
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .open(&path)
        .map_err(io_error)?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).map_err(io_error)?;
    match file.try_lock() {
        Ok(()) => Ok(file),
        Err(TryLockError::WouldBlock) => Err(NduProjectionStoreError::WriterBusy),
        Err(TryLockError::Error(error)) => Err(io_error(error)),
    }
}

#[cfg(unix)]
fn persist_journal(
    root: &Path,
    journal: &NduProjectionJournalV1,
) -> Result<(), NduProjectionStoreError> {
    let temporary = root.join(TEMP_FILENAME);
    let destination = root.join(STORE_FILENAME);
    if temporary.exists() {
        validate_regular_private_file(&temporary)?;
        fs::remove_file(&temporary).map_err(io_error)?;
    }
    atomic_write_create_new(&temporary, &destination, &encode_store(journal)?)
}

#[cfg(unix)]
fn atomic_write_create_new(
    temporary: &Path,
    destination: &Path,
    bytes: &[u8],
) -> Result<(), NduProjectionStoreError> {
    use std::os::unix::fs::PermissionsExt;

    let parent = destination
        .parent()
        .ok_or(NduProjectionStoreError::InvalidRoot)?;
    validate_private_directory(parent)?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(temporary)
        .map_err(io_error)?;
    fs::set_permissions(temporary, fs::Permissions::from_mode(0o600)).map_err(io_error)?;
    let write_result = (|| -> io::Result<()> {
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        fs::rename(temporary, destination)?;
        File::open(parent)?.sync_all()
    })();
    if let Err(error) = write_result {
        let _ = fs::remove_file(temporary);
        return Err(io_error(error));
    }
    validate_regular_private_file(destination)
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), NduProjectionStoreError> {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(io_error)
}

#[cfg(unix)]
fn encode_store(journal: &NduProjectionJournalV1) -> Result<Vec<u8>, NduProjectionStoreError> {
    let journal_bytes = journal.export_bytes();
    let journal_length =
        u32::try_from(journal_bytes.len()).map_err(|_| NduProjectionStoreError::CorruptStore)?;
    let mut bytes = Vec::with_capacity(8 + 4 + 32 + 4 + journal_bytes.len() + 32);
    bytes.extend_from_slice(STORE_MAGIC);
    bytes.extend_from_slice(&STORE_SCHEMA_VERSION.to_be_bytes());
    bytes.extend_from_slice(store_schema_digest().as_array());
    bytes.extend_from_slice(&journal_length.to_be_bytes());
    bytes.extend_from_slice(&journal_bytes);
    let store_digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(store_digest.as_array());
    Ok(bytes)
}

#[cfg(unix)]
fn decode_store(bytes: &[u8]) -> Result<NduProjectionJournalV1, NduProjectionStoreError> {
    const HEADER_BYTES: usize = 8 + 4 + 32 + 4;
    const DIGEST_BYTES: usize = 32;
    if bytes.len() < HEADER_BYTES + DIGEST_BYTES || &bytes[..8] != STORE_MAGIC {
        return Err(NduProjectionStoreError::CorruptStore);
    }
    let version = u32::from_be_bytes(
        bytes[8..12]
            .try_into()
            .map_err(|_| NduProjectionStoreError::CorruptStore)?,
    );
    if version != STORE_SCHEMA_VERSION {
        return Err(NduProjectionStoreError::SchemaVersion(version));
    }
    let schema_digest = digest_from_slice(&bytes[12..44])?;
    if schema_digest != store_schema_digest() {
        return Err(NduProjectionStoreError::SchemaDigestMismatch);
    }
    let journal_length = usize::try_from(u32::from_be_bytes(
        bytes[44..48]
            .try_into()
            .map_err(|_| NduProjectionStoreError::CorruptStore)?,
    ))
    .map_err(|_| NduProjectionStoreError::CorruptStore)?;
    let journal_end = HEADER_BYTES
        .checked_add(journal_length)
        .ok_or(NduProjectionStoreError::CorruptStore)?;
    let expected_length = journal_end
        .checked_add(DIGEST_BYTES)
        .ok_or(NduProjectionStoreError::CorruptStore)?;
    if bytes.len() != expected_length {
        return Err(NduProjectionStoreError::CorruptStore);
    }
    let stored_digest = digest_from_slice(&bytes[journal_end..])?;
    if stored_digest != Digest32::of_bytes(&bytes[..journal_end]) {
        return Err(NduProjectionStoreError::CorruptStore);
    }
    NduProjectionJournalV1::reopen(&bytes[HEADER_BYTES..journal_end]).map_err(Into::into)
}

#[cfg(unix)]
fn digest_from_slice(bytes: &[u8]) -> Result<Digest32, NduProjectionStoreError> {
    let array: [u8; 32] = bytes
        .try_into()
        .map_err(|_| NduProjectionStoreError::CorruptStore)?;
    Ok(Digest32::from_array(array))
}

#[cfg(unix)]
fn store_schema_digest() -> Digest32 {
    Digest32::of_bytes(STORE_SCHEMA_V1)
}

#[cfg(unix)]
fn io_error(error: io::Error) -> NduProjectionStoreError {
    NduProjectionStoreError::Io(error.to_string())
}

#[cfg(all(test, unix))]
#[path = "projection_store_tests.rs"]
mod tests;
