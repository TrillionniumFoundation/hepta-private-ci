use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

use crate::PlannerJournalError;
use crate::PlannerJournalV1;

const STORE_MAGIC: &[u8; 8] = b"HCPSTR01";
const STORE_HEADER_BYTES: usize = 8 + 8 + 4 + 32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerStoreError {
    Io,
    UnsafeDirectory,
    InvalidStoreId,
    Locked,
    RecoveryRequired,
    NonMonotonicReplace,
    GenerationOverflow,
    Journal(PlannerJournalError),
}

impl fmt::Display for PlannerStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlannerStoreError {}

impl From<PlannerJournalError> for PlannerStoreError {
    fn from(error: PlannerJournalError) -> Self {
        Self::Journal(error)
    }
}

/// Owner-local durable planner journal store.
///
/// Each successful persist publishes one immutable generation file after
/// syncing the file and containing directory. A process-local lock file fences
/// concurrent writers. Stale lock files and any corrupt/gapped generation
/// require explicit recovery rather than guessing which state is authoritative.
///
/// This store prevents rollback within one surviving directory by requiring
/// every successor journal to extend the previously opened journal. Restoring
/// the entire directory from an older backup still requires an independent
/// anti-rollback witness before production use.
pub struct PlannerDurableStoreV1 {
    directory: PathBuf,
    store_id: String,
    lock_path: PathBuf,
    _lock: File,
    current_generation: u64,
    journal: PlannerJournalV1,
    failed: bool,
}

impl PlannerDurableStoreV1 {
    pub fn open(directory: &Path, store_id: &str) -> Result<Self, PlannerStoreError> {
        validate_store_id(store_id)?;
        let metadata = fs::symlink_metadata(directory).map_err(|_| PlannerStoreError::Io)?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(PlannerStoreError::UnsafeDirectory);
        }

        let lock_path = directory.join(format!(".{store_id}.lock"));
        let mut lock = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
            .map_err(|error| {
                if error.kind() == std::io::ErrorKind::AlreadyExists {
                    PlannerStoreError::Locked
                } else {
                    PlannerStoreError::Io
                }
            })?;
        lock.write_all(std::process::id().to_string().as_bytes())
            .map_err(|_| PlannerStoreError::Io)?;
        lock.sync_all().map_err(|_| PlannerStoreError::Io)?;

        let loaded = load_generations(directory, store_id);
        let (current_generation, journal) = match loaded {
            Ok(value) => value,
            Err(error) => {
                drop(lock);
                let _ = fs::remove_file(&lock_path);
                return Err(error);
            }
        };

        Ok(Self {
            directory: directory.to_path_buf(),
            store_id: store_id.to_string(),
            lock_path,
            _lock: lock,
            current_generation,
            journal,
            failed: false,
        })
    }

    #[must_use]
    pub const fn current_generation(&self) -> u64 {
        self.current_generation
    }

    #[must_use]
    pub const fn journal(&self) -> &PlannerJournalV1 {
        &self.journal
    }

    pub fn persist(&mut self, next: &PlannerJournalV1) -> Result<(), PlannerStoreError> {
        if self.failed {
            return Err(PlannerStoreError::RecoveryRequired);
        }

        let canonical = PlannerJournalV1::reopen(&next.export_bytes())?;
        if canonical.entries() == self.journal.entries() {
            return Ok(());
        }
        if !is_prefix(self.journal.entries(), canonical.entries()) {
            return Err(PlannerStoreError::NonMonotonicReplace);
        }

        let generation = self
            .current_generation
            .checked_add(1)
            .ok_or(PlannerStoreError::GenerationOverflow)?;
        let path = generation_path(&self.directory, &self.store_id, generation);
        let encoded = encode_generation(generation, &canonical)?;

        let result = (|| -> Result<(), PlannerStoreError> {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&path)
                .map_err(|_| PlannerStoreError::Io)?;
            file.write_all(&encoded).map_err(|_| PlannerStoreError::Io)?;
            file.sync_all().map_err(|_| PlannerStoreError::Io)?;
            sync_directory(&self.directory)?;
            Ok(())
        })();

        if let Err(error) = result {
            self.failed = true;
            return Err(match error {
                PlannerStoreError::Io => PlannerStoreError::RecoveryRequired,
                other => other,
            });
        }

        self.current_generation = generation;
        self.journal = canonical;
        Ok(())
    }
}

impl Drop for PlannerDurableStoreV1 {
    fn drop(&mut self) {
        if !self.failed {
            let _ = fs::remove_file(&self.lock_path);
            let _ = sync_directory(&self.directory);
        }
    }
}

fn validate_store_id(store_id: &str) -> Result<(), PlannerStoreError> {
    if store_id.is_empty()
        || store_id.len() > 64
        || !store_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
    {
        return Err(PlannerStoreError::InvalidStoreId);
    }
    Ok(())
}

