//! Durable owner-local store for the planner decision journal.
//!
//! The Unix profile uses a private directory, process lock, no-follow opens,
//! file fsync, atomic rename and directory fsync. Only semantically valid strict
//! journals may be committed. One predecessor is retained for explicit restore.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use codex_hepta_types::Digest32;

use crate::PlannerJournalV1;
use crate::StrictPlannerJournalError;
use crate::StrictPlannerJournalV1;

const STORE_MAGIC: &[u8; 8] = b"HCPSTR01";
const STORE_SCHEMA: u32 = 1;
const MAX_STORE_BYTES: usize = 2 * 1024 * 1024;
const CURRENT: &str = "planner-journal.v1";
const CURRENT_NEXT: &str = "planner-journal.next";
const PREVIOUS: &str = "planner-journal.previous.v1";
const PREVIOUS_NEXT: &str = "planner-journal.previous.next";
const LEGACY_RAW: &str = "planner-journal.raw.v1";
const LOCK: &str = "planner-journal.lock";

pub struct PlannerJournalStoreV1 {
    root: File,
    _lock: File,
}

impl fmt::Debug for PlannerJournalStoreV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("PlannerJournalStoreV1([PRIVATE DURABLE STORE])")
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerJournalStoreError {
    UnsupportedPlatform,
    UnsafeStateDirectory,
    StateLocked,
    Unavailable,
    CorruptStore,
    Semantic(StrictPlannerJournalError),
    NoPreviousGeneration,
}

impl fmt::Display for PlannerJournalStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlannerJournalStoreError {}

impl From<StrictPlannerJournalError> for PlannerJournalStoreError {
    fn from(error: StrictPlannerJournalError) -> Self {
        Self::Semantic(error)
    }
}

impl PlannerJournalStoreV1 {
    pub fn open(root: &Path) -> Result<Self, PlannerJournalStoreError> {
        let root = prepare_directory(root)?;
        let lock = open_private(&root, LOCK, Access::Create)?;
        lock.try_lock()
            .map_err(|_| PlannerJournalStoreError::StateLocked)?;
        Ok(Self { root, _lock: lock })
    }

    /// Load the current generation. If only the legacy raw V1 journal exists,
    /// validate it with strict semantic replay and migrate it atomically.
    pub fn load(&self) -> Result<Option<StrictPlannerJournalV1>, PlannerJournalStoreError> {
        if entry_exists(&self.root, CURRENT)? {
            return read_stored(&self.root, CURRENT).map(Some);
        }
        if entry_exists(&self.root, LEGACY_RAW)? {
            let bytes = read_bounded(&self.root, LEGACY_RAW)?;
            let strict = StrictPlannerJournalV1::reopen(&bytes)?;
            self.persist_generation(CURRENT_NEXT, CURRENT, &encode_store(&strict)?)?;
            return Ok(Some(strict));
        }
        Ok(None)
    }

    /// Commit one semantically valid generation and retain exactly one verified
    /// predecessor. Invalid hash-valid histories are rejected before disk I/O.
    pub fn commit(
        &self,
        journal: &PlannerJournalV1,
    ) -> Result<StrictPlannerJournalV1, PlannerJournalStoreError> {
        let strict = StrictPlannerJournalV1::reopen(&journal.export_bytes())?;
        self.commit_strict(&strict)?;
        Ok(strict)
    }

    pub fn commit_strict(
        &self,
        journal: &StrictPlannerJournalV1,
    ) -> Result<(), PlannerJournalStoreError> {
        if entry_exists(&self.root, CURRENT)? {
            let current_bytes = read_bounded(&self.root, CURRENT)?;
            decode_store(&current_bytes)?;
            self.persist_generation(PREVIOUS_NEXT, PREVIOUS, &current_bytes)?;
        }
        self.persist_generation(CURRENT_NEXT, CURRENT, &encode_store(journal)?)
    }

    /// Explicit rollback only. A missing/corrupt predecessor never becomes an
    /// implicit empty journal or a silent reset.
    pub fn restore_previous(
        &self,
    ) -> Result<StrictPlannerJournalV1, PlannerJournalStoreError> {
        if !entry_exists(&self.root, PREVIOUS)? {
            return Err(PlannerJournalStoreError::NoPreviousGeneration);
        }
        let bytes = read_bounded(&self.root, PREVIOUS)?;
        let strict = decode_store(&bytes)?;
        self.persist_generation(CURRENT_NEXT, CURRENT, &bytes)?;
        Ok(strict)
    }

    fn persist_generation(
        &self,
        temporary: &str,
        target: &str,
        bytes: &[u8],
    ) -> Result<(), PlannerJournalStoreError> {
        if bytes.len() > MAX_STORE_BYTES {
            return Err(PlannerJournalStoreError::CorruptStore);
        }
        let mut file = open_private(&self.root, temporary, Access::Create)?;
        file.set_len(0)
            .map_err(|_| PlannerJournalStoreError::Unavailable)?;
        file.write_all(bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| PlannerJournalStoreError::Unavailable)?;
        replace_entry(&self.root, temporary, target)?;
        self.root
            .sync_all()
            .map_err(|_| PlannerJournalStoreError::Unavailable)
    }
}

