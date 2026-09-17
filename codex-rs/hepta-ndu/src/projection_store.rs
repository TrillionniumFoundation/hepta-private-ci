use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;

use crate::NduProjectionEntryV1;
use crate::NduProjectionJournalError;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;

const POINTER_MAGIC: &str = "HNDUPS01";
const CURRENT_FILE: &str = "CURRENT";
const WRITER_LOCK_FILE: &str = ".writer.lock";
const MAX_POINTER_BYTES: usize = 512;
const MAX_JOURNAL_BYTES: usize = 12 + 4096 * (8 + 1 + 32 * 6);
const MAX_RETAINED_SNAPSHOTS: usize = 2;
static TEMP_NONCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProjectionBackupV1 {
    pub journal_bytes: Vec<u8>,
    pub journal_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduProjectionStoreError {
    Busy,
    RootNotDirectory,
    RootIsSymlink,
    NotRegular,
    Capacity,
    CorruptPointer,
    CorruptSnapshot,
    SnapshotConflict,
    NotEmpty,
    UnsupportedDurabilityPlatform,
    Journal(NduProjectionJournalError),
    Io(io::ErrorKind),
}

impl fmt::Display for NduProjectionStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduProjectionStoreError {}

impl From<io::Error> for NduProjectionStoreError {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}

impl From<NduProjectionJournalError> for NduProjectionStoreError {
    fn from(value: NduProjectionJournalError) -> Self {
        Self::Journal(value)
    }
}

/// Crash-durable owner-local store candidate for projection journal snapshots.
///
/// The caller supplies a pre-created, host-authorized private directory. One
/// lifetime-held advisory lock fences concurrent writers. Every mutation first
/// writes and fsyncs a complete immutable journal snapshot, then atomically
/// replaces and directory-fsyncs a small `CURRENT` pointer. Recovery follows
/// only that pointer and replays the journal's semantic state machine.
///
/// Directory-fsync durability is admitted on Unix only. This type grants no
/// artifact selection, effect, activation or release authority; host path
/// authentication, backup transport, deletion policy and target-host evidence
/// remain outside this crate.
#[derive(Debug)]
pub struct NduProjectionStoreV1 {
    root: PathBuf,
    writer_lock: File,
    journal: NduProjectionJournalV1,
    snapshot_digest: Digest32,
}

impl NduProjectionStoreV1 {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, NduProjectionStoreError> {
        let root = root.as_ref();
        let metadata = fs::symlink_metadata(root)?;
        if metadata.file_type().is_symlink() {
            return Err(NduProjectionStoreError::RootIsSymlink);
        }
        if !metadata.is_dir() {
            return Err(NduProjectionStoreError::RootNotDirectory);
        }

        let lock_path = root.join(WRITER_LOCK_FILE);
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true);
        #[cfg(unix)]
        options.mode(0o600);
        let writer_lock = options.open(lock_path)?;
        if !writer_lock.metadata()?.is_file() {
            return Err(NduProjectionStoreError::NotRegular);
        }
        match writer_lock.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(NduProjectionStoreError::Busy),
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }

        let (journal, snapshot_digest) = load_current(root)?;
        Ok(Self {
            root: root.to_path_buf(),
            writer_lock,
            journal,
            snapshot_digest,
        })
    }

    #[must_use]
    pub fn journal(&self) -> &NduProjectionJournalV1 {
        &self.journal
    }

    #[must_use]
    pub const fn current_snapshot_digest(&self) -> Digest32 {
        self.snapshot_digest
    }

    pub fn append_projection(
        &mut self,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError> {
        let mut next = self.journal.clone();
        let entry = next.append_projection(
            kind,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
        )?;
        self.commit(next)?;
        Ok(entry)
    }

    pub fn select_projection(
        &mut self,
        operation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError> {
        let mut next = self.journal.clone();
        let entry = next.select_projection(
            operation_identity_digest,
            objective_digest,
            subject_digest,
            projection_digest,
        )?;
        self.commit(next)?;
        Ok(entry)
    }

    pub fn revoke_projection(
        &mut self,
        revocation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionStoreError> {
        let mut next = self.journal.clone();
        let entry = next.revoke_projection(
            revocation_identity_digest,
            objective_digest,
            subject_digest,
            projection_digest,
        )?;
        self.commit(next)?;
        Ok(entry)
    }

    #[must_use]
    pub fn export_backup(&self) -> NduProjectionBackupV1 {
        let journal_bytes = self.journal.export_bytes();
        NduProjectionBackupV1 {
            journal_digest: Digest32::of_bytes(&journal_bytes),
            journal_bytes,
        }
    }

    pub fn restore_into_empty(
        root: impl AsRef<Path>,
        backup: &NduProjectionBackupV1,
    ) -> Result<Self, NduProjectionStoreError> {
        if backup.journal_bytes.len() > MAX_JOURNAL_BYTES
            || Digest32::of_bytes(&backup.journal_bytes) != backup.journal_digest
        {
            return Err(NduProjectionStoreError::CorruptSnapshot);
        }
        let journal = NduProjectionJournalV1::reopen(&backup.journal_bytes)?;
        if journal.entries().is_empty() {
            return Err(NduProjectionStoreError::CorruptSnapshot);
        }
        let mut store = Self::open(root)?;
        if !store.journal.entries().is_empty() {
            return Err(NduProjectionStoreError::NotEmpty);
        }
        store.commit(journal)?;
        Ok(store)
    }

    fn commit(&mut self, next: NduProjectionJournalV1) -> Result<(), NduProjectionStoreError> {
        if next.entries().is_empty() || next.entries().len() > 4096 {
            return Err(NduProjectionStoreError::Capacity);
        }
        let bytes = next.export_bytes();
        if bytes.len() > MAX_JOURNAL_BYTES {
            return Err(NduProjectionStoreError::Capacity);
        }
        let digest = Digest32::of_bytes(&bytes);
        let sequence = u64::try_from(next.entries().len())
            .map_err(|_| NduProjectionStoreError::Capacity)?;
        let filename = snapshot_filename(sequence, digest);
        publish_snapshot(&self.root, &filename, &bytes)?;
        publish_pointer(&self.root, sequence, digest, &filename)?;
        prune_snapshots(&self.root, &filename)?;
        self.journal = next;
        self.snapshot_digest = digest;
        Ok(())
    }
}

impl Drop for NduProjectionStoreV1 {
    fn drop(&mut self) {
        let _ = self.writer_lock.unlock();
    }
}

fn load_current(
    root: &Path,
) -> Result<(NduProjectionJournalV1, Digest32), NduProjectionStoreError> {
    let pointer_path = root.join(CURRENT_FILE);
    let pointer_metadata = match fs::symlink_metadata(&pointer_path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return Ok((NduProjectionJournalV1::new(), Digest32::ZERO));
        }
        Err(error) => return Err(error.into()),
    };
    if pointer_metadata.file_type().is_symlink() || !pointer_metadata.is_file() {
        return Err(NduProjectionStoreError::CorruptPointer);
    }
    let pointer = read_bounded(&pointer_path, MAX_POINTER_BYTES)?;
    let (sequence, digest, filename) = decode_pointer(&pointer)?;
    if filename != snapshot_filename(sequence, digest) {
        return Err(NduProjectionStoreError::CorruptPointer);
    }
    let snapshot_path = root.join(&filename);
    let snapshot_metadata = fs::symlink_metadata(&snapshot_path)
        .map_err(|_| NduProjectionStoreError::CorruptSnapshot)?;
    if snapshot_metadata.file_type().is_symlink() || !snapshot_metadata.is_file() {
        return Err(NduProjectionStoreError::CorruptSnapshot);
    }
    let bytes = read_bounded(&snapshot_path, MAX_JOURNAL_BYTES)
        .map_err(|_| NduProjectionStoreError::CorruptSnapshot)?;
    if Digest32::of_bytes(&bytes) != digest {
        return Err(NduProjectionStoreError::CorruptSnapshot);
    }
    let journal = NduProjectionJournalV1::reopen(&bytes)?;
    if journal.entries().len() != usize::try_from(sequence).unwrap_or(usize::MAX) {
        return Err(NduProjectionStoreError::CorruptSnapshot);
    }
    Ok((journal, digest))
}

fn publish_snapshot(
    root: &Path,
    filename: &str,
    bytes: &[u8],
) -> Result<(), NduProjectionStoreError> {
    let final_path = root.join(filename);
    if let Ok(metadata) = fs::symlink_metadata(&final_path) {
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(NduProjectionStoreError::SnapshotConflict);
        }
        let existing = read_bounded(&final_path, MAX_JOURNAL_BYTES)?;
        if existing != bytes {
            return Err(NduProjectionStoreError::SnapshotConflict);
        }
        return Ok(());
    }

    let temporary = temporary_path(root, "snapshot");
    let mut file = create_private_new(&temporary)?;
    if let Err(error) = file.write_all(bytes).and_then(|()| file.sync_all()) {
        let _ = fs::remove_file(&temporary);
        return Err(error.into());
    }
    drop(file);
    if let Err(error) = fs::rename(&temporary, &final_path) {
        let _ = fs::remove_file(&temporary);
        return Err(error.into());
    }
    sync_directory(root)?;
    Ok(())
}

