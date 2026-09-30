use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

use crate::FeasiblePlanReceiptV1;
use crate::GlobalStateSnapshotV1;
use crate::PlannerJournalEntryV1;
use crate::PlannerJournalError;
use crate::PlannerJournalHeadV1;
use crate::PlannerJournalV1;

const ANCHOR_MAGIC: &[u8; 8] = b"HCPANC01";
const ANCHOR_BYTES: usize = 8 + 8 + 32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerJournalStoreError {
    Io {
        operation: &'static str,
        kind: ErrorKind,
    },
    Busy,
    Journal(PlannerJournalError),
    Conflict {
        expected: PlannerJournalHeadV1,
        actual: PlannerJournalHeadV1,
    },
    AnchorRegression {
        current: PlannerJournalHeadV1,
        proposed: PlannerJournalHeadV1,
    },
    RollbackDetected {
        anchor: PlannerJournalHeadV1,
        journal: PlannerJournalHeadV1,
    },
    ForkDetected {
        anchor: PlannerJournalHeadV1,
        journal: PlannerJournalHeadV1,
    },
    CorruptAnchor,
}

impl std::fmt::Display for PlannerJournalStoreError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for PlannerJournalStoreError {}

impl From<PlannerJournalError> for PlannerJournalStoreError {
    fn from(error: PlannerJournalError) -> Self {
        Self::Journal(error)
    }
}

pub trait PlannerJournalStoreV1 {
    fn load(&mut self) -> Result<Option<Vec<u8>>, PlannerJournalStoreError>;

    fn compare_and_commit(
        &mut self,
        expected: PlannerJournalHeadV1,
        journal: &PlannerJournalV1,
    ) -> Result<PlannerJournalHeadV1, PlannerJournalStoreError>;
}

/// The anchor must be provisioned independently from the journal store when
/// rollback by a privileged local actor is in scope. A second file on the same
/// volume provides crash recovery and accidental-rollback detection, but not
/// independence from an actor capable of replacing both files.
pub trait PlannerJournalAnchorV1 {
    fn load_head(&mut self) -> Result<PlannerJournalHeadV1, PlannerJournalStoreError>;

    fn compare_and_advance(
        &mut self,
        expected: PlannerJournalHeadV1,
        next: PlannerJournalHeadV1,
    ) -> Result<(), PlannerJournalStoreError>;
}

#[derive(Clone, Debug, Default)]
pub struct InMemoryPlannerJournalStoreV1 {
    bytes: Option<Vec<u8>>,
}

impl InMemoryPlannerJournalStoreV1 {
    #[must_use]
    pub fn from_bytes(bytes: Vec<u8>) -> Self {
        Self { bytes: Some(bytes) }
    }

    #[must_use]
    pub fn bytes(&self) -> Option<&[u8]> {
        self.bytes.as_deref()
    }
}

impl PlannerJournalStoreV1 for InMemoryPlannerJournalStoreV1 {
    fn load(&mut self) -> Result<Option<Vec<u8>>, PlannerJournalStoreError> {
        Ok(self.bytes.clone())
    }

    fn compare_and_commit(
        &mut self,
        expected: PlannerJournalHeadV1,
        journal: &PlannerJournalV1,
    ) -> Result<PlannerJournalHeadV1, PlannerJournalStoreError> {
        let actual = journal_head_from_bytes(self.bytes.as_deref())?;
        if actual != expected {
            return Err(PlannerJournalStoreError::Conflict { expected, actual });
        }
        self.bytes = Some(journal.export_bytes());
        Ok(journal.head())
    }
}

#[derive(Clone, Debug, Default)]
pub struct InMemoryPlannerJournalAnchorV1 {
    head: PlannerJournalHeadV1,
}

impl InMemoryPlannerJournalAnchorV1 {
    #[must_use]
    pub const fn from_head(head: PlannerJournalHeadV1) -> Self {
        Self { head }
    }
}

impl PlannerJournalAnchorV1 for InMemoryPlannerJournalAnchorV1 {
    fn load_head(&mut self) -> Result<PlannerJournalHeadV1, PlannerJournalStoreError> {
        Ok(self.head)
    }

