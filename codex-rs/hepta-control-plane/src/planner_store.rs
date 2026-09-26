//! Crash-bounded durable owner store for planner decisions and execution evidence.
//!
//! V1 deliberately uses a Unix durability profile: one exclusive writer, a
//! versioned self-validating image, temporary-file write, file synchronization,
//! atomic rename and parent-directory synchronization.  A directory-sync
//! failure poisons the open handle because the rename may already be visible.
//! Reopening reconciles to the last complete validated image.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_types::Digest32;

use crate::FeasiblePlanReceiptV1;
use crate::GlobalStateSnapshotV1;
use crate::PlannerJournalEntryV1;
use crate::PlannerJournalError;
use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;

const LOCK_FILE: &str = ".planner-store.lock";
const STORE_FILE: &str = "planner.store";
const TEMP_FILE: &str = ".planner.store.tmp";
const STORE_MAGIC: &[u8; 8] = b"HCPSTR01";
const LEGACY_JOURNAL_MAGIC: &[u8; 8] = b"HCPJNL01";
const STORE_SCHEMA_VERSION: u32 = 1;
const MAX_BODIES: usize = 4096;
const MAX_BODY_BYTES: usize = 1024 * 1024;
const MAX_STORE_BYTES: usize = 64 * 1024 * 1024;
const IMAGE_DIGEST_BYTES: usize = 32;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PlannerBodyKindV1 {
    Snapshot,
    Decision,
    AuthorityRequest,
    AuthorityGrant,
    TerminalReceipt,
    Reconciliation,
}