fn encode_store(
    journal: &StrictPlannerJournalV1,
) -> Result<Vec<u8>, PlannerJournalStoreError> {
    let payload = journal.export_bytes();
    let payload_len =
        u32::try_from(payload.len()).map_err(|_| PlannerJournalStoreError::CorruptStore)?;
    let mut bytes = Vec::with_capacity(16 + payload.len() + 32);
    bytes.extend_from_slice(STORE_MAGIC);
    bytes.extend_from_slice(&STORE_SCHEMA.to_be_bytes());
    bytes.extend_from_slice(&payload_len.to_be_bytes());
    bytes.extend_from_slice(&payload);
    let checksum = store_checksum(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    if bytes.len() > MAX_STORE_BYTES {
        return Err(PlannerJournalStoreError::CorruptStore);
    }
    Ok(bytes)
}

fn decode_store(bytes: &[u8]) -> Result<StrictPlannerJournalV1, PlannerJournalStoreError> {
    if bytes.len() < 48 || &bytes[..8] != STORE_MAGIC {
        return Err(PlannerJournalStoreError::CorruptStore);
    }
    let schema = u32::from_be_bytes(
        bytes[8..12]
            .try_into()
            .map_err(|_| PlannerJournalStoreError::CorruptStore)?,
    );
    if schema != STORE_SCHEMA {
        return Err(PlannerJournalStoreError::CorruptStore);
    }
    let payload_len = usize::try_from(u32::from_be_bytes(
        bytes[12..16]
            .try_into()
            .map_err(|_| PlannerJournalStoreError::CorruptStore)?,
    ))
    .map_err(|_| PlannerJournalStoreError::CorruptStore)?;
    let payload_end = 16_usize
        .checked_add(payload_len)
        .ok_or(PlannerJournalStoreError::CorruptStore)?;
    let expected = payload_end
        .checked_add(32)
        .ok_or(PlannerJournalStoreError::CorruptStore)?;
    if expected != bytes.len() || expected > MAX_STORE_BYTES {
        return Err(PlannerJournalStoreError::CorruptStore);
    }
    let checksum = Digest32::from_array(
        bytes[payload_end..]
            .try_into()
            .map_err(|_| PlannerJournalStoreError::CorruptStore)?,
    );
    if checksum != store_checksum(&bytes[..payload_end]) {
        return Err(PlannerJournalStoreError::CorruptStore);
    }
    StrictPlannerJournalV1::reopen(&bytes[16..payload_end]).map_err(Into::into)
}

fn store_checksum(bytes: &[u8]) -> Digest32 {
    let mut input = b"hepta.control.planner-journal-store.v1\0".to_vec();
    input.extend_from_slice(bytes);
    Digest32::of_bytes(&input)
}

fn read_stored(
    directory: &File,
    name: &str,
) -> Result<StrictPlannerJournalV1, PlannerJournalStoreError> {
    decode_store(&read_bounded(directory, name)?)
}

fn read_bounded(directory: &File, name: &str) -> Result<Vec<u8>, PlannerJournalStoreError> {
    let mut bytes = Vec::new();
    open_private(directory, name, Access::Read)?
        .take((MAX_STORE_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| PlannerJournalStoreError::Unavailable)?;
    if bytes.len() > MAX_STORE_BYTES {
        return Err(PlannerJournalStoreError::CorruptStore);
    }
    Ok(bytes)
}

enum Access {
    Read,
    Create,
}

#[cfg(unix)]
fn prepare_directory(root: &Path) -> Result<File, PlannerJournalStoreError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;

    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(root)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(PlannerJournalStoreError::Unavailable);
    }
    let directory: File = rustix::fs::open(
        root,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| PlannerJournalStoreError::UnsafeStateDirectory)?
    .into();
    let metadata = directory
        .metadata()
        .map_err(|_| PlannerJournalStoreError::Unavailable)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(PlannerJournalStoreError::UnsafeStateDirectory);
    }
    Ok(directory)
}

#[cfg(not(unix))]
fn prepare_directory(_root: &Path) -> Result<File, PlannerJournalStoreError> {
    Err(PlannerJournalStoreError::UnsupportedPlatform)
}

#[cfg(unix)]
fn open_private(
    directory: &File,
    name: &str,
    access: Access,
) -> Result<File, PlannerJournalStoreError> {
    use std::os::unix::fs::MetadataExt;

    let flags = match access {
        Access::Read => rustix::fs::OFlags::RDONLY,
        Access::Create => rustix::fs::OFlags::RDWR | rustix::fs::OFlags::CREATE,
    } | rustix::fs::OFlags::NOFOLLOW
        | rustix::fs::OFlags::CLOEXEC;
    let file: File = rustix::fs::openat(
        directory,
        name,
        flags,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )
    .map_err(|_| PlannerJournalStoreError::Unavailable)?
    .into();
    let metadata = file
        .metadata()
        .map_err(|_| PlannerJournalStoreError::Unavailable)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(PlannerJournalStoreError::UnsafeStateDirectory);
    }
    Ok(file)
}

