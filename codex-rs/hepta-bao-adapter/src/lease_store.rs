//! Append-only durable metadata journal for the HeptaBao lease coordinator.
//!
//! The journal contains no raw secret bytes. A complete newline-terminated
//! frame is the publication boundary. An incomplete trailing frame after a
//! crash is conservatively truncated on reopen, leaving the prior intent in a
//! reconcile-only state.

use std::fmt;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;

use codex_hepta_contracts::ProviderEffectAppendDisposition;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::BaoLeaseError;
use super::LeaseJournalRecord;
use super::StoreState;
use super::StoredOperation;
use super::apply_record;
use super::intent_for;

const JOURNAL_MAGIC: &[u8] = b"HEPTA-BAO-LEASE-JOURNAL-V1\n";
const JOURNAL_SCHEMA: u32 = 1;
const MAX_JOURNAL_BYTES: u64 = 64 * 1024 * 1024;
const MAX_FRAME_BYTES: usize = 32 * 1024;
const MAX_RECORDS: u64 = 1_000_000;

#[derive(Serialize)]
struct FrameCore<'a> {
    schema: u32,
    sequence: u64,
    previous_sha256: [u8; 32],
    record: &'a LeaseJournalRecord,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct JournalFrame {
    schema: u32,
    sequence: u64,
    previous_sha256: [u8; 32],
    record: LeaseJournalRecord,
    frame_sha256: [u8; 32],
}

pub(super) struct LeaseStore {
    root: File,
    journal: File,
    _lock: File,
    sequence: u64,
    tail_sha256: [u8; 32],
    state: StoreState,
    failed: bool,
}

impl fmt::Debug for LeaseStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LeaseStore")
            .field("sequence", &self.sequence)
            .field("operation_count", &self.state.operations.len())
            .field("lease_count", &self.state.leases.len())
            .finish()
    }
}

impl LeaseStore {
    pub(super) fn open(root: &Path, provider_scope: &str) -> Result<Self, BaoLeaseError> {
        let root = prepare_directory(root)?;
        let lock_preexisted = entry_exists(&root, "lease.lock")?;
        let journal_preexisted = entry_exists(&root, "lease.journal")?;
        let lock = open_private(&root, "lease.lock", Access::Create)?;
        lock.try_lock().map_err(|_| BaoLeaseError::StateLocked)?;

        if !journal_preexisted && lock_preexisted {
            return Err(BaoLeaseError::StateCorrupt);
        }

        let mut journal = open_private(&root, "lease.journal", Access::Append)?;
        if !journal_preexisted {
            journal
                .set_len(0)
                .and_then(|()| journal.write_all(JOURNAL_MAGIC))
                .and_then(|()| journal.sync_all())
                .map_err(|_| BaoLeaseError::StateUnavailable)?;
            root.sync_all()
                .map_err(|_| BaoLeaseError::StateUnavailable)?;
        }

        let (state, sequence, tail_sha256, complete_len) = load_journal(&mut journal)?;
        let current_len = journal
            .metadata()
            .map_err(|_| BaoLeaseError::StateUnavailable)?
            .len();
        if complete_len < current_len {
            journal
                .set_len(complete_len)
                .and_then(|()| journal.sync_all())
                .map_err(|_| BaoLeaseError::StateUnavailable)?;
        }
        journal
            .seek(SeekFrom::End(0))
            .map_err(|_| BaoLeaseError::StateUnavailable)?;

        let mut store = Self {
            root,
            journal,
            _lock: lock,
            sequence,
            tail_sha256,
            state,
            failed: false,
        };

        if !journal_preexisted {
            store.append(LeaseJournalRecord::Initialize {
                provider_scope: provider_scope.to_string(),
            })?;
        }
        if store.state.provider_scope.as_deref() != Some(provider_scope) {
            return Err(BaoLeaseError::InvalidConfiguration);
        }
        Ok(store)
    }

    pub(super) fn state(&self) -> &StoreState {
        &self.state
    }

    pub(super) fn ensure_intent(
        &mut self,
        stored: StoredOperation,
    ) -> Result<ProviderEffectAppendDisposition, BaoLeaseError> {
        if let Some(existing) = self.state.operations.get(&stored.operation.operation_id) {
            if existing == &stored {
                return Ok(ProviderEffectAppendDisposition::AlreadyPresent);
            }
            return Err(BaoLeaseError::OperationConflict);
        }
        let provider_scope = self
            .state
            .provider_scope
            .as_deref()
            .ok_or(BaoLeaseError::StateCorrupt)?;
        let expected = intent_for(provider_scope, &stored.operation)?;
        if expected != stored.intent {
            return Err(BaoLeaseError::OperationConflict);
        }
        self.append(LeaseJournalRecord::Intent {
            operation: stored.operation,
            intent: stored.intent,
        })?;
        Ok(ProviderEffectAppendDisposition::Inserted)
    }