impl PlannerBodyKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Snapshot => 0,
            Self::Decision => 1,
            Self::AuthorityRequest => 2,
            Self::AuthorityGrant => 3,
            Self::TerminalReceipt => 4,
            Self::Reconciliation => 5,
        }
    }

    fn from_tag(value: u8) -> Result<Self, PlannerStoreError> {
        match value {
            0 => Ok(Self::Snapshot),
            1 => Ok(Self::Decision),
            2 => Ok(Self::AuthorityRequest),
            3 => Ok(Self::AuthorityGrant),
            4 => Ok(Self::TerminalReceipt),
            5 => Ok(Self::Reconciliation),
            _ => Err(PlannerStoreError::UnknownBodyKind(value)),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredPlannerBodyV1 {
    kind: PlannerBodyKindV1,
    semantic_digest: Digest32,
    content_digest: Digest32,
    parent_digest: Option<Digest32>,
    bytes: Vec<u8>,
}

impl StoredPlannerBodyV1 {
    #[must_use]
    pub const fn kind(&self) -> PlannerBodyKindV1 {
        self.kind
    }

    #[must_use]
    pub const fn semantic_digest(&self) -> Digest32 {
        self.semantic_digest
    }

    #[must_use]
    pub const fn content_digest(&self) -> Digest32 {
        self.content_digest
    }

    #[must_use]
    pub const fn parent_digest(&self) -> Option<Digest32> {
        self.parent_digest
    }

    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlannerCheckpointV1 {
    content_root_digest: Digest32,
    external_anchor_digest: Digest32,
}

impl PlannerCheckpointV1 {
    #[must_use]
    pub const fn content_root_digest(&self) -> Digest32 {
        self.content_root_digest
    }

    #[must_use]
    pub const fn external_anchor_digest(&self) -> Digest32 {
        self.external_anchor_digest
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerStoreError {
    UnsupportedPlatform,
    Busy,
    NotDirectory,
    NotRegular,
    Symlink,
    EmptyDigest,
    EmptyBody,
    BodyTooLarge,
    StoreTooLarge,
    BodyLimitExceeded,
    BodyConflict,
    MissingParent,
    BackupRegression,
    CorruptHeader,
    UnsupportedSchema(u32),
    Truncated,
    UnknownBodyKind(u8),
    CorruptBody,
    CorruptImageDigest,
    CorruptCheckpoint,
    Journal(PlannerJournalError),
    Io(io::ErrorKind),
    /// A rename may have committed while parent-directory durability could not
    /// be acknowledged.  Reopen before any authoritative read or mutation.
    Indeterminate,
}

impl fmt::Display for PlannerStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlannerStoreError {}

impl From<io::Error> for PlannerStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

impl From<PlannerJournalError> for PlannerStoreError {
    fn from(error: PlannerJournalError) -> Self {
        Self::Journal(error)
    }
}

trait PlannerPersistenceV1: Send + Sync {
    fn write_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()>;
    fn sync_temp(&self, path: &Path) -> io::Result<()>;
    fn rename(&self, from: &Path, to: &Path) -> io::Result<()>;
    fn sync_parent(&self, root: &Path) -> io::Result<()>;
}

#[derive(Clone, Copy, Debug, Default)]
struct FsPlannerPersistenceV1;

impl PlannerPersistenceV1 for FsPlannerPersistenceV1 {
    fn write_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()> {
        let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
        file.write_all(bytes)
    }

    fn sync_temp(&self, path: &Path) -> io::Result<()> {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)?
            .sync_all()
    }

    fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
        fs::rename(from, to)
    }

    fn sync_parent(&self, root: &Path) -> io::Result<()> {
        #[cfg(unix)]
        {
            File::open(root)?.sync_all()
        }
        #[cfg(not(unix))]
        {
            let _ = root;
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "PlannerStoreV1 requires Unix directory durability semantics",
            ))
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct PlannerStoreImageV1 {
    journal: PlannerJournalV1,
    bodies: BTreeMap<Digest32, StoredPlannerBodyV1>,
    checkpoint: Option<PlannerCheckpointV1>,
}

impl PlannerStoreImageV1 {
    fn new() -> Self {
        Self {
            journal: PlannerJournalV1::new(),
            bodies: BTreeMap::new(),
            checkpoint: None,
        }
    }

    fn content_root_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.control.planner-store-content-root.v1".to_vec();
        let journal = self.journal.export_bytes();
        push_u32(&mut bytes, journal.len());
        bytes.extend_from_slice(&journal);
        push_u32(&mut bytes, self.bodies.len());
        for body in self.bodies.values() {
            push_body_binding(&mut bytes, body);
        }
        Digest32::of_bytes(&bytes)
    }

    fn export_bytes(&self) -> Result<Vec<u8>, PlannerStoreError> {
        if self.bodies.len() > MAX_BODIES {
            return Err(PlannerStoreError::BodyLimitExceeded);
        }
        if let Some(checkpoint) = self.checkpoint {
            if checkpoint.content_root_digest != self.content_root_digest()
                || checkpoint.external_anchor_digest.is_zero()
            {
                return Err(PlannerStoreError::CorruptCheckpoint);
            }
        }

        let journal = self.journal.export_bytes();
        let mut bytes = Vec::new();
        bytes.extend_from_slice(STORE_MAGIC);
        bytes.extend_from_slice(&STORE_SCHEMA_VERSION.to_be_bytes());
        push_u32(&mut bytes, journal.len());
        push_u32(&mut bytes, self.bodies.len());
        bytes.push(u8::from(self.checkpoint.is_some()));
        bytes.extend_from_slice(&journal);
        for body in self.bodies.values() {
            bytes.push(body.kind.tag());
            bytes.extend_from_slice(body.semantic_digest.as_array());
            bytes.extend_from_slice(body.content_digest.as_array());
            bytes.push(u8::from(body.parent_digest.is_some()));
            if let Some(parent) = body.parent_digest {
                bytes.extend_from_slice(parent.as_array());
            }
            push_u32(&mut bytes, body.bytes.len());
            bytes.extend_from_slice(&body.bytes);
        }
        if let Some(checkpoint) = self.checkpoint {
            bytes.extend_from_slice(checkpoint.content_root_digest.as_array());
            bytes.extend_from_slice(checkpoint.external_anchor_digest.as_array());
        }
        let digest = image_digest(&bytes);
        bytes.extend_from_slice(digest.as_array());
        if bytes.len() > MAX_STORE_BYTES {
            return Err(PlannerStoreError::StoreTooLarge);
        }
        Ok(bytes)
    }

    fn reopen(bytes: &[u8]) -> Result<Self, PlannerStoreError> {
        if bytes.len() > MAX_STORE_BYTES {
            return Err(PlannerStoreError::StoreTooLarge);
        }
        if bytes.len() < STORE_MAGIC.len() + 4 + 4 + 4 + 1 + IMAGE_DIGEST_BYTES {
            return Err(PlannerStoreError::Truncated);
        }
        let payload_len = bytes
            .len()
            .checked_sub(IMAGE_DIGEST_BYTES)
            .ok_or(PlannerStoreError::Truncated)?;
        let payload = bytes
            .get(..payload_len)
            .ok_or(PlannerStoreError::Truncated)?;
        let expected_digest = read_digest_at(bytes, payload_len)?;
        if image_digest(payload) != expected_digest {
            return Err(PlannerStoreError::CorruptImageDigest);
        }

        let mut offset = 0;
        if read_exact(bytes, &mut offset, STORE_MAGIC.len())? != STORE_MAGIC {
            return Err(PlannerStoreError::CorruptHeader);
        }
        let schema = read_u32(bytes, &mut offset)?;
        if schema != STORE_SCHEMA_VERSION {
            return Err(PlannerStoreError::UnsupportedSchema(schema));
        }
        let journal_len = usize::try_from(read_u32(bytes, &mut offset)?)
            .map_err(|_| PlannerStoreError::StoreTooLarge)?;
        let body_count = usize::try_from(read_u32(bytes, &mut offset)?)
            .map_err(|_| PlannerStoreError::BodyLimitExceeded)?;
        if body_count > MAX_BODIES {
            return Err(PlannerStoreError::BodyLimitExceeded);
        }
        let has_checkpoint = match read_u8(bytes, &mut offset)? {
            0 => false,
            1 => true,
            _ => return Err(PlannerStoreError::CorruptCheckpoint),
        };
        let journal_bytes = read_exact(bytes, &mut offset, journal_len)?;
        let journal = PlannerJournalV1::reopen(journal_bytes)?;

        let mut bodies = BTreeMap::new();
        for _ in 0..body_count {
            let kind = PlannerBodyKindV1::from_tag(read_u8(bytes, &mut offset)?)?;
            let semantic_digest = read_digest(bytes, &mut offset)?;
            let content_digest = read_digest(bytes, &mut offset)?;
            if semantic_digest.is_zero() || content_digest.is_zero() {
                return Err(PlannerStoreError::EmptyDigest);
            }
            let parent_digest = match read_u8(bytes, &mut offset)? {
                0 => None,
                1 => {
                    let parent = read_digest(bytes, &mut offset)?;
                    if parent.is_zero() {
                        return Err(PlannerStoreError::EmptyDigest);
                    }
                    Some(parent)
                }
                _ => return Err(PlannerStoreError::CorruptBody),
            };
            let body_len = usize::try_from(read_u32(bytes, &mut offset)?)
                .map_err(|_| PlannerStoreError::BodyTooLarge)?;
            if body_len == 0 {
                return Err(PlannerStoreError::EmptyBody);
            }
            if body_len > MAX_BODY_BYTES {
                return Err(PlannerStoreError::BodyTooLarge);
            }
            let body_bytes = read_exact(bytes, &mut offset, body_len)?.to_vec();
            if Digest32::of_bytes(&body_bytes) != content_digest {
                return Err(PlannerStoreError::CorruptBody);
            }
            let body = StoredPlannerBodyV1 {
                kind,
                semantic_digest,
                content_digest,
                parent_digest,
                bytes: body_bytes,
            };
            if bodies.insert(semantic_digest, body).is_some() {
                return Err(PlannerStoreError::BodyConflict);
            }
        }

        let checkpoint = if has_checkpoint {
            Some(PlannerCheckpointV1 {
                content_root_digest: read_digest(bytes, &mut offset)?,
                external_anchor_digest: read_digest(bytes, &mut offset)?,
            })
        } else {
            None
        };
        if offset != payload_len {
            return Err(PlannerStoreError::Truncated);
        }

        let image = Self {
            journal,
            bodies,
            checkpoint,
        };
        if let Some(checkpoint) = image.checkpoint {
            if checkpoint.content_root_digest != image.content_root_digest()
                || checkpoint.external_anchor_digest.is_zero()
            {
                return Err(PlannerStoreError::CorruptCheckpoint);
            }
        }
        image.validate_parent_links()?;
        Ok(image)
    }

    fn validate_parent_links(&self) -> Result<(), PlannerStoreError> {
        for body in self.bodies.values() {
            if let Some(parent) = body.parent_digest {
                let journal_knows_parent = self.journal.entries().iter().any(|entry| {
                    entry.identity_digest == parent || entry.payload_digest == parent
                });
                if !self.bodies.contains_key(&parent) && !journal_knows_parent {
                    return Err(PlannerStoreError::MissingParent);
                }
            }
        }
        Ok(())
    }

    fn insert_body(
        &mut self,
        kind: PlannerBodyKindV1,
        semantic_digest: Digest32,
        parent_digest: Option<Digest32>,
        bytes: &[u8],
    ) -> Result<StoredPlannerBodyV1, PlannerStoreError> {
        if semantic_digest.is_zero() || parent_digest.is_some_and(|digest| digest.is_zero()) {
            return Err(PlannerStoreError::EmptyDigest);
        }
        if bytes.is_empty() {
            return Err(PlannerStoreError::EmptyBody);
        }
        if bytes.len() > MAX_BODY_BYTES {
            return Err(PlannerStoreError::BodyTooLarge);
        }
        if self.bodies.len() >= MAX_BODIES && !self.bodies.contains_key(&semantic_digest) {
            return Err(PlannerStoreError::BodyLimitExceeded);
        }
        if let Some(parent) = parent_digest {
            let journal_knows_parent = self.journal.entries().iter().any(|entry| {
                entry.identity_digest == parent || entry.payload_digest == parent
            });
            if !self.bodies.contains_key(&parent) && !journal_knows_parent {
                return Err(PlannerStoreError::MissingParent);
            }
        }
        let candidate = StoredPlannerBodyV1 {
            kind,
            semantic_digest,
            content_digest: Digest32::of_bytes(bytes),
            parent_digest,
            bytes: bytes.to_vec(),
        };
        if let Some(existing) = self.bodies.get(&semantic_digest) {
            if existing == &candidate {
                return Ok(existing.clone());
            }
            return Err(PlannerStoreError::BodyConflict);
        }
        self.bodies.insert(semantic_digest, candidate.clone());
        Ok(candidate)
    }
}

/// Exclusive owner-local writer for planner decisions and their exact evidence
/// bodies.  The store itself grants no execution authority.
pub struct PlannerStoreV1 {
    root: PathBuf,
    lock: File,
    image: PlannerStoreImageV1,
    persistence: Arc<dyn PlannerPersistenceV1>,
    indeterminate: bool,
}

impl PlannerStoreV1 {
    /// Open an existing owner-authorized directory or initialize its V1 image.
    /// The directory must already exist; this API never widens filesystem scope.
    pub fn open(root: impl AsRef<Path>) -> Result<Self, PlannerStoreError> {
        Self::open_with_persistence(root, Arc::new(FsPlannerPersistenceV1))
    }

    fn open_with_persistence(
        root: impl AsRef<Path>,
        persistence: Arc<dyn PlannerPersistenceV1>,
    ) -> Result<Self, PlannerStoreError> {
        if !cfg!(unix) {
            return Err(PlannerStoreError::UnsupportedPlatform);
        }
        let root = root.as_ref().to_path_buf();
        let metadata = fs::symlink_metadata(&root)?;
        if metadata.file_type().is_symlink() {
            return Err(PlannerStoreError::Symlink);
        }
        if !metadata.is_dir() {
            return Err(PlannerStoreError::NotDirectory);
        }

        let lock_path = root.join(LOCK_FILE);
        reject_existing_symlink(&lock_path)?;
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&lock_path)?;
        if !lock.metadata()?.is_file() {
            return Err(PlannerStoreError::NotRegular);
        }
        match File::try_lock(&lock) {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(PlannerStoreError::Busy),
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }

        let temp_path = root.join(TEMP_FILE);
        match fs::remove_file(&temp_path) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }

        let store_path = root.join(STORE_FILE);
        reject_existing_symlink(&store_path)?;
        let image = match File::open(&store_path) {
            Ok(mut file) => {
                if !file.metadata()?.is_file() {
                    return Err(PlannerStoreError::NotRegular);
                }
                let mut bytes = Vec::new();
                file.read_to_end(&mut bytes)?;
                if bytes.len() > MAX_STORE_BYTES {
                    return Err(PlannerStoreError::StoreTooLarge);
                }
                if bytes.starts_with(LEGACY_JOURNAL_MAGIC) {
                    let migrated = PlannerStoreImageV1 {
                        journal: PlannerJournalV1::reopen(&bytes)?,
                        bodies: BTreeMap::new(),
                        checkpoint: None,
                    };
                    persist_image(&root, &migrated, persistence.as_ref())?;
                    migrated
                } else {
                    PlannerStoreImageV1::reopen(&bytes)?
                }
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                let image = PlannerStoreImageV1::new();
                persist_image(&root, &image, persistence.as_ref())?;
                image
            }
            Err(error) => return Err(error.into()),
        };

        Ok(Self {
            root,
            lock,
            image,
            persistence,
            indeterminate: false,
        })
    }

    #[must_use]
    pub const fn is_indeterminate(&self) -> bool {
        self.indeterminate
    }

    pub fn entries(&self) -> Result<&[PlannerJournalEntryV1], PlannerStoreError> {
        self.ensure_authoritative()?;
        Ok(self.image.journal.entries())
    }

    pub fn body(
        &self,
        semantic_digest: Digest32,
    ) -> Result<Option<&StoredPlannerBodyV1>, PlannerStoreError> {
        self.ensure_authoritative()?;
        Ok(self.image.bodies.get(&semantic_digest))
    }

    pub fn checkpoint(&self) -> Result<Option<PlannerCheckpointV1>, PlannerStoreError> {
        self.ensure_authoritative()?;
        Ok(self.image.checkpoint)
    }

    pub fn selected_plan_digest(&self) -> Result<Option<Digest32>, PlannerStoreError> {
        self.ensure_authoritative()?;
        Ok(self.image.journal.selected_plan_digest())
    }

    /// Reports whether every snapshot and decision record has an exact body.
    /// Legacy journal migration remains readable but returns false until bodies
    /// are supplied by the authoritative owner.
    pub fn has_complete_body_coverage(&self) -> Result<bool, PlannerStoreError> {
        self.ensure_authoritative()?;
        Ok(self.image.journal.entries().iter().all(|entry| {
            !matches!(
                entry.kind,
                PlannerJournalKindV1::Snapshot | PlannerJournalKindV1::Decision
            ) || self.image.bodies.contains_key(&entry.payload_digest)
        }))
    }

    pub fn record_snapshot(
        &mut self,
        snapshot: &GlobalStateSnapshotV1,
        canonical_body: &[u8],
    ) -> Result<PlannerJournalEntryV1, PlannerStoreError> {
        let semantic_digest = snapshot.snapshot_digest();
        self.commit(|image| {
            let entry = image.journal.record_snapshot(snapshot)?;
            image.insert_body(
                PlannerBodyKindV1::Snapshot,
                semantic_digest,
                None,
                canonical_body,
            )?;
            Ok(entry)
        })
    }

    pub fn record_decision(
        &mut self,
        receipt: &FeasiblePlanReceiptV1,
        canonical_body: &[u8],
    ) -> Result<PlannerJournalEntryV1, PlannerStoreError> {
        let semantic_digest = receipt.receipt_digest();
        self.commit(|image| {
            let entry = image.journal.record_decision(receipt)?;
            image.insert_body(
                PlannerBodyKindV1::Decision,
                semantic_digest,
                None,
                canonical_body,
            )?;
            Ok(entry)
        })
    }

    pub fn record_evidence(
        &mut self,
        kind: PlannerBodyKindV1,
        semantic_digest: Digest32,
        parent_digest: Digest32,
        canonical_body: &[u8],
    ) -> Result<StoredPlannerBodyV1, PlannerStoreError> {
        if matches!(kind, PlannerBodyKindV1::Snapshot | PlannerBodyKindV1::Decision) {
            return Err(PlannerStoreError::CorruptBody);
        }
        self.commit(|image| {
            image.insert_body(kind, semantic_digest, Some(parent_digest), canonical_body)
        })
    }

    pub fn select_plan(
        &mut self,
        operation_identity_digest: Digest32,
        receipt: &FeasiblePlanReceiptV1,
    ) -> Result<PlannerJournalEntryV1, PlannerStoreError> {
        self.commit(|image| {
            Ok(image
                .journal
                .select_plan(operation_identity_digest, receipt)?)
        })
    }

    pub fn revoke(
        &mut self,
        revocation_identity_digest: Digest32,
        target_digest: Digest32,
    ) -> Result<PlannerJournalEntryV1, PlannerStoreError> {
        self.commit(|image| {
            Ok(image
                .journal
                .revoke(revocation_identity_digest, target_digest)?)
        })
    }

    /// Persist an externally issued evidence receipt over the current content
    /// root.  The anchor may be a signature receipt, transparency-log entry or
    /// another independently governed immutable evidence identity.
    pub fn anchor_checkpoint(
        &mut self,
        external_anchor_digest: Digest32,
    ) -> Result<PlannerCheckpointV1, PlannerStoreError> {
        self.ensure_authoritative()?;
        if external_anchor_digest.is_zero() {
            return Err(PlannerStoreError::EmptyDigest);
        }
        let mut candidate = self.image.clone();
        let checkpoint = PlannerCheckpointV1 {
            content_root_digest: candidate.content_root_digest(),
            external_anchor_digest,
        };
        candidate.checkpoint = Some(checkpoint);
        self.persist_candidate(candidate)?;
        Ok(checkpoint)
    }

    /// Bounded retention compaction. Snapshot and decision bodies are always
    /// retained. Other evidence may be pruned only with an explicit external
    /// archive anchor and an allow-set of semantic digests to keep online.
    pub fn compact_evidence(
        &mut self,
        retain_online: &BTreeSet<Digest32>,
        archive_anchor_digest: Digest32,
    ) -> Result<usize, PlannerStoreError> {
        self.ensure_authoritative()?;
        if archive_anchor_digest.is_zero() {
            return Err(PlannerStoreError::EmptyDigest);
        }
        let mut candidate = self.image.clone();
        let before = candidate.bodies.len();
        candidate.bodies.retain(|semantic, body| {
            matches!(
                body.kind,
                PlannerBodyKindV1::Snapshot | PlannerBodyKindV1::Decision
            ) || retain_online.contains(semantic)
        });
        candidate.validate_parent_links()?;
        candidate.checkpoint = Some(PlannerCheckpointV1 {
            content_root_digest: candidate.content_root_digest(),
            external_anchor_digest: archive_anchor_digest,
        });
        let removed = before.saturating_sub(candidate.bodies.len());
        self.persist_candidate(candidate)?;
        Ok(removed)
    }

    /// Complete self-validating backup image. Transport encryption, remote
    /// retention and external acknowledgement remain the caller's authority.
    pub fn backup_bytes(&self) -> Result<Vec<u8>, PlannerStoreError> {
        self.ensure_authoritative()?;
        self.image.export_bytes()
    }

    /// Restore only a monotonic extension of the current journal and body set.
    /// This prevents an older valid backup from deleting a later revocation or
    /// replacing an already-bound canonical body.
    pub fn restore_backup(&mut self, bytes: &[u8]) -> Result<(), PlannerStoreError> {
        self.ensure_authoritative()?;
        let restored = PlannerStoreImageV1::reopen(bytes)?;
        let current_entries = self.image.journal.entries();
        if restored.journal.entries().len() < current_entries.len()
            || &restored.journal.entries()[..current_entries.len()] != current_entries
        {
            return Err(PlannerStoreError::BackupRegression);
        }
        for (digest, body) in &self.image.bodies {
            if restored.bodies.get(digest) != Some(body) {
                return Err(PlannerStoreError::BackupRegression);
            }
        }
        self.persist_candidate(restored)
    }

    fn ensure_authoritative(&self) -> Result<(), PlannerStoreError> {
        if self.indeterminate {
            Err(PlannerStoreError::Indeterminate)
        } else {
            Ok(())
        }
    }

    fn commit<T, F>(&mut self, mutation: F) -> Result<T, PlannerStoreError>
    where
        F: FnOnce(&mut PlannerStoreImageV1) -> Result<T, PlannerStoreError>,
    {
        self.ensure_authoritative()?;
        let mut candidate = self.image.clone();
        candidate.checkpoint = None;
        let result = mutation(&mut candidate)?;
        candidate.validate_parent_links()?;
        self.persist_candidate(candidate)?;
        Ok(result)
    }

    fn persist_candidate(
        &mut self,
        candidate: PlannerStoreImageV1,
    ) -> Result<(), PlannerStoreError> {
        match persist_image(&self.root, &candidate, self.persistence.as_ref()) {
            Ok(()) => {
                self.image = candidate;
                Ok(())
            }
            Err(PlannerStoreError::Indeterminate) => {
                self.indeterminate = true;
                Err(PlannerStoreError::Indeterminate)
            }
            Err(error) => Err(error),
        }
    }
}

impl Drop for PlannerStoreV1 {
    fn drop(&mut self) {
        let _ = File::unlock(&self.lock);
    }
}

fn reject_existing_symlink(path: &Path) -> Result<(), PlannerStoreError> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => Err(PlannerStoreError::Symlink),
        Ok(_) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn persist_image(
    root: &Path,
    image: &PlannerStoreImageV1,
    persistence: &dyn PlannerPersistenceV1,
) -> Result<(), PlannerStoreError> {
    if !cfg!(unix) {
        return Err(PlannerStoreError::UnsupportedPlatform);
    }
    let bytes = image.export_bytes()?;
    let temp_path = root.join(TEMP_FILE);
    let store_path = root.join(STORE_FILE);

    match persistence.write_temp(&temp_path, &bytes) {
        Ok(()) => {}
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
            fs::remove_file(&temp_path)?;
            persistence.write_temp(&temp_path, &bytes)?;
        }
        Err(error) => return Err(error.into()),
    }
    if let Err(error) = persistence.sync_temp(&temp_path) {
        let _ = fs::remove_file(&temp_path);
        return Err(error.into());
    }
    if let Err(error) = persistence.rename(&temp_path, &store_path) {
        let _ = fs::remove_file(&temp_path);
        return Err(error.into());
    }
    persistence
        .sync_parent(root)
        .map_err(|_| PlannerStoreError::Indeterminate)
}

