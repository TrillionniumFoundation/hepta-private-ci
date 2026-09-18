use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::fs::TryLockError;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
#[cfg(unix)]
use std::sync::atomic::AtomicU64;
#[cfg(unix)]
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;

use crate::FeasiblePlanReceiptV1;
use crate::GlobalStateSnapshotV1;
use crate::PlannerJournalEntryV1;
use crate::PlannerJournalError;
use crate::PlannerJournalV1;

#[cfg(unix)]
const STORE_MAGIC: &[u8; 8] = b"HCPSTR01";
#[cfg(unix)]
const STORE_VERSION: u32 = 1;
#[cfg(unix)]
const STORE_HEADER_BYTES: usize = 8 + 4 + 8 + 32;
#[cfg(unix)]
const STORE_MAX_BYTES: u64 = 1024 * 1024;
#[cfg(unix)]
const JOURNAL_NAME: &str = "planner-journal.hcp";
#[cfg(unix)]
const LOCK_NAME: &str = "planner-journal.lock";
#[cfg(unix)]
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Debug)]
pub enum PlannerStoreErrorV1 {
    Io(std::io::Error),
    Journal(PlannerJournalError),
    Busy,
    UnsupportedPlatform,
    UnsafeState(&'static str),
    CorruptEnvelope,
    UnsupportedVersion(u32),
    RollbackDetected,
}

impl fmt::Display for PlannerStoreErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "planner store I/O failed: {error}"),
            Self::Journal(error) => write!(formatter, "planner journal rejected: {error}"),
            Self::Busy => formatter.write_str("planner store already has a live writer"),
            Self::UnsupportedPlatform => {
                formatter.write_str("durable planner store requires a Unix durability profile")
            }
            Self::UnsafeState(message) => {
                write!(formatter, "unsafe planner store state: {message}")
            }
            Self::CorruptEnvelope => formatter.write_str("corrupt planner store envelope"),
            Self::UnsupportedVersion(version) => {
                write!(formatter, "unsupported planner store version {version}")
            }
            Self::RollbackDetected => {
                formatter.write_str("planner store is older than the trusted persisted head")
            }
        }
    }
}

impl StdError for PlannerStoreErrorV1 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::Journal(error) => Some(error),
            _ => None,
        }
    }
}

impl From<std::io::Error> for PlannerStoreErrorV1 {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}

impl From<PlannerJournalError> for PlannerStoreErrorV1 {
    fn from(error: PlannerJournalError) -> Self {
        Self::Journal(error)
    }
}

/// Single-writer, fsync-backed persistence for PlannerJournalV1.
///
/// The caller retains trusted_head() outside the journal backup domain.
/// Reopening with that head rejects restoration of an older otherwise-valid
/// backup. The file lock fences concurrent local writers. V0 bare HCPJNL01
/// bytes are deterministically migrated to the HCPSTR01 envelope on open.
pub struct PlannerJournalStoreV1 {
    root: PathBuf,
    journal_path: PathBuf,
    _lock: File,
    journal: PlannerJournalV1,
}

impl PlannerJournalStoreV1 {
    pub fn open(root: &Path) -> Result<Self, PlannerStoreErrorV1> {
        Self::open_with_minimum_head(root, None)
    }

    pub fn open_with_minimum_head(
        root: &Path,
        minimum_head: Option<Digest32>,
    ) -> Result<Self, PlannerStoreErrorV1> {
        #[cfg(not(unix))]
        {
            let _ = (root, minimum_head);
            return Err(PlannerStoreErrorV1::UnsupportedPlatform);
        }

        #[cfg(unix)]
        {
            verify_secure_root(root)?;
            let lock = open_and_lock(&root.join(LOCK_NAME))?;
            let journal_path = root.join(JOURNAL_NAME);
            let (journal, needs_migration) = if journal_path.exists() {
                decode_store(&secure_read(&journal_path)?)?
            } else {
                if minimum_head.is_some() {
                    return Err(PlannerStoreErrorV1::RollbackDetected);
                }
                (PlannerJournalV1::new(), false)
            };
            enforce_minimum_head(&journal, minimum_head)?;
            let store = Self {
                root: root.to_path_buf(),
                journal_path,
                _lock: lock,
                journal,
            };
            if needs_migration {
                store.persist(&store.journal)?;
            }
            Ok(store)
        }
    }

    #[must_use]
    pub fn journal(&self) -> &PlannerJournalV1 {
        &self.journal
    }

    #[must_use]
    pub fn trusted_head(&self) -> Option<Digest32> {
        self.journal
            .entries()
            .last()
            .map(|entry| entry.entry_digest)
    }

    #[must_use]
    pub fn journal_path(&self) -> &Path {
        &self.journal_path
    }

    pub fn record_snapshot(
        &mut self,
        snapshot: &GlobalStateSnapshotV1,
    ) -> Result<PlannerJournalEntryV1, PlannerStoreErrorV1> {
        self.transact(|journal| journal.record_snapshot(snapshot))
    }

