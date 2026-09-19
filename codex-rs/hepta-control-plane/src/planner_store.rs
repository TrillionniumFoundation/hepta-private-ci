use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;

use crate::PlannerJournalError;
use crate::PlannerJournalV1;

const CURRENT_FILE: &str = "planner.journal";
const BACKUP_FILE: &str = "planner.journal.bak";
const FRONTIER_FILE: &str = "planner.frontier";
const STORE_MAGIC: &[u8; 8] = b"HCPSTR01";
const FRONTIER_MAGIC: &[u8; 8] = b"HCPFRT01";
const STORE_SCHEMA: u32 = 1;
const FRONTIER_BYTES: usize = 8 + 4 + 8 + 32;
const MAX_STORE_BYTES: usize = 8 * 1024 * 1024;
static TEMP_COUNTER: AtomicU64 = AtomicU64::new(1);

#[derive(Debug)]
pub struct PlannerJournalStoreV1 {
    root: PathBuf,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerStoreError {
    Io(std::io::ErrorKind),
    CorruptHeader,
    UnsupportedSchema(u32),
    Truncated,
    Oversized,
    DigestMismatch,
    FrontierMismatch,
    RestoreUnavailable,
    Journal(PlannerJournalError),
}

impl fmt::Display for PlannerStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlannerStoreError {}

impl From<std::io::Error> for PlannerStoreError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error.kind())
    }
}