    fn compare_and_advance(
        &mut self,
        expected: PlannerJournalHeadV1,
        next: PlannerJournalHeadV1,
    ) -> Result<(), PlannerJournalStoreError> {
        if self.head != expected {
            return Err(PlannerJournalStoreError::Conflict {
                expected,
                actual: self.head,
            });
        }
        validate_anchor_advance(self.head, next)?;
        self.head = next;
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct FilePlannerJournalStoreV1 {
    path: PathBuf,
    backup_path: PathBuf,
    lock_path: PathBuf,
}

impl FilePlannerJournalStoreV1 {
    #[must_use]
    pub fn new(path: impl Into<PathBuf>) -> Self {
        let path = path.into();
        Self {
            backup_path: path.with_extension("bak"),
            lock_path: path.with_extension("lock"),
            path,
        }
    }

    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    #[must_use]
    pub fn backup_path(&self) -> &Path {
        &self.backup_path
    }

    pub fn load_backup(&self) -> Result<Option<Vec<u8>>, PlannerJournalStoreError> {
        read_optional(&self.backup_path, "read journal backup")
    }
}

impl PlannerJournalStoreV1 for FilePlannerJournalStoreV1 {
    fn load(&mut self) -> Result<Option<Vec<u8>>, PlannerJournalStoreError> {
        read_optional(&self.path, "read journal")
    }

    fn compare_and_commit(
        &mut self,
        expected: PlannerJournalHeadV1,
        journal: &PlannerJournalV1,
    ) -> Result<PlannerJournalHeadV1, PlannerJournalStoreError> {
        ensure_parent(&self.path)?;
        let _guard = FileLockGuard::acquire(&self.lock_path)?;
        let actual_bytes = read_optional(&self.path, "read journal before commit")?;
        let actual = journal_head_from_bytes(actual_bytes.as_deref())?;
        if actual != expected {
            return Err(PlannerJournalStoreError::Conflict { expected, actual });
        }
        if let Some(bytes) = actual_bytes {
            atomic_replace(
                &self.backup_path,
                &self.backup_path.with_extension("bak.tmp"),
                &bytes,
                "write journal backup",
            )?;
        }
        let bytes = journal.export_bytes();
        atomic_replace(
            &self.path,
            &self.path.with_extension("tmp"),
            &bytes,
            "write journal",
        )?;
        let verified = read_optional(&self.path, "verify journal commit")?
            .ok_or(PlannerJournalStoreError::Io {
                operation: "verify journal commit",
                kind: ErrorKind::NotFound,
            })?;
        let reopened = PlannerJournalV1::reopen(&verified)?;
        if reopened.head() != journal.head() {
            return Err(PlannerJournalStoreError::ForkDetected {
                anchor: journal.head(),
                journal: reopened.head(),
            });
        }
        Ok(journal.head())
    }
}

#[derive(Clone, Debug)]
pub struct FilePlannerJournalAnchorV1 {
    path: PathBuf,
    lock_path: PathBuf,
}

impl FilePlannerJournalAnchorV1 {
    #[must_use]
    pub fn new(path: impl Into<PathBuf>) -> Self {
        let path = path.into();
        Self {
            lock_path: path.with_extension("lock"),
            path,
        }
    }

    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }
}

impl PlannerJournalAnchorV1 for FilePlannerJournalAnchorV1 {
    fn load_head(&mut self) -> Result<PlannerJournalHeadV1, PlannerJournalStoreError> {
        let Some(bytes) = read_optional(&self.path, "read journal anchor")? else {
            return Ok(PlannerJournalHeadV1::empty());
        };
        decode_anchor(&bytes)
    }