#[cfg(not(unix))]
fn open_private(
    _directory: &File,
    _name: &str,
    _access: Access,
) -> Result<File, PlannerJournalStoreError> {
    Err(PlannerJournalStoreError::UnsupportedPlatform)
}

#[cfg(unix)]
fn entry_exists(directory: &File, name: &str) -> Result<bool, PlannerJournalStoreError> {
    match rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(PlannerJournalStoreError::Unavailable),
    }
}

#[cfg(not(unix))]
fn entry_exists(_directory: &File, _name: &str) -> Result<bool, PlannerJournalStoreError> {
    Err(PlannerJournalStoreError::UnsupportedPlatform)
}

#[cfg(unix)]
fn replace_entry(
    directory: &File,
    source: &str,
    destination: &str,
) -> Result<(), PlannerJournalStoreError> {
    rustix::fs::renameat(directory, source, directory, destination)
        .map_err(|_| PlannerJournalStoreError::Unavailable)
}

#[cfg(not(unix))]
fn replace_entry(
    _directory: &File,
    _source: &str,
    _destination: &str,
) -> Result<(), PlannerJournalStoreError> {
    Err(PlannerJournalStoreError::UnsupportedPlatform)
}

#[cfg(all(test, unix))]
mod tests {
    use std::fs::OpenOptions;
    use std::os::unix::fs::OpenOptionsExt;

    use codex_hepta_types::Digest32;

    use super::*;
    use crate::PlannerJournalKindV1;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn journal(decision: &str) -> PlannerJournalV1 {
        let mut journal = PlannerJournalV1::new();
        let decision = digest(decision);
        journal
            .append(PlannerJournalKindV1::Decision, decision, decision)
            .expect("decision");
        journal
            .append(
                PlannerJournalKindV1::SelectedPlan,
                digest("selection"),
                decision,
            )
            .expect("selection");
        journal
    }

    #[test]
    fn durable_commit_reopens_and_process_lock_excludes_second_owner() {
        let directory = tempfile::tempdir().expect("tempdir");
        let store = PlannerJournalStoreV1::open(directory.path()).expect("store");
        assert_eq!(
            PlannerJournalStoreV1::open(directory.path())
                .expect_err("second owner must not acquire lock"),
            PlannerJournalStoreError::StateLocked
        );
        let committed = store.commit(&journal("decision-a")).expect("commit");
        assert_eq!(
            committed.selected_plan_digest(),
            Some(digest("decision-a"))
        );
        drop(store);

        let reopened = PlannerJournalStoreV1::open(directory.path()).expect("reopen");
        assert_eq!(
            reopened
                .load()
                .expect("load")
                .expect("current")
                .selected_plan_digest(),
            Some(digest("decision-a"))
        );
    }

    #[test]
    fn predecessor_restore_is_explicit_and_semantically_verified() {
        let directory = tempfile::tempdir().expect("tempdir");
        let store = PlannerJournalStoreV1::open(directory.path()).expect("store");
        store.commit(&journal("decision-a")).expect("first");
        store.commit(&journal("decision-b")).expect("second");
        assert_eq!(
            store
                .load()
                .expect("load")
                .expect("current")
                .selected_plan_digest(),
            Some(digest("decision-b"))
        );
        assert_eq!(
            store
                .restore_previous()
                .expect("restore")
                .selected_plan_digest(),
            Some(digest("decision-a"))
        );
    }

    #[test]
    fn hash_valid_semantic_forgery_never_reaches_disk() {
        let directory = tempfile::tempdir().expect("tempdir");
        let store = PlannerJournalStoreV1::open(directory.path()).expect("store");
        let mut invalid = PlannerJournalV1::new();
        invalid
            .append(
                PlannerJournalKindV1::SelectedPlan,
                digest("selection"),
                digest("missing-decision"),
            )
            .expect("raw append");
        assert_eq!(
            store.commit(&invalid),
            Err(PlannerJournalStoreError::Semantic(
                StrictPlannerJournalError::SelectionBeforeDecision
            ))
        );
        assert!(store.load().expect("load").is_none());
    }

    #[test]
    fn legacy_raw_journal_migrates_once_through_strict_replay() {
        let directory = tempfile::tempdir().expect("tempdir");
        let raw = journal("legacy-decision").export_bytes();
        let path = directory.path().join(LEGACY_RAW);
        let mut legacy = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(path)
            .expect("legacy");
        legacy.write_all(&raw).expect("write legacy");
        legacy.sync_all().expect("sync legacy");
        drop(legacy);

        let store = PlannerJournalStoreV1::open(directory.path()).expect("store");
        let loaded = store.load().expect("migrate").expect("current");
        assert_eq!(
            loaded.selected_plan_digest(),
            Some(digest("legacy-decision"))
        );
        assert!(entry_exists(&store.root, CURRENT).expect("current exists"));
    }
}