fn publish_pointer(
    root: &Path,
    sequence: u64,
    digest: Digest32,
    filename: &str,
) -> Result<(), NduProjectionStoreError> {
    let body = format!("{POINTER_MAGIC}\n{sequence}\n{digest}\n{filename}\n");
    if body.len() > MAX_POINTER_BYTES {
        return Err(NduProjectionStoreError::Capacity);
    }
    let temporary = temporary_path(root, "current");
    let mut file = create_private_new(&temporary)?;
    if let Err(error) = file
        .write_all(body.as_bytes())
        .and_then(|()| file.sync_all())
    {
        let _ = fs::remove_file(&temporary);
        return Err(error.into());
    }
    drop(file);
    if let Err(error) = replace_atomic(&temporary, &root.join(CURRENT_FILE)) {
        let _ = fs::remove_file(&temporary);
        return Err(error);
    }
    sync_directory(root)?;
    Ok(())
}

#[cfg(unix)]
fn replace_atomic(source: &Path, destination: &Path) -> Result<(), NduProjectionStoreError> {
    fs::rename(source, destination)?;
    Ok(())
}

#[cfg(not(unix))]
fn replace_atomic(_source: &Path, _destination: &Path) -> Result<(), NduProjectionStoreError> {
    Err(NduProjectionStoreError::UnsupportedDurabilityPlatform)
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), NduProjectionStoreError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), NduProjectionStoreError> {
    Err(NduProjectionStoreError::UnsupportedDurabilityPlatform)
}