    fn compare_and_advance(
        &mut self,
        expected: PlannerJournalHeadV1,
        next: PlannerJournalHeadV1,
    ) -> Result<(), PlannerJournalStoreError> {
        ensure_parent(&self.path)?;
        let _guard = FileLockGuard::acquire(&self.lock_path)?;
        let current = match read_optional(&self.path, "read journal anchor before advance")? {
            Some(bytes) => decode_anchor(&bytes)?,
            None => PlannerJournalHeadV1::empty(),
        };
        if current != expected {
            return Err(PlannerJournalStoreError::Conflict {
                expected,
                actual: current,
            });
        }
        validate_anchor_advance(current, next)?;
        atomic_replace(
            &self.path,
            &self.path.with_extension("tmp"),
            &encode_anchor(next),
            "write journal anchor",
        )
    }
}

#[derive(Debug)]
pub struct DurablePlannerJournalV1<S, A> {
    journal: PlannerJournalV1,
    store: S,
    anchor: A,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurablePlannerJournalError {
    Journal(PlannerJournalError),
    Store(PlannerJournalStoreError),
}

impl std::fmt::Display for DurablePlannerJournalError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for DurablePlannerJournalError {}

impl From<PlannerJournalError> for DurablePlannerJournalError {
    fn from(error: PlannerJournalError) -> Self {
        Self::Journal(error)
    }
}

impl From<PlannerJournalStoreError> for DurablePlannerJournalError {
    fn from(error: PlannerJournalStoreError) -> Self {
        Self::Store(error)
    }
}

impl<S: PlannerJournalStoreV1, A: PlannerJournalAnchorV1> DurablePlannerJournalV1<S, A> {
    pub fn open(mut store: S, mut anchor: A) -> Result<Self, DurablePlannerJournalError> {
        let journal = match store.load()? {
            Some(bytes) => PlannerJournalV1::reopen(&bytes)?,
            None => PlannerJournalV1::new(),
        };
        let journal_head = journal.head();
        let anchor_head = anchor.load_head()?;
        if journal_head != anchor_head {
            if journal_head.sequence < anchor_head.sequence {
                return Err(PlannerJournalStoreError::RollbackDetected {
                    anchor: anchor_head,
                    journal: journal_head,
                }
                .into());
            }
            if !journal.contains_head(anchor_head) {
                return Err(PlannerJournalStoreError::ForkDetected {
                    anchor: anchor_head,
                    journal: journal_head,
                }
                .into());
            }
            // The store commit reached durable media before the independently
            // provisioned anchor advanced. Recover only along the exact chain.
            anchor.compare_and_advance(anchor_head, journal_head)?;
        }
        Ok(Self {
            journal,
            store,
            anchor,
        })
    }

    #[must_use]
    pub fn journal(&self) -> &PlannerJournalV1 {
        &self.journal
    }

    #[must_use]
    pub fn head(&self) -> PlannerJournalHeadV1 {
        self.journal.head()
    }

    pub fn record_snapshot(
        &mut self,
        snapshot: &GlobalStateSnapshotV1,
    ) -> Result<PlannerJournalEntryV1, DurablePlannerJournalError> {
        let mut staged = self.journal.clone();
        let entry = staged.record_snapshot(snapshot)?;
        self.commit(staged)?;
        Ok(entry)
    }

    pub fn record_decision(
        &mut self,
        receipt: &FeasiblePlanReceiptV1,
    ) -> Result<PlannerJournalEntryV1, DurablePlannerJournalError> {
        let mut staged = self.journal.clone();
        let entry = staged.record_decision(receipt)?;
        self.commit(staged)?;
        Ok(entry)
    }

    pub fn select_plan(
        &mut self,
        operation_identity_digest: Digest32,
        receipt: &FeasiblePlanReceiptV1,
    ) -> Result<PlannerJournalEntryV1, DurablePlannerJournalError> {
        let mut staged = self.journal.clone();
        let entry = staged.select_plan(operation_identity_digest, receipt)?;
        self.commit(staged)?;
        Ok(entry)
    }

    pub fn revoke(
        &mut self,
        revocation_identity_digest: Digest32,
        target_digest: Digest32,
    ) -> Result<PlannerJournalEntryV1, DurablePlannerJournalError> {
        let mut staged = self.journal.clone();
        let entry = staged.revoke(revocation_identity_digest, target_digest)?;
        self.commit(staged)?;
        Ok(entry)
    }

    #[must_use]
    pub fn into_parts(self) -> (PlannerJournalV1, S, A) {
        (self.journal, self.store, self.anchor)
    }