fn load_generations(
    directory: &Path,
    store_id: &str,
) -> Result<(u64, PlannerJournalV1), PlannerStoreError> {
    let prefix = format!("{store_id}.v1.");
    let suffix = ".journal";
    let mut generations = Vec::new();
    for entry in fs::read_dir(directory).map_err(|_| PlannerStoreError::Io)? {
        let entry = entry.map_err(|_| PlannerStoreError::Io)?;
        let file_type = entry.file_type().map_err(|_| PlannerStoreError::Io)?;
        if !file_type.is_file() {
            continue;
        }
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            continue;
        };
        if !name.starts_with(&prefix) || !name.ends_with(suffix) {
            continue;
        }
        let raw = &name[prefix.len()..name.len() - suffix.len()];
        let generation = raw
            .parse::<u64>()
            .map_err(|_| PlannerStoreError::RecoveryRequired)?;
        if generation == 0 {
            return Err(PlannerStoreError::RecoveryRequired);
        }
        generations.push((generation, entry.path()));
    }
    generations.sort_by_key(|(generation, _)| *generation);

    let mut current_generation = 0_u64;
    let mut current = PlannerJournalV1::new();
    for (index, (generation, path)) in generations.into_iter().enumerate() {
        let expected_generation = u64::try_from(index)
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(PlannerStoreError::GenerationOverflow)?;
        if generation != expected_generation {
            return Err(PlannerStoreError::RecoveryRequired);
        }
        let next = read_generation(&path, generation)?;
        if !is_prefix(current.entries(), next.entries()) {
            return Err(PlannerStoreError::RecoveryRequired);
        }
        current_generation = generation;
        current = next;
    }
    Ok((current_generation, current))
}

fn generation_path(directory: &Path, store_id: &str, generation: u64) -> PathBuf {
    directory.join(format!("{store_id}.v1.{generation:020}.journal"))
}

fn encode_generation(
    generation: u64,
    journal: &PlannerJournalV1,
) -> Result<Vec<u8>, PlannerStoreError> {
    let payload = journal.export_bytes();
    let payload_len =
        u32::try_from(payload.len()).map_err(|_| PlannerStoreError::RecoveryRequired)?;
    let digest = Digest32::of_bytes(&payload);
    let mut bytes = Vec::with_capacity(STORE_HEADER_BYTES + payload.len());
    bytes.extend_from_slice(STORE_MAGIC);
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(&payload_len.to_be_bytes());
    bytes.extend_from_slice(digest.as_array());
    bytes.extend_from_slice(&payload);
    Ok(bytes)
}

fn read_generation(
    path: &Path,
    expected_generation: u64,
) -> Result<PlannerJournalV1, PlannerStoreError> {
    let mut file = File::open(path).map_err(|_| PlannerStoreError::RecoveryRequired)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)
        .map_err(|_| PlannerStoreError::RecoveryRequired)?;
    if bytes.len() < STORE_HEADER_BYTES || &bytes[..8] != STORE_MAGIC {
        return Err(PlannerStoreError::RecoveryRequired);
    }
    let generation = u64::from_be_bytes(
        bytes[8..16]
            .try_into()
            .map_err(|_| PlannerStoreError::RecoveryRequired)?,
    );
    if generation != expected_generation {
        return Err(PlannerStoreError::RecoveryRequired);
    }
    let payload_len = u32::from_be_bytes(
        bytes[16..20]
            .try_into()
            .map_err(|_| PlannerStoreError::RecoveryRequired)?,
    );
    let payload_len =
        usize::try_from(payload_len).map_err(|_| PlannerStoreError::RecoveryRequired)?;
    let digest = Digest32::from_array(
        bytes[20..52]
            .try_into()
            .map_err(|_| PlannerStoreError::RecoveryRequired)?,
    );
    let payload = bytes
        .get(STORE_HEADER_BYTES..)
        .ok_or(PlannerStoreError::RecoveryRequired)?;
    if payload.len() != payload_len || Digest32::of_bytes(payload) != digest {
        return Err(PlannerStoreError::RecoveryRequired);
    }
    PlannerJournalV1::reopen(payload).map_err(PlannerStoreError::Journal)
}

fn is_prefix(
    previous: &[crate::PlannerJournalEntryV1],
    next: &[crate::PlannerJournalEntryV1],
) -> bool {
    previous.len() <= next.len() && previous.iter().zip(next).all(|(left, right)| left == right)
}

#[cfg(unix)]
fn sync_directory(directory: &Path) -> Result<(), PlannerStoreError> {
    File::open(directory)
        .and_then(|file| file.sync_all())
        .map_err(|_| PlannerStoreError::RecoveryRequired)
}

#[cfg(not(unix))]
fn sync_directory(_directory: &Path) -> Result<(), PlannerStoreError> {
    Ok(())
}

#[cfg(test)]
#[path = "planner_store_tests.rs"]
mod tests;