fn prune_snapshots(root: &Path, current: &str) -> Result<(), NduProjectionStoreError> {
    let mut snapshots = Vec::new();
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            continue;
        };
        if name.starts_with("journal-") && name.ends_with(".bin") && name != current {
            snapshots.push(name.to_string());
        }
    }
    snapshots.sort();
    let remove_count = snapshots
        .len()
        .saturating_add(1)
        .saturating_sub(MAX_RETAINED_SNAPSHOTS);
    for name in snapshots.into_iter().take(remove_count) {
        let path = root.join(name);
        let metadata = fs::symlink_metadata(&path)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(NduProjectionStoreError::SnapshotConflict);
        }
        fs::remove_file(path)?;
    }
    if remove_count > 0 {
        sync_directory(root)?;
    }
    Ok(())
}

fn decode_pointer(bytes: &[u8]) -> Result<(u64, Digest32, String), NduProjectionStoreError> {
    let text = std::str::from_utf8(bytes).map_err(|_| NduProjectionStoreError::CorruptPointer)?;
    let mut lines = text.lines();
    if lines.next() != Some(POINTER_MAGIC) {
        return Err(NduProjectionStoreError::CorruptPointer);
    }
    let sequence = lines
        .next()
        .ok_or(NduProjectionStoreError::CorruptPointer)?
        .parse::<u64>()
        .map_err(|_| NduProjectionStoreError::CorruptPointer)?;
    if sequence == 0 || sequence > 4096 {
        return Err(NduProjectionStoreError::CorruptPointer);
    }
    let digest = Digest32::from_str(
        lines
            .next()
            .ok_or(NduProjectionStoreError::CorruptPointer)?,
    )
    .map_err(|_| NduProjectionStoreError::CorruptPointer)?;
    if digest.is_zero() {
        return Err(NduProjectionStoreError::CorruptPointer);
    }
    let filename = lines
        .next()
        .ok_or(NduProjectionStoreError::CorruptPointer)?
        .to_string();
    if lines.next().is_some() {
        return Err(NduProjectionStoreError::CorruptPointer);
    }
    Ok((sequence, digest, filename))
}

fn snapshot_filename(sequence: u64, digest: Digest32) -> String {
    format!("journal-{sequence:016}-{digest}.bin")
}

fn temporary_path(root: &Path, label: &str) -> PathBuf {
    let nonce = TEMP_NONCE.fetch_add(1, Ordering::Relaxed);
    root.join(format!(".ndu-{label}-{}-{nonce}.tmp", std::process::id()))
}

fn create_private_new(path: &Path) -> Result<File, NduProjectionStoreError> {
    let mut options = OpenOptions::new();
    options.read(true).write(true).create_new(true);
    #[cfg(unix)]
    options.mode(0o600);
    Ok(options.open(path)?)
}

fn read_bounded(path: &Path, maximum: usize) -> Result<Vec<u8>, NduProjectionStoreError> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(NduProjectionStoreError::NotRegular);
    }
    if metadata.len() > maximum as u64 {
        return Err(NduProjectionStoreError::Capacity);
    }
    let mut file = File::open(path)?;
    let mut bytes = Vec::with_capacity(usize::try_from(metadata.len()).unwrap_or(maximum));
    (&mut file)
        .take(maximum as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum || file.metadata()?.len() != metadata.len() {
        return Err(NduProjectionStoreError::Capacity);
    }
    Ok(bytes)
}

#[cfg(test)]
#[path = "projection_store_tests.rs"]
mod tests;