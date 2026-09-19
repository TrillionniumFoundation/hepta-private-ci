use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use codex_hepta_types::Digest32;

use crate::PlannerJournalError;
use crate::PlannerJournalV1;

const STORE_V1_MAGIC: &[u8; 8] = b"HCPSTR01";
const STORE_V2_MAGIC: &[u8; 8] = b"HCPSTR02";
const LOCK_FILE: &str = "planner.lock";
const STATE_FILE: &str = "planner.state";
const NEXT_FILE: &str = "planner.next";
const MAX_STORE_BYTES: usize = 2 * 1024 * 1024;
const MAX_REVOKED_DIGESTS: usize = 4096;
const DIGEST_BYTES: usize = 32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerStoreError {
    Unavailable,
    UnsafeStateDirectory,
    StateLocked,
    MissingState,
    CorruptState,
    UnsupportedSchema,
    RevocationRegression,
    HistoryRegression,
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
/// The qualified backend is a local Unix filesystem with an owner-only
/// directory, no-follow opens, a single-process lock, same-directory atomic
/// replacement, and file plus directory fsync. A caller must supply the
/// currently authoritative revoked-decision floor when opening restored state.
#[derive(Debug)]
pub struct PlannerJournalStoreV1 {
    root: File,
    _lock: File,
    current: PlannerJournalV1,
    recovery_floor: BTreeSet<Digest32>,
}

impl PlannerJournalStoreV1 {
    pub fn open(
        root: &Path,
        recovery_floor: &[Digest32],
    ) -> Result<(Self, PlannerJournalV1), PlannerStoreError> {
        if recovery_floor.len() > MAX_REVOKED_DIGESTS {
            return Err(PlannerStoreError::RevocationRegression);
        }
        let recovery_floor_count = recovery_floor.len();
        let recovery_floor: BTreeSet<_> = recovery_floor.iter().copied().collect();
        if recovery_floor.len() != recovery_floor_count {
            return Err(PlannerStoreError::RevocationRegression);
        }

        let directory = prepare_directory(root)?;
        let initialized = entry_exists(&directory, LOCK_FILE)?;
        let lock = open_private(&directory, LOCK_FILE, Access::Create)?;
        lock.try_lock()
            .map_err(|_| PlannerStoreError::StateLocked)?;

        let has_state = entry_exists(&directory, STATE_FILE)?;
        let (journal, migrated) = if has_state {
            let bytes = read_state(&directory)?;
            decode_store(&bytes)?
        } else {
            if initialized {
                return Err(PlannerStoreError::MissingState);
            }
            (PlannerJournalV1::new(), false)
        };

        validate_recovery_floor(&journal, &recovery_floor)?;

        let mut store = Self {
            root: directory,
            _lock: lock,
            current: journal.clone(),
            recovery_floor,
        };
        if !has_state || migrated {
            store.persist(&journal)?;
        }
        Ok((store, journal))
    }

    pub fn persist(&mut self, journal: &PlannerJournalV1) -> Result<(), PlannerStoreError> {
        validate_recovery_floor(journal, &self.recovery_floor)?;
        if !journal.entries().starts_with(self.current.entries()) {
            return Err(PlannerStoreError::HistoryRegression);
        }
        let bytes = encode_store_v2(journal)?;
        write_state(&self.root, &bytes)?;
        self.current = journal.clone();
        Ok(())
    }

    #[must_use]
    pub fn current(&self) -> &PlannerJournalV1 {
        &self.current
    }
}

fn validate_recovery_floor(
    journal: &PlannerJournalV1,
    recovery_floor: &BTreeSet<Digest32>,
) -> Result<(), PlannerStoreError> {
    let revoked: BTreeSet<_> = journal.revoked_decision_digests().into_iter().collect();
    if !revoked.is_superset(recovery_floor) {
        return Err(PlannerStoreError::RevocationRegression);
    }
    Ok(())
}

fn read_state(directory: &File) -> Result<Vec<u8>, PlannerStoreError> {
    let mut bytes = Vec::new();
    open_private(directory, STATE_FILE, Access::Read)?
        .take((MAX_STORE_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| PlannerStoreError::Unavailable)?;
    if bytes.len() > MAX_STORE_BYTES {
        return Err(PlannerStoreError::CorruptState);
    }
    Ok(bytes)
}

fn write_state(directory: &File, bytes: &[u8]) -> Result<(), PlannerStoreError> {
    if bytes.len() > MAX_STORE_BYTES {
        return Err(PlannerStoreError::CorruptState);
    }
    let mut file = open_private(directory, NEXT_FILE, Access::Create)?;
    file.set_len(0)
        .map_err(|_| PlannerStoreError::Unavailable)?;
    file.write_all(bytes)
        .and_then(|()| file.sync_all())
        .map_err(|_| PlannerStoreError::Unavailable)?;
    replace_state(directory)?;
    directory
        .sync_all()
        .map_err(|_| PlannerStoreError::Unavailable)
}

fn encode_store_v2(journal: &PlannerJournalV1) -> Result<Vec<u8>, PlannerStoreError> {
    let journal_bytes = journal.export_bytes();
    let revoked = journal.revoked_decision_digests();
    if revoked.len() > MAX_REVOKED_DIGESTS {
        return Err(PlannerStoreError::CorruptState);
    }
    let mut bytes = Vec::new();
    bytes.extend_from_slice(STORE_V2_MAGIC);
    push_u32(&mut bytes, journal_bytes.len())?;
    push_u32(&mut bytes, revoked.len())?;
    bytes.extend_from_slice(&journal_bytes);
    for digest in &revoked {
        bytes.extend_from_slice(digest.as_array());
    }
    let digest = digest_store_v2(&journal_bytes, &revoked);
    bytes.extend_from_slice(digest.as_array());
    Ok(bytes)
}

fn decode_store(bytes: &[u8]) -> Result<(PlannerJournalV1, bool), PlannerStoreError> {
    if bytes.len() < 8 + 4 + DIGEST_BYTES {
        return Err(PlannerStoreError::CorruptState);
    }
    if &bytes[..8] == STORE_V1_MAGIC {
        return decode_store_v1(bytes).map(|journal| (journal, true));
    }
    if &bytes[..8] != STORE_V2_MAGIC {
        return Err(PlannerStoreError::UnsupportedSchema);
    }
    let mut offset = 8;
    let journal_len = read_u32(bytes, &mut offset)?;
    let revoked_len = read_u32(bytes, &mut offset)?;
    if revoked_len > MAX_REVOKED_DIGESTS {
        return Err(PlannerStoreError::CorruptState);
    }
    let revoked_bytes = revoked_len
        .checked_mul(DIGEST_BYTES)
        .ok_or(PlannerStoreError::CorruptState)?;
    let expected_len = offset
        .checked_add(journal_len)
        .and_then(|value| value.checked_add(revoked_bytes))
        .and_then(|value| value.checked_add(DIGEST_BYTES))
        .ok_or(PlannerStoreError::CorruptState)?;
    if expected_len != bytes.len() {
        return Err(PlannerStoreError::CorruptState);
    }
    let journal_end = offset + journal_len;
    let journal_bytes = &bytes[offset..journal_end];
    offset = journal_end;

    let mut revoked = Vec::with_capacity(revoked_len);
    for _ in 0..revoked_len {
        revoked.push(read_digest(bytes, &mut offset)?);
    }
    let stored_digest = read_digest(bytes, &mut offset)?;
    if stored_digest != digest_store_v2(journal_bytes, &revoked) {
        return Err(PlannerStoreError::CorruptState);
    }

    let journal = PlannerJournalV1::reopen(journal_bytes)?;
    if journal.revoked_decision_digests() != revoked {
        return Err(PlannerStoreError::CorruptState);
    }
    Ok((journal, false))
}

fn decode_store_v1(bytes: &[u8]) -> Result<PlannerJournalV1, PlannerStoreError> {
    let mut offset = 8;
    let journal_len = read_u32(bytes, &mut offset)?;
    let expected_len = offset
        .checked_add(journal_len)
        .and_then(|value| value.checked_add(DIGEST_BYTES))
        .ok_or(PlannerStoreError::CorruptState)?;
    if expected_len != bytes.len() {
        return Err(PlannerStoreError::CorruptState);
    }
    let journal_end = offset + journal_len;
    let journal_bytes = &bytes[offset..journal_end];
    offset = journal_end;
    let stored_digest = read_digest(bytes, &mut offset)?;
    if stored_digest != digest_store_v1(journal_bytes) {
        return Err(PlannerStoreError::CorruptState);
    }
    PlannerJournalV1::reopen(journal_bytes).map_err(Into::into)
}

fn digest_store_v1(journal_bytes: &[u8]) -> Digest32 {
    let mut bytes = b"hepta.control.planner-store.v1\0".to_vec();
    bytes.extend_from_slice(journal_bytes);
    Digest32::of_bytes(&bytes)
}

fn digest_store_v2(journal_bytes: &[u8], revoked: &[Digest32]) -> Digest32 {
    let mut bytes = b"hepta.control.planner-store.v2\0".to_vec();
    bytes.extend_from_slice(journal_bytes);
    bytes.extend_from_slice(&(revoked.len() as u32).to_be_bytes());
    for digest in revoked {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn push_u32(bytes: &mut Vec<u8>, value: usize) -> Result<(), PlannerStoreError> {
    let value = u32::try_from(value).map_err(|_| PlannerStoreError::CorruptState)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

fn read_u32(bytes: &[u8], offset: &mut usize) -> Result<usize, PlannerStoreError> {
    let end = (*offset)
        .checked_add(4)
        .ok_or(PlannerStoreError::CorruptState)?;
    let value = u32::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(PlannerStoreError::CorruptState)?
            .try_into()
            .map_err(|_| PlannerStoreError::CorruptState)?,
    );
    *offset = end;
    usize::try_from(value).map_err(|_| PlannerStoreError::CorruptState)
}

fn read_digest(bytes: &[u8], offset: &mut usize) -> Result<Digest32, PlannerStoreError> {
    let end = (*offset)
        .checked_add(DIGEST_BYTES)
        .ok_or(PlannerStoreError::CorruptState)?;
    let value: [u8; DIGEST_BYTES] = bytes
        .get(*offset..end)
        .ok_or(PlannerStoreError::CorruptState)?
        .try_into()
        .map_err(|_| PlannerStoreError::CorruptState)?;
    *offset = end;
    Ok(Digest32::from_array(value))
}

enum Access {
    Read,
    Create,
}

#[cfg(unix)]
fn prepare_directory(root: &Path) -> Result<File, PlannerStoreError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;

    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(root)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(PlannerStoreError::Unavailable);
    }
    let directory: File = rustix::fs::open(
        root,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| PlannerStoreError::UnsafeStateDirectory)?
    .into();
    let metadata = directory
        .metadata()
        .map_err(|_| PlannerStoreError::Unavailable)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(PlannerStoreError::UnsafeStateDirectory);
    }
    Ok(directory)
}

#[cfg(unix)]
fn open_private(directory: &File, name: &str, access: Access) -> Result<File, PlannerStoreError> {
    use rustix::fs::Mode;
    use rustix::fs::OFlags;
    use std::os::unix::fs::MetadataExt;

    let flags = match access {
        Access::Read => OFlags::RDONLY,
        Access::Create => OFlags::RDWR | OFlags::CREATE,
    } | OFlags::NOFOLLOW
        | OFlags::CLOEXEC;
    let file: File = rustix::fs::openat(directory, name, flags, Mode::RUSR | Mode::WUSR)
        .map_err(|_| PlannerStoreError::Unavailable)?
        .into();
    let metadata = file
        .metadata()
        .map_err(|_| PlannerStoreError::Unavailable)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(PlannerStoreError::UnsafeStateDirectory);
    }
    Ok(file)
}