impl From<PlannerJournalError> for PlannerStoreError {
    fn from(error: PlannerJournalError) -> Self {
        Self::Journal(error)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct FrontierV1 {
    record_count: u64,
    store_digest: Digest32,
}

impl PlannerJournalStoreV1 {
    pub fn open(root: impl AsRef<Path>) -> Result<(Self, PlannerJournalV1), PlannerStoreError> {
        let root = root.as_ref().to_path_buf();
        fs::create_dir_all(&root)?;
        let store = Self { root };
        let current = store.root.join(CURRENT_FILE);
        if !current.exists() {
            let journal = PlannerJournalV1::new();
            store.commit(&journal)?;
            return Ok((store, journal));
        }

        let frontier_path = store.root.join(FRONTIER_FILE);
        if !frontier_path.exists() {
            let raw = read_bounded(&current)?;
            if !raw.starts_with(b"HCPJNL01") {
                return Err(PlannerStoreError::FrontierMismatch);
            }
            let journal = PlannerJournalV1::reopen(&raw)?;
            store.commit(&journal)?;
            return Ok((store, journal));
        }

        let frontier = decode_frontier(&read_bounded(&frontier_path)?)?;
        match store.read_if_frontier_matches(&current, frontier) {
            Ok(journal) => Ok((store, journal)),
            Err(PlannerStoreError::FrontierMismatch)
            | Err(PlannerStoreError::DigestMismatch)
            | Err(PlannerStoreError::Truncated)
            | Err(PlannerStoreError::CorruptHeader)
            | Err(PlannerStoreError::Journal(_)) => {
                let backup = store.root.join(BACKUP_FILE);
                let journal = store
                    .read_if_frontier_matches(&backup, frontier)
                    .map_err(|_| PlannerStoreError::FrontierMismatch)?;
                let bytes = read_bounded(&backup)?;
                atomic_write(&store.root, &current, &bytes)?;
                Ok((store, journal))
            }
            Err(error) => Err(error),
        }
    }

    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn reopen(&self) -> Result<PlannerJournalV1, PlannerStoreError> {
        let frontier = decode_frontier(&read_bounded(&self.root.join(FRONTIER_FILE))?)?;
        self.read_if_frontier_matches(&self.root.join(CURRENT_FILE), frontier)
    }

    pub fn commit(&self, journal: &PlannerJournalV1) -> Result<Digest32, PlannerStoreError> {
        let encoded = encode_store(journal)?;
        let store_digest = Digest32::of_bytes(&encoded);
        let current = self.root.join(CURRENT_FILE);
        let backup = self.root.join(BACKUP_FILE);
        if current.exists() {
            let previous = read_bounded(&current)?;
            decode_store(&previous)?;
            atomic_write(&self.root, &backup, &previous)?;
        }
        atomic_write(&self.root, &current, &encoded)?;
        let frontier = FrontierV1 {
            record_count: u64::try_from(journal.entries().len())
                .map_err(|_| PlannerStoreError::Oversized)?,
            store_digest,
        };
        atomic_write(
            &self.root,
            &self.root.join(FRONTIER_FILE),
            &encode_frontier(frontier),
        )?;
        sync_directory(&self.root)?;
        Ok(store_digest)
    }

    pub fn restore_backup(&self) -> Result<PlannerJournalV1, PlannerStoreError> {
        let frontier_path = self.root.join(FRONTIER_FILE);
        if !frontier_path.exists() {
            return Err(PlannerStoreError::RestoreUnavailable);
        }
        let frontier = decode_frontier(&read_bounded(&frontier_path)?)?;
        let backup = self.root.join(BACKUP_FILE);
        let journal = self
            .read_if_frontier_matches(&backup, frontier)
            .map_err(|_| PlannerStoreError::RestoreUnavailable)?;
        let bytes = read_bounded(&backup)?;
        atomic_write(&self.root, &self.root.join(CURRENT_FILE), &bytes)?;
        Ok(journal)
    }

    fn read_if_frontier_matches(
        &self,
        path: &Path,
        frontier: FrontierV1,
    ) -> Result<PlannerJournalV1, PlannerStoreError> {
        if !path.exists() {
            return Err(PlannerStoreError::RestoreUnavailable);
        }
        let bytes = read_bounded(path)?;
        if Digest32::of_bytes(&bytes) != frontier.store_digest {
            return Err(PlannerStoreError::FrontierMismatch);
        }
        let journal = decode_store(&bytes)?;
        if u64::try_from(journal.entries().len()).map_err(|_| PlannerStoreError::Oversized)?
            != frontier.record_count
        {
            return Err(PlannerStoreError::FrontierMismatch);
        }
        Ok(journal)
    }
}

fn encode_store(journal: &PlannerJournalV1) -> Result<Vec<u8>, PlannerStoreError> {
    let payload = journal.export_bytes();
    let payload_len = u64::try_from(payload.len()).map_err(|_| PlannerStoreError::Oversized)?;
    let mut bytes = Vec::with_capacity(8 + 4 + 8 + 32 + payload.len());
    bytes.extend_from_slice(STORE_MAGIC);
    bytes.extend_from_slice(&STORE_SCHEMA.to_be_bytes());
    bytes.extend_from_slice(&payload_len.to_be_bytes());
    bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
    bytes.extend_from_slice(&payload);
    if bytes.len() > MAX_STORE_BYTES {
        return Err(PlannerStoreError::Oversized);
    }
    Ok(bytes)
}

fn decode_store(bytes: &[u8]) -> Result<PlannerJournalV1, PlannerStoreError> {
    if bytes.len() > MAX_STORE_BYTES {
        return Err(PlannerStoreError::Oversized);
    }
    if bytes.starts_with(b"HCPJNL01") {
        return PlannerJournalV1::reopen(bytes).map_err(Into::into);
    }
    if bytes.len() < 52 {
        return Err(PlannerStoreError::Truncated);
    }
    if &bytes[..8] != STORE_MAGIC {
        return Err(PlannerStoreError::CorruptHeader);
    }
    let schema = u32::from_be_bytes(
        bytes[8..12]
            .try_into()
            .map_err(|_| PlannerStoreError::Truncated)?,
    );
    if schema != STORE_SCHEMA {
        return Err(PlannerStoreError::UnsupportedSchema(schema));
    }
    let payload_len = usize::try_from(u64::from_be_bytes(
        bytes[12..20]
            .try_into()
            .map_err(|_| PlannerStoreError::Truncated)?,
    ))
    .map_err(|_| PlannerStoreError::Oversized)?;
    let expected = 52_usize
        .checked_add(payload_len)
        .ok_or(PlannerStoreError::Oversized)?;
    if bytes.len() != expected {
        return Err(PlannerStoreError::Truncated);
    }
    let payload_digest = Digest32::from_array(
        bytes[20..52]
            .try_into()
            .map_err(|_| PlannerStoreError::Truncated)?,
    );
    let payload = &bytes[52..];
    if Digest32::of_bytes(payload) != payload_digest {
        return Err(PlannerStoreError::DigestMismatch);
    }
    PlannerJournalV1::reopen(payload).map_err(Into::into)
}

fn encode_frontier(frontier: FrontierV1) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(FRONTIER_BYTES);
    bytes.extend_from_slice(FRONTIER_MAGIC);
    bytes.extend_from_slice(&STORE_SCHEMA.to_be_bytes());
    bytes.extend_from_slice(&frontier.record_count.to_be_bytes());
    bytes.extend_from_slice(frontier.store_digest.as_array());
    bytes
}

fn decode_frontier(bytes: &[u8]) -> Result<FrontierV1, PlannerStoreError> {
    if bytes.len() != FRONTIER_BYTES {
        return Err(PlannerStoreError::Truncated);
    }
    if &bytes[..8] != FRONTIER_MAGIC {
        return Err(PlannerStoreError::CorruptHeader);
    }
    let schema = u32::from_be_bytes(
        bytes[8..12]
            .try_into()
            .map_err(|_| PlannerStoreError::Truncated)?,
    );
    if schema != STORE_SCHEMA {
        return Err(PlannerStoreError::UnsupportedSchema(schema));
    }
    let record_count = u64::from_be_bytes(
        bytes[12..20]
            .try_into()
            .map_err(|_| PlannerStoreError::Truncated)?,
    );
    let store_digest = Digest32::from_array(
        bytes[20..52]
            .try_into()
            .map_err(|_| PlannerStoreError::Truncated)?,
    );
    Ok(FrontierV1 {
        record_count,
        store_digest,
    })
}

fn read_bounded(path: &Path) -> Result<Vec<u8>, PlannerStoreError> {
    let mut file = File::open(path)?;
    let metadata = file.metadata()?;
    let size = usize::try_from(metadata.len()).map_err(|_| PlannerStoreError::Oversized)?;
    if size > MAX_STORE_BYTES {
        return Err(PlannerStoreError::Oversized);
    }
    let mut bytes = Vec::with_capacity(size);
    file.read_to_end(&mut bytes)?;
    if bytes.len() != size {
        return Err(PlannerStoreError::Truncated);
    }
    Ok(bytes)
}

fn atomic_write(root: &Path, target: &Path, bytes: &[u8]) -> Result<(), PlannerStoreError> {
    if bytes.len() > MAX_STORE_BYTES {
        return Err(PlannerStoreError::Oversized);
    }
    let sequence = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
    let name = target
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(PlannerStoreError::CorruptHeader)?;
    let temp = root.join(format!(".{name}.{}.{}.tmp", std::process::id(), sequence));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temp)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);

    #[cfg(windows)]
    if target.exists() {
        fs::remove_file(target)?;
    }
    fs::rename(&temp, target)?;
    sync_directory(root)?;
    Ok(())
}

#[cfg(unix)]
fn sync_directory(root: &Path) -> Result<(), PlannerStoreError> {
    File::open(root)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_directory(_root: &Path) -> Result<(), PlannerStoreError> {
    Ok(())
}

#[cfg(test)]
#[path = "planner_store_tests.rs"]
mod tests;