    pub fn record_decision(
        &mut self,
        receipt: &FeasiblePlanReceiptV1,
    ) -> Result<PlannerJournalEntryV1, PlannerStoreErrorV1> {
        self.transact(|journal| journal.record_decision(receipt))
    }

    pub fn select_plan(
        &mut self,
        operation_identity_digest: Digest32,
        receipt: &FeasiblePlanReceiptV1,
    ) -> Result<PlannerJournalEntryV1, PlannerStoreErrorV1> {
        self.transact(|journal| journal.select_plan(operation_identity_digest, receipt))
    }

    pub fn revoke(
        &mut self,
        revocation_identity_digest: Digest32,
        target_digest: Digest32,
    ) -> Result<PlannerJournalEntryV1, PlannerStoreErrorV1> {
        self.transact(|journal| journal.revoke(revocation_identity_digest, target_digest))
    }

    fn transact<F>(&mut self, mutation: F) -> Result<PlannerJournalEntryV1, PlannerStoreErrorV1>
    where
        F: FnOnce(&mut PlannerJournalV1) -> Result<PlannerJournalEntryV1, PlannerJournalError>,
    {
        let mut candidate = self.journal.clone();
        let entry = mutation(&mut candidate)?;
        self.persist(&candidate)?;
        self.journal = candidate;
        Ok(entry)
    }

    fn persist(&self, journal: &PlannerJournalV1) -> Result<(), PlannerStoreErrorV1> {
        #[cfg(not(unix))]
        {
            let _ = journal;
            return Err(PlannerStoreErrorV1::UnsupportedPlatform);
        }

        #[cfg(unix)]
        {
            verify_secure_root(&self.root)?;
            if self.journal_path.exists() {
                let _ = secure_read(&self.journal_path)?;
            }
            let bytes = encode_store(journal)?;
            let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
            let temporary = self.root.join(format!(
                ".planner-journal.tmp-{}-{sequence}",
                std::process::id()
            ));
            let result = (|| -> Result<(), PlannerStoreErrorV1> {
                let mut options = OpenOptions::new();
                options.write(true).create_new(true);
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
                let mut file = options.open(&temporary)?;
                file.write_all(&bytes)?;
                file.sync_all()?;
                drop(file);
                std::fs::rename(&temporary, &self.journal_path)?;
                File::open(&self.root)?.sync_all()?;
                let persisted = secure_read(&self.journal_path)?;
                if persisted != bytes {
                    return Err(PlannerStoreErrorV1::CorruptEnvelope);
                }
                let (reopened, migrated) = decode_store(&persisted)?;
                if migrated || reopened.entries() != journal.entries() {
                    return Err(PlannerStoreErrorV1::CorruptEnvelope);
                }
                Ok(())
            })();
            if result.is_err() {
                let _ = std::fs::remove_file(&temporary);
            }
            result
        }
    }
}

impl Drop for PlannerJournalStoreV1 {
    fn drop(&mut self) {
        let _ = self._lock.unlock();
    }
}

#[cfg(unix)]
fn enforce_minimum_head(
    journal: &PlannerJournalV1,
    minimum_head: Option<Digest32>,
) -> Result<(), PlannerStoreErrorV1> {
    let Some(minimum_head) = minimum_head else {
        return Ok(());
    };
    if minimum_head.is_zero() {
        return Err(PlannerStoreErrorV1::UnsafeState(
            "trusted minimum head must be nonzero",
        ));
    }
    if journal
        .entries()
        .iter()
        .any(|entry| entry.entry_digest == minimum_head)
    {
        Ok(())
    } else {
        Err(PlannerStoreErrorV1::RollbackDetected)
    }
}

#[cfg(unix)]
fn encode_store(journal: &PlannerJournalV1) -> Result<Vec<u8>, PlannerStoreErrorV1> {
    let payload = journal.export_bytes();
    let payload_len =
        u64::try_from(payload.len()).map_err(|_| PlannerStoreErrorV1::CorruptEnvelope)?;
    let total = STORE_HEADER_BYTES
        .checked_add(payload.len())
        .ok_or(PlannerStoreErrorV1::CorruptEnvelope)?;
    if u64::try_from(total).unwrap_or(u64::MAX) > STORE_MAX_BYTES {
        return Err(PlannerStoreErrorV1::CorruptEnvelope);
    }
    let mut bytes = Vec::with_capacity(total);
    bytes.extend_from_slice(STORE_MAGIC);
    bytes.extend_from_slice(&STORE_VERSION.to_be_bytes());
    bytes.extend_from_slice(&payload_len.to_be_bytes());
    bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
    bytes.extend_from_slice(&payload);
    Ok(bytes)
}