fn push_body_binding(bytes: &mut Vec<u8>, body: &StoredPlannerBodyV1) {
    bytes.push(body.kind.tag());
    bytes.extend_from_slice(body.semantic_digest.as_array());
    bytes.extend_from_slice(body.content_digest.as_array());
    bytes.push(u8::from(body.parent_digest.is_some()));
    if let Some(parent) = body.parent_digest {
        bytes.extend_from_slice(parent.as_array());
    }
    push_u32(bytes, body.bytes.len());
}

fn image_digest(bytes: &[u8]) -> Digest32 {
    let mut material = b"hepta.control.planner-store-image.v1".to_vec();
    material.extend_from_slice(bytes);
    Digest32::of_bytes(&material)
}

fn push_u32(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u32::try_from(value).unwrap_or(u32::MAX).to_be_bytes());
}

fn read_exact<'a>(
    bytes: &'a [u8],
    offset: &mut usize,
    len: usize,
) -> Result<&'a [u8], PlannerStoreError> {
    let end = (*offset)
        .checked_add(len)
        .ok_or(PlannerStoreError::Truncated)?;
    let value = bytes
        .get(*offset..end)
        .ok_or(PlannerStoreError::Truncated)?;
    *offset = end;
    Ok(value)
}

fn read_u8(bytes: &[u8], offset: &mut usize) -> Result<u8, PlannerStoreError> {
    Ok(*read_exact(bytes, offset, 1)?
        .first()
        .ok_or(PlannerStoreError::Truncated)?)
}

fn read_u32(bytes: &[u8], offset: &mut usize) -> Result<u32, PlannerStoreError> {
    Ok(u32::from_be_bytes(
        read_exact(bytes, offset, 4)?
            .try_into()
            .map_err(|_| PlannerStoreError::Truncated)?,
    ))
}

fn read_digest(bytes: &[u8], offset: &mut usize) -> Result<Digest32, PlannerStoreError> {
    let array: [u8; 32] = read_exact(bytes, offset, 32)?
        .try_into()
        .map_err(|_| PlannerStoreError::Truncated)?;
    Ok(Digest32::from_array(array))
}

fn read_digest_at(bytes: &[u8], offset: usize) -> Result<Digest32, PlannerStoreError> {
    let end = offset
        .checked_add(32)
        .ok_or(PlannerStoreError::Truncated)?;
    let array: [u8; 32] = bytes
        .get(offset..end)
        .ok_or(PlannerStoreError::Truncated)?
        .try_into()
        .map_err(|_| PlannerStoreError::Truncated)?;
    Ok(Digest32::from_array(array))
}

#[cfg(test)]
#[path = "planner_store_tests.rs"]
mod tests;