#[cfg(unix)]
fn entry_exists(directory: &File, name: &str) -> Result<bool, PlannerStoreError> {
    match rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(PlannerStoreError::Unavailable),
    }
}

#[cfg(unix)]
fn replace_state(directory: &File) -> Result<(), PlannerStoreError> {
    rustix::fs::renameat(directory, NEXT_FILE, directory, STATE_FILE)
        .map_err(|_| PlannerStoreError::Unavailable)
}

#[cfg(not(unix))]
fn prepare_directory(_root: &Path) -> Result<File, PlannerStoreError> {
    Err(PlannerStoreError::UnsafeStateDirectory)
}

#[cfg(not(unix))]
fn open_private(
    _directory: &File,
    _name: &str,
    _access: Access,
) -> Result<File, PlannerStoreError> {
    Err(PlannerStoreError::UnsafeStateDirectory)
}

#[cfg(not(unix))]
fn entry_exists(_directory: &File, _name: &str) -> Result<bool, PlannerStoreError> {
    Err(PlannerStoreError::UnsafeStateDirectory)
}

#[cfg(not(unix))]
fn replace_state(_directory: &File) -> Result<(), PlannerStoreError> {
    Err(PlannerStoreError::UnsafeStateDirectory)
}

#[cfg(test)]
pub(super) fn encode_store_v1_for_test(
    journal: &PlannerJournalV1,
) -> Result<Vec<u8>, PlannerStoreError> {
    let journal_bytes = journal.export_bytes();
    let mut bytes = Vec::new();
    bytes.extend_from_slice(STORE_V1_MAGIC);
    push_u32(&mut bytes, journal_bytes.len())?;
    bytes.extend_from_slice(&journal_bytes);
    bytes.extend_from_slice(digest_store_v1(&journal_bytes).as_array());
    Ok(bytes)
}

#[cfg(test)]
#[path = "planner_store_tests.rs"]
mod tests;