#[cfg(unix)]
fn decode_store(bytes: &[u8]) -> Result<(PlannerJournalV1, bool), PlannerStoreErrorV1> {
    if bytes.starts_with(b"HCPJNL01") {
        return Ok((PlannerJournalV1::reopen(bytes)?, true));
    }
    if bytes.len() < STORE_HEADER_BYTES || &bytes[..8] != STORE_MAGIC {
        return Err(PlannerStoreErrorV1::CorruptEnvelope);
    }
    let version = u32::from_be_bytes(
        bytes[8..12]
            .try_into()
            .map_err(|_| PlannerStoreErrorV1::CorruptEnvelope)?,
    );
    if version != STORE_VERSION {
        return Err(PlannerStoreErrorV1::UnsupportedVersion(version));
    }
    let payload_len = u64::from_be_bytes(
        bytes[12..20]
            .try_into()
            .map_err(|_| PlannerStoreErrorV1::CorruptEnvelope)?,
    );
    let payload_len =
        usize::try_from(payload_len).map_err(|_| PlannerStoreErrorV1::CorruptEnvelope)?;
    let expected = STORE_HEADER_BYTES
        .checked_add(payload_len)
        .ok_or(PlannerStoreErrorV1::CorruptEnvelope)?;
    if bytes.len() != expected || u64::try_from(expected).unwrap_or(u64::MAX) > STORE_MAX_BYTES {
        return Err(PlannerStoreErrorV1::CorruptEnvelope);
    }
    let declared = Digest32::from_array(
        bytes[20..52]
            .try_into()
            .map_err(|_| PlannerStoreErrorV1::CorruptEnvelope)?,
    );
    let payload = &bytes[STORE_HEADER_BYTES..];
    if Digest32::of_bytes(payload) != declared {
        return Err(PlannerStoreErrorV1::CorruptEnvelope);
    }
    Ok((PlannerJournalV1::reopen(payload)?, false))
}

#[cfg(unix)]
fn open_and_lock(path: &Path) -> Result<File, PlannerStoreErrorV1> {
    let mut options = OpenOptions::new();
    options.create(true).read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options.open(path)?;
    verify_private_file(path, &file)?;
    match file.try_lock() {
        Ok(()) => Ok(file),
        Err(TryLockError::WouldBlock) => Err(PlannerStoreErrorV1::Busy),
        Err(TryLockError::Error(error)) => Err(error.into()),
    }
}

#[cfg(unix)]
fn secure_read(path: &Path) -> Result<Vec<u8>, PlannerStoreErrorV1> {
    let link = std::fs::symlink_metadata(path)?;
    if link.file_type().is_symlink() || !link.is_file() {
        return Err(PlannerStoreErrorV1::UnsafeState(
            "journal must be a regular non-symlink file",
        ));
    }
    if link.len() > STORE_MAX_BYTES {
        return Err(PlannerStoreErrorV1::CorruptEnvelope);
    }
    let mut file = File::open(path)?;
    verify_private_file(path, &file)?;
    let capacity = usize::try_from(link.len()).map_err(|_| PlannerStoreErrorV1::CorruptEnvelope)?;
    let mut bytes = Vec::with_capacity(capacity);
    file.read_to_end(&mut bytes)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > STORE_MAX_BYTES {
        return Err(PlannerStoreErrorV1::CorruptEnvelope);
    }
    Ok(bytes)
}

#[cfg(unix)]
fn verify_secure_root(root: &Path) -> Result<(), PlannerStoreErrorV1> {
    let metadata = std::fs::symlink_metadata(root)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(PlannerStoreErrorV1::UnsafeState(
            "store root must be an existing non-symlink directory",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(PlannerStoreErrorV1::UnsafeState(
                "store root must not grant group or other permissions",
            ));
        }
    }
    Ok(())
}

#[cfg(unix)]
fn verify_private_file(path: &Path, file: &File) -> Result<(), PlannerStoreErrorV1> {
    let fd_metadata = file.metadata()?;
    let path_metadata = std::fs::metadata(path)?;
    let link_metadata = std::fs::symlink_metadata(path)?;
    if !fd_metadata.is_file() || link_metadata.file_type().is_symlink() {
        return Err(PlannerStoreErrorV1::UnsafeState(
            "planner store file must be a regular non-symlink file",
        ));
    }
    if !same_file_identity(&fd_metadata, &path_metadata)
        || !same_file_identity(&fd_metadata, &link_metadata)
    {
        return Err(PlannerStoreErrorV1::UnsafeState(
            "planner store file identity changed while opening",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;
        if fd_metadata.nlink() != 1 || fd_metadata.permissions().mode() & 0o077 != 0 {
            return Err(PlannerStoreErrorV1::UnsafeState(
                "planner store file must be private and have one hard link",
            ));
        }
    }
    Ok(())
}

#[cfg(unix)]
fn same_file_identity(left: &std::fs::Metadata, right: &std::fs::Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        left.dev() == right.dev() && left.ino() == right.ino()
    }
    #[cfg(not(unix))]
    {
        left.len() == right.len() && left.modified().ok() == right.modified().ok()
    }
}

#[cfg(all(test, unix))]
#[path = "planner_store_tests.rs"]
mod tests;