    pub(super) fn append(&mut self, record: LeaseJournalRecord) -> Result<(), BaoLeaseError> {
        if self.failed {
            return Err(BaoLeaseError::StateUnavailable);
        }
        if self.sequence >= MAX_RECORDS {
            return Err(BaoLeaseError::StateCapacityExceeded);
        }
        let mut next_state = self.state.clone();
        apply_record(&mut next_state, &record)?;

        let sequence = self
            .sequence
            .checked_add(1)
            .ok_or(BaoLeaseError::StateCapacityExceeded)?;
        let core = FrameCore {
            schema: JOURNAL_SCHEMA,
            sequence,
            previous_sha256: self.tail_sha256,
            record: &record,
        };
        let core_bytes = serde_json::to_vec(&core).map_err(|_| BaoLeaseError::StateUnavailable)?;
        let frame_sha256 = Digest32::of_bytes(&core_bytes).into_array();
        let frame = JournalFrame {
            schema: JOURNAL_SCHEMA,
            sequence,
            previous_sha256: self.tail_sha256,
            record,
            frame_sha256,
        };
        let mut bytes = serde_json::to_vec(&frame).map_err(|_| BaoLeaseError::StateUnavailable)?;
        if bytes.len() > MAX_FRAME_BYTES {
            return Err(BaoLeaseError::StateCapacityExceeded);
        }
        bytes.push(b'\n');

        let current_len = self
            .journal
            .metadata()
            .map_err(|_| BaoLeaseError::StateUnavailable)?
            .len();
        let additional =
            u64::try_from(bytes.len()).map_err(|_| BaoLeaseError::StateCapacityExceeded)?;
        if current_len.saturating_add(additional) > MAX_JOURNAL_BYTES {
            return Err(BaoLeaseError::StateCapacityExceeded);
        }

        if self
            .journal
            .write_all(&bytes)
            .and_then(|()| self.journal.sync_all())
            .is_err()
            || self.root.sync_all().is_err()
        {
            self.failed = true;
            return Err(BaoLeaseError::StateUnavailable);
        }

        self.sequence = sequence;
        self.tail_sha256 = frame_sha256;
        self.state = next_state;
        Ok(())
    }
}

fn load_journal(journal: &mut File) -> Result<(StoreState, u64, [u8; 32], u64), BaoLeaseError> {
    journal
        .seek(SeekFrom::Start(0))
        .map_err(|_| BaoLeaseError::StateUnavailable)?;
    let mut bytes = Vec::new();
    journal
        .take(MAX_JOURNAL_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| BaoLeaseError::StateUnavailable)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_JOURNAL_BYTES
        || !bytes.starts_with(JOURNAL_MAGIC)
    {
        return Err(BaoLeaseError::StateCorrupt);
    }

    let mut complete_len =
        u64::try_from(JOURNAL_MAGIC.len()).map_err(|_| BaoLeaseError::StateCorrupt)?;
    let body = &bytes[JOURNAL_MAGIC.len()..];
    let mut state = StoreState::default();
    let mut sequence = 0_u64;
    let mut tail = [0_u8; 32];

    let mut cursor = 0_usize;
    while cursor < body.len() {
        let Some(relative_end) = body[cursor..].iter().position(|byte| *byte == b'\n') else {
            // Unterminated tail is not published. Truncate it on reopen.
            break;
        };
        let end = cursor + relative_end;
        let line = &body[cursor..end];
        if line.is_empty() || line.len() > MAX_FRAME_BYTES {
            return Err(BaoLeaseError::StateCorrupt);
        }
        let frame: JournalFrame =
            serde_json::from_slice(line).map_err(|_| BaoLeaseError::StateCorrupt)?;
        let expected_sequence = sequence.checked_add(1).ok_or(BaoLeaseError::StateCorrupt)?;
        if frame.schema != JOURNAL_SCHEMA
            || frame.sequence != expected_sequence
            || frame.previous_sha256 != tail
        {
            return Err(BaoLeaseError::StateCorrupt);
        }
        let core = FrameCore {
            schema: frame.schema,
            sequence: frame.sequence,
            previous_sha256: frame.previous_sha256,
            record: &frame.record,
        };
        let core_bytes = serde_json::to_vec(&core).map_err(|_| BaoLeaseError::StateCorrupt)?;
        let expected_sha256 = Digest32::of_bytes(&core_bytes).into_array();
        if expected_sha256 != frame.frame_sha256 {
            return Err(BaoLeaseError::StateCorrupt);
        }
        apply_record(&mut state, &frame.record).map_err(|_| BaoLeaseError::StateCorrupt)?;
        sequence = frame.sequence;
        tail = frame.frame_sha256;
        cursor = end + 1;
        complete_len = complete_len
            .checked_add(u64::try_from(line.len() + 1).map_err(|_| BaoLeaseError::StateCorrupt)?)
            .ok_or(BaoLeaseError::StateCorrupt)?;
        if sequence > MAX_RECORDS {
            return Err(BaoLeaseError::StateCapacityExceeded);
        }
    }

    if state.provider_scope.is_none() && sequence != 0 {
        return Err(BaoLeaseError::StateCorrupt);
    }
    Ok((state, sequence, tail, complete_len))
}