    fn commit(&mut self, staged: PlannerJournalV1) -> Result<(), DurablePlannerJournalError> {
        let expected = self.journal.head();
        let next = staged.head();
        let committed = self.store.compare_and_commit(expected, &staged)?;
        if committed != next {
            return Err(PlannerJournalStoreError::ForkDetected {
                anchor: next,
                journal: committed,
            }
            .into());
        }
        // Publish the locally durable chain before advancing the independent
        // anchor. A crash in this interval is recovered only when the old
        // anchor is an exact predecessor in the durable journal.
        self.journal = staged;
        self.anchor.compare_and_advance(expected, next)?;
        Ok(())
    }
}

fn validate_anchor_advance(
    current: PlannerJournalHeadV1,
    proposed: PlannerJournalHeadV1,
) -> Result<(), PlannerJournalStoreError> {
    if proposed.sequence < current.sequence
        || (proposed.sequence == current.sequence && proposed.entry_digest != current.entry_digest)
    {
        return Err(PlannerJournalStoreError::AnchorRegression { current, proposed });
    }
    Ok(())
}

fn journal_head_from_bytes(
    bytes: Option<&[u8]>,
) -> Result<PlannerJournalHeadV1, PlannerJournalStoreError> {
    match bytes {
        Some(bytes) => Ok(PlannerJournalV1::reopen(bytes)?.head()),
        None => Ok(PlannerJournalHeadV1::empty()),
    }
}

fn encode_anchor(head: PlannerJournalHeadV1) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(ANCHOR_BYTES);
    bytes.extend_from_slice(ANCHOR_MAGIC);
    bytes.extend_from_slice(&head.sequence.to_be_bytes());
    bytes.extend_from_slice(head.entry_digest.as_array());
    bytes
}

fn decode_anchor(bytes: &[u8]) -> Result<PlannerJournalHeadV1, PlannerJournalStoreError> {
    if bytes.len() != ANCHOR_BYTES || &bytes[..8] != ANCHOR_MAGIC {
        return Err(PlannerJournalStoreError::CorruptAnchor);
    }
    let sequence = u64::from_be_bytes(
        bytes[8..16]
            .try_into()
            .map_err(|_| PlannerJournalStoreError::CorruptAnchor)?,
    );
    let digest = Digest32::from_array(
        bytes[16..48]
            .try_into()
            .map_err(|_| PlannerJournalStoreError::CorruptAnchor)?,
    );
    if sequence == 0 && !digest.is_zero() {
        return Err(PlannerJournalStoreError::CorruptAnchor);
    }
    if sequence != 0 && digest.is_zero() {
        return Err(PlannerJournalStoreError::CorruptAnchor);
    }
    Ok(PlannerJournalHeadV1 {
        sequence,
        entry_digest: digest,
    })
}

fn read_optional(
    path: &Path,
    operation: &'static str,
) -> Result<Option<Vec<u8>>, PlannerJournalStoreError> {
    match fs::read(path) {
        Ok(bytes) => Ok(Some(bytes)),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(None),
        Err(error) => Err(io_error(operation, error.kind())),
    }
}

fn ensure_parent(path: &Path) -> Result<(), PlannerJournalStoreError> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent).map_err(|error| io_error("create journal directory", error.kind()))
}

fn atomic_replace(
    path: &Path,
    temporary: &Path,
    bytes: &[u8],
    operation: &'static str,
) -> Result<(), PlannerJournalStoreError> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(temporary)
        .map_err(|error| io_error(operation, error.kind()))?;
    file.write_all(bytes)
        .map_err(|error| io_error(operation, error.kind()))?;
    file.sync_all()
        .map_err(|error| io_error(operation, error.kind()))?;
    drop(file);
    fs::rename(temporary, path).map_err(|error| io_error(operation, error.kind()))?;
    sync_parent(parent)
}

#[cfg(unix)]
fn sync_parent(parent: &Path) -> Result<(), PlannerJournalStoreError> {
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| io_error("sync journal directory", error.kind()))
}

#[cfg(not(unix))]
fn sync_parent(_parent: &Path) -> Result<(), PlannerJournalStoreError> {
    Ok(())
}

fn io_error(operation: &'static str, kind: ErrorKind) -> PlannerJournalStoreError {
    PlannerJournalStoreError::Io { operation, kind }
}

struct FileLockGuard {
    path: PathBuf,
    _file: File,
}

impl FileLockGuard {
    fn acquire(path: &Path) -> Result<Self, PlannerJournalStoreError> {
        let file = match OpenOptions::new().write(true).create_new(true).open(path) {
            Ok(file) => file,
            Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                return Err(PlannerJournalStoreError::Busy);
            }
            Err(error) => return Err(io_error("acquire journal lock", error.kind())),
        };
        Ok(Self {
            path: path.to_path_buf(),
            _file: file,
        })
    }
}

impl Drop for FileLockGuard {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

#[cfg(test)]
#[path = "planner_journal_store_tests.rs"]
mod tests;
