use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;

use crate::PlannerJournalError;
use crate::PlannerJournalV1;

const STORE_MAGIC: &[u8; 8] = b"HCPSTR02";
const STORE_VERSION: u32 = 2;
const STORE_HEADER_BYTES: usize = 8 + 4 + 8 + 32;
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Debug)]
pub struct PlannerJournalStoreV1 {
    path: PathBuf,
    journal: PlannerJournalV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlannerJournalStoreError {
    Io(String),
    UnsupportedVersion(u32),
    CorruptEnvelope,
    Journal(PlannerJournalError),
}

impl fmt::Display for PlannerJournalStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlannerJournalStoreError {}

impl From<std::io::Error> for PlannerJournalStoreError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error.to_string())
    }
}

impl From<PlannerJournalError> for PlannerJournalStoreError {
    fn from(error: PlannerJournalError) -> Self {
        Self::Journal(error)
    }
}

impl PlannerJournalStoreV1 {
    pub fn create(path: impl AsRef<Path>) -> Result<Self, PlannerJournalStoreError> {
        let path = path.as_ref().to_path_buf();
        if path.exists() {
            return Err(PlannerJournalStoreError::Io(
                "planner journal store already exists".to_string(),
            ));
        }
        let mut store = Self {
            path,
            journal: PlannerJournalV1::new(),
        };
        let journal = store.journal.clone();
        store.commit(&journal)?;
        Ok(store)
    }

    pub fn open(path: impl AsRef<Path>) -> Result<Self, PlannerJournalStoreError> {
        let path = path.as_ref().to_path_buf();
        let bytes = fs::read(&path)?;
        if bytes.starts_with(b"HCPJNL01") {
            let journal = PlannerJournalV1::reopen(&bytes)?;
            let mut store = Self {
                path,
                journal: journal.clone(),
            };
            store.commit(&journal)?;
            return Ok(store);
        }
        let journal = decode_store(&bytes)?;
        Ok(Self { path, journal })
    }

    #[must_use]
    pub fn journal(&self) -> &PlannerJournalV1 {
        &self.journal
    }

    pub fn commit(
        &mut self,
        journal: &PlannerJournalV1,
    ) -> Result<(), PlannerJournalStoreError> {
        let canonical_bytes = journal.export_bytes();
        let validated = PlannerJournalV1::reopen(&canonical_bytes)?;
        let envelope = encode_store(&canonical_bytes);
        write_atomic(&self.path, &envelope)?;
        self.journal = validated;
        Ok(())
    }

    pub fn restore_journal_bytes(
        &mut self,
        journal_bytes: &[u8],
    ) -> Result<(), PlannerJournalStoreError> {
        let restored = PlannerJournalV1::reopen(journal_bytes)?;
        self.commit(&restored)
    }
}

fn encode_store(journal_bytes: &[u8]) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(STORE_HEADER_BYTES + journal_bytes.len());
    bytes.extend_from_slice(STORE_MAGIC);
    bytes.extend_from_slice(&STORE_VERSION.to_be_bytes());
    bytes.extend_from_slice(
        &u64::try_from(journal_bytes.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(Digest32::of_bytes(journal_bytes).as_array());
    bytes.extend_from_slice(journal_bytes);
    bytes
}

fn decode_store(bytes: &[u8]) -> Result<PlannerJournalV1, PlannerJournalStoreError> {
    if bytes.len() < STORE_HEADER_BYTES || &bytes[..8] != STORE_MAGIC {
        return Err(PlannerJournalStoreError::CorruptEnvelope);
    }
    let version = u32::from_be_bytes(
        bytes[8..12]
            .try_into()
            .map_err(|_| PlannerJournalStoreError::CorruptEnvelope)?,
    );
    if version != STORE_VERSION {
        return Err(PlannerJournalStoreError::UnsupportedVersion(version));
    }
    let journal_len_u64 = u64::from_be_bytes(
        bytes[12..20]
            .try_into()
            .map_err(|_| PlannerJournalStoreError::CorruptEnvelope)?,
    );
    let journal_len = usize::try_from(journal_len_u64)
        .map_err(|_| PlannerJournalStoreError::CorruptEnvelope)?;
    let expected = STORE_HEADER_BYTES
        .checked_add(journal_len)
        .ok_or(PlannerJournalStoreError::CorruptEnvelope)?;
    if bytes.len() != expected {
        return Err(PlannerJournalStoreError::CorruptEnvelope);
    }
    let stored_digest = Digest32::from_array(
        bytes[20..52]
            .try_into()
            .map_err(|_| PlannerJournalStoreError::CorruptEnvelope)?,
    );
    let journal_bytes = &bytes[STORE_HEADER_BYTES..];
    if stored_digest != Digest32::of_bytes(journal_bytes) {
        return Err(PlannerJournalStoreError::CorruptEnvelope);
    }
    PlannerJournalV1::reopen(journal_bytes).map_err(Into::into)
}

fn write_atomic(path: &Path, bytes: &[u8]) -> Result<(), PlannerJournalStoreError> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| PlannerJournalStoreError::Io("invalid planner store path".to_string()))?;
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let temp_path = parent.join(format!(".{name}.tmp-{}-{sequence}", std::process::id()));
    let result = (|| -> Result<(), PlannerJournalStoreError> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp_path)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temp_path, path)?;
        sync_parent(parent)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp_path);
    }
    result
}

#[cfg(unix)]
fn sync_parent(parent: &Path) -> Result<(), PlannerJournalStoreError> {
    std::fs::File::open(parent)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent(_parent: &Path) -> Result<(), PlannerJournalStoreError> {
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "planner_store_tests.rs"]
mod tests;