enum Access {
    Create,
    Append,
}

// The store is deliberately Linux-only for now. This avoids adding a new
// first-party dependency edge (and therefore an out-of-scope Cargo.lock
// mutation) while preserving O_NOFOLLOW/O_DIRECTORY semantics. Other
// platforms fail closed until an equivalent owner/ACL implementation exists.
#[cfg(target_os = "linux")]
fn prepare_directory(root: &Path) -> Result<File, BaoLeaseError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    const O_DIRECTORY: i32 = 0o200000;
    const O_NOFOLLOW: i32 = 0o400000;
    const O_CLOEXEC: i32 = 0o2000000;

    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(root)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(BaoLeaseError::StateUnavailable);
    }
    let directory = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        .open(root)
        .map_err(|_| BaoLeaseError::UnsafeStateDirectory)?;
    let metadata = directory
        .metadata()
        .map_err(|_| BaoLeaseError::StateUnavailable)?;
    let effective_uid = std::fs::metadata("/proc/self")
        .map_err(|_| BaoLeaseError::UnsafeStateDirectory)?
        .uid();
    if !metadata.is_dir() || metadata.mode() & 0o077 != 0 || metadata.uid() != effective_uid {
        return Err(BaoLeaseError::UnsafeStateDirectory);
    }
    Ok(directory)
}

#[cfg(not(target_os = "linux"))]
fn prepare_directory(_root: &Path) -> Result<File, BaoLeaseError> {
    Err(BaoLeaseError::UnsafeStateDirectory)
}

#[cfg(target_os = "linux")]
fn open_private(directory: &File, name: &str, access: Access) -> Result<File, BaoLeaseError> {
    use std::os::fd::AsRawFd;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    const O_NOFOLLOW: i32 = 0o400000;
    const O_CLOEXEC: i32 = 0o2000000;

    let path = format!("/proc/self/fd/{}/{}", directory.as_raw_fd(), name);
    let mut options = std::fs::OpenOptions::new();
    options
        .read(true)
        .create(true)
        .mode(0o600)
        .custom_flags(O_NOFOLLOW | O_CLOEXEC);
    match access {
        Access::Create => {
            options.write(true);
        }
        Access::Append => {
            options.append(true);
        }
    }
    let file = options
        .open(path)
        .map_err(|_| BaoLeaseError::StateUnavailable)?;
    let metadata = file
        .metadata()
        .map_err(|_| BaoLeaseError::StateUnavailable)?;
    let effective_uid = std::fs::metadata("/proc/self")
        .map_err(|_| BaoLeaseError::UnsafeStateDirectory)?
        .uid();
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != effective_uid
    {
        return Err(BaoLeaseError::UnsafeStateDirectory);
    }
    Ok(file)
}

#[cfg(not(target_os = "linux"))]
fn open_private(_directory: &File, _name: &str, _access: Access) -> Result<File, BaoLeaseError> {
    Err(BaoLeaseError::UnsafeStateDirectory)
}

#[cfg(target_os = "linux")]
fn entry_exists(directory: &File, name: &str) -> Result<bool, BaoLeaseError> {
    use std::os::fd::AsRawFd;

    let path = format!("/proc/self/fd/{}/{}", directory.as_raw_fd(), name);
    match std::fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(_) => Err(BaoLeaseError::StateUnavailable),
    }
}

#[cfg(not(target_os = "linux"))]
fn entry_exists(_directory: &File, _name: &str) -> Result<bool, BaoLeaseError> {
    Err(BaoLeaseError::UnsafeStateDirectory)
}
