use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;

use codex_hepta_types::Digest32;

use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;

const STORE_SCHEMA: u32 = 1;
const MAGIC: &[u8] = b"HEPTA-PLANNER-STORE-V1\0";
const FRAME_MAGIC: &[u8; 4] = b"HPS1";
const LOCK_FILE: &str = ".planner-store.lock";
const STORE_FILE: &str = "planner.store";
const TEMP_FILE: &str = ".planner.store.tmp";
const MAX_RECORDS: usize = 4096;
const MAX_ENVELOPE_BYTES: usize = 1024 * 1024;
const MAX_STORE_BYTES: usize = 64 * 1024 * 1024;
const FIXED_FRAME_PAYLOAD_BYTES: usize = 8 + 1 + 32 + 32 + 32 + 32 + 4;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PlannerStoreRecordKindV1 {
    Snapshot,
    Decision,
    SelectedPlan,
    AuthorityRequest,
    AuthorityDecision,
    EffectDispatch,
    TerminalReceipt,
    Reconciliation,
    Revocation,
    Checkpoint,
}

impl PlannerStoreRecordKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Snapshot => 0,
            Self::Decision => 1,
            Self::SelectedPlan => 2,
            Self::AuthorityRequest => 3,
            Self::AuthorityDecision => 4,
            Self::EffectDispatch => 5,
            Self::TerminalReceipt => 6,
            Self::Reconciliation => 7,
            Self::Revocation => 8,
            Self::Checkpoint => 9,
        }
    }

    fn from_tag(value: u8) -> Result<Self, PlannerStoreError> {
        match value {
            0 => Ok(Self::Snapshot),
            1 => Ok(Self::Decision),
            2 => Ok(Self::SelectedPlan),
            3 => Ok(Self::AuthorityRequest),
            4 => Ok(Self::AuthorityDecision),
            5 => Ok(Self::EffectDispatch),
            6 => Ok(Self::TerminalReceipt),
            7 => Ok(Self::Reconciliation),
            8 => Ok(Self::Revocation),
            9 => Ok(Self::Checkpoint),
            _ => Err(PlannerStoreError::UnknownRecordKind(value)),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerCanonicalEnvelopeV1 {
    kind: PlannerStoreRecordKindV1,
    identity_digest: Digest32,
    semantic_digest: Digest32,
    canonical_body: Vec<u8>,
    body_digest: Digest32,
}

impl PlannerCanonicalEnvelopeV1 {
    pub fn new(
        kind: PlannerStoreRecordKindV1,
        identity_digest: Digest32,
        semantic_digest: Digest32,
        canonical_body: Vec<u8>,
    ) -> Result<Self, PlannerStoreError> {
        if identity_digest.is_zero() || semantic_digest.is_zero() {
            return Err(PlannerStoreError::EmptyDigest);
        }
        if canonical_body.is_empty() || canonical_body.len() > MAX_ENVELOPE_BYTES {
            return Err(PlannerStoreError::EnvelopeSize);
        }
        let body_digest = Digest32::of_bytes(&canonical_body);
        Ok(Self {
            kind,
            identity_digest,
            semantic_digest,
            canonical_body,
            body_digest,
        })
    }

    #[must_use]
    pub const fn kind(&self) -> PlannerStoreRecordKindV1 {
        self.kind
    }

    #[must_use]
    pub const fn identity_digest(&self) -> Digest32 {
        self.identity_digest
    }

    #[must_use]
    pub const fn semantic_digest(&self) -> Digest32 {
        self.semantic_digest
    }

    #[must_use]
    pub fn canonical_body(&self) -> &[u8] {
        &self.canonical_body
    }

    #[must_use]
    pub const fn body_digest(&self) -> Digest32 {
        self.body_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerStoreEntryV1 {
    pub sequence: u64,
    pub kind: PlannerStoreRecordKindV1,
    pub identity_digest: Digest32,
    pub semantic_digest: Digest32,
    pub body_digest: Digest32,
    pub predecessor_frame_digest: Digest32,
    pub frame_digest: Digest32,
    pub canonical_body: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerCheckpointProposalV1 {
    pub previous_root_digest: Digest32,
    pub checkpoint_identity_digest: Digest32,
    pub retained_state_digest: Digest32,
    pub retained_state_bytes: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerCheckpointReceiptV1 {
    pub previous_root_digest: Digest32,
    pub checkpoint_identity_digest: Digest32,
    pub retained_state_digest: Digest32,
    pub external_anchor_digest: Digest32,
    pub checkpoint_frame_digest: Digest32,
}

pub trait PlannerExternalAnchorV1 {
    fn anchor(
        &mut self,
        proposal: &PlannerCheckpointProposalV1,
    ) -> Result<Digest32, PlannerStoreError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerStoreError {
    UnsupportedPlatform,
    Busy,
    NotDirectory,
    NotRegular,
    Symlink,
    EmptyDigest,
    EnvelopeSize,
    RecordLimit,
    StoreSize,
    IdentityConflict,
    DuplicateSerializedIdentity,
    CorruptHeader,
    CorruptFrame,
    CorruptSequence,
    CorruptPredecessor,
    CorruptBodyDigest,
    CorruptFrameDigest,
    UnknownRecordKind(u8),
    BackupRegression,
    MigrationMismatch,
    AnchorRejected,
    Io(io::ErrorKind),
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

trait PlannerPersistenceV1: Send + Sync {
    fn append(&self, path: &Path, bytes: &[u8]) -> io::Result<()>;
    fn sync_file(&self, path: &Path) -> io::Result<()>;
    fn truncate(&self, path: &Path, length: u64) -> io::Result<()>;
    fn write_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()>;
    fn sync_temp(&self, path: &Path) -> io::Result<()>;
    fn rename(&self, from: &Path, to: &Path) -> io::Result<()>;
    fn sync_parent(&self, root: &Path) -> io::Result<()>;
}

#[derive(Clone, Copy, Debug, Default)]
struct FsPlannerPersistenceV1;

impl PlannerPersistenceV1 for FsPlannerPersistenceV1 {
    fn append(&self, path: &Path, bytes: &[u8]) -> io::Result<()> {
        let mut options = private_open_options();
        options.append(true).create(false);
        let mut file = options.open(path)?;
        file.write_all(bytes)
    }

    fn sync_file(&self, path: &Path) -> io::Result<()> {
        OpenOptions::new().read(true).write(true).open(path)?.sync_all()
    }

    fn truncate(&self, path: &Path, length: u64) -> io::Result<()> {
        let file = OpenOptions::new().read(true).write(true).open(path)?;
        file.set_len(length)?;
        file.sync_all()
    }

    fn write_temp(&self, path: &Path, bytes: &[u8]) -> io::Result<()> {
        let mut options = private_open_options();
        options.write(true).create_new(true);
        let mut file = options.open(path)?;
        file.write_all(bytes)
    }

    fn sync_temp(&self, path: &Path) -> io::Result<()> {
        OpenOptions::new().read(true).write(true).open(path)?.sync_all()
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
                "planner store V1 requires Unix directory durability semantics",
            ))
        }
    }
}

pub struct PlannerStoreV1 {
    root: PathBuf,
    lock: File,
    entries: Vec<PlannerStoreEntryV1>,
    identities: BTreeMap<Digest32, usize>,
    committed_len: usize,
    persistence: Arc<dyn PlannerPersistenceV1>,
    indeterminate: bool,
}

impl PlannerStoreV1 {
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
        let mut lock_options = private_open_options();
        lock_options.read(true).write(true).create(true).truncate(false);
        let lock = lock_options.open(&lock_path)?;
        if !lock.metadata()?.is_file() {
            return Err(PlannerStoreError::NotRegular);
        }
        match File::try_lock(&lock) {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(PlannerStoreError::Busy),
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }

        let temp_path = root.join(TEMP_FILE);
        reject_existing_symlink(&temp_path)?;
        match fs::remove_file(&temp_path) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }

        let store_path = root.join(STORE_FILE);
        reject_existing_symlink(&store_path)?;
        if !store_path.exists() {
            persist_atomic(&root, initial_image(), persistence.as_ref())?;
        }
        let metadata = fs::symlink_metadata(&store_path)?;
        if metadata.file_type().is_symlink() {
            return Err(PlannerStoreError::Symlink);
        }
        if !metadata.is_file() {
            return Err(PlannerStoreError::NotRegular);
        }
        let mut file = File::open(&store_path)?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        if bytes.len() > MAX_STORE_BYTES {
            return Err(PlannerStoreError::StoreSize);
        }
        let parsed = parse_image(&bytes, true)?;
        if parsed.committed_len < bytes.len() {
            persistence.truncate(
                &store_path,
                u64::try_from(parsed.committed_len).map_err(|_| PlannerStoreError::StoreSize)?,
            )?;
        }
        let identities = identity_index(&parsed.entries)?;
        Ok(Self {
            root,
            lock,
            entries: parsed.entries,
            identities,
            committed_len: parsed.committed_len,
            persistence,
            indeterminate: false,
        })
    }

    #[must_use]
    pub const fn is_indeterminate(&self) -> bool {
        self.indeterminate
    }

    pub fn entries(&self) -> Result<&[PlannerStoreEntryV1], PlannerStoreError> {
        self.ensure_authoritative()?;
        Ok(&self.entries)
    }

    pub fn root_digest(&self) -> Result<Digest32, PlannerStoreError> {
        self.ensure_authoritative()?;
        Ok(self
            .entries
            .last()
            .map_or_else(|| Digest32::of_bytes(MAGIC), |entry| entry.frame_digest))
    }

    pub fn envelope(
        &self,
        identity_digest: Digest32,
    ) -> Result<Option<&PlannerStoreEntryV1>, PlannerStoreError> {
        self.ensure_authoritative()?;
        Ok(self
            .identities
            .get(&identity_digest)
            .and_then(|index| self.entries.get(*index)))
    }

    pub fn append_envelope(
        &mut self,
        envelope: PlannerCanonicalEnvelopeV1,
    ) -> Result<PlannerStoreEntryV1, PlannerStoreError> {
        self.ensure_authoritative()?;
        if let Some(index) = self.identities.get(&envelope.identity_digest).copied() {
            let existing = self
                .entries
                .get(index)
                .ok_or(PlannerStoreError::CorruptFrame)?;
            if existing.kind == envelope.kind
                && existing.semantic_digest == envelope.semantic_digest
                && existing.body_digest == envelope.body_digest
                && existing.canonical_body == envelope.canonical_body
            {
                return Ok(existing.clone());
            }
            return Err(PlannerStoreError::IdentityConflict);
        }
        if self.entries.len() >= MAX_RECORDS {
            return Err(PlannerStoreError::RecordLimit);
        }
        let sequence = u64::try_from(self.entries.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(PlannerStoreError::RecordLimit)?;
        let predecessor_frame_digest = self
            .entries
            .last()
            .map_or(Digest32::ZERO, |entry| entry.frame_digest);
        let entry = PlannerStoreEntryV1 {
            sequence,
            kind: envelope.kind,
            identity_digest: envelope.identity_digest,
            semantic_digest: envelope.semantic_digest,
            body_digest: envelope.body_digest,
            predecessor_frame_digest,
            frame_digest: Digest32::ZERO,
            canonical_body: envelope.canonical_body,
        };
        let (entry, frame) = encode_entry(entry)?;
        let next_len = self
            .committed_len
            .checked_add(frame.len())
            .filter(|length| *length <= MAX_STORE_BYTES)
            .ok_or(PlannerStoreError::StoreSize)?;
        let store_path = self.root.join(STORE_FILE);
        if self.persistence.append(&store_path, &frame).is_err() {
            self.indeterminate = true;
            return Err(PlannerStoreError::Indeterminate);
        }
        if self.persistence.sync_file(&store_path).is_err() {
            self.indeterminate = true;
            return Err(PlannerStoreError::Indeterminate);
        }
        let index = self.entries.len();
        self.identities.insert(entry.identity_digest, index);
        self.entries.push(entry.clone());
        self.committed_len = next_len;
        Ok(entry)
    }

    pub fn backup_bytes(&self) -> Result<Vec<u8>, PlannerStoreError> {
        self.ensure_authoritative()?;
        let mut file = File::open(self.root.join(STORE_FILE))?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        if bytes.len() != self.committed_len || bytes.len() > MAX_STORE_BYTES {
            return Err(PlannerStoreError::CorruptFrame);
        }
        parse_image(&bytes, false)?;
        Ok(bytes)
    }

    pub fn restore_backup(&mut self, bytes: &[u8]) -> Result<(), PlannerStoreError> {
        self.ensure_authoritative()?;
        if bytes.len() > MAX_STORE_BYTES {
            return Err(PlannerStoreError::StoreSize);
        }
        let parsed = parse_image(bytes, false)?;
        if parsed.committed_len != bytes.len()
            || parsed.entries.len() < self.entries.len()
            || parsed.entries[..self.entries.len()] != self.entries
        {
            return Err(PlannerStoreError::BackupRegression);
        }
        self.replace_image(bytes, parsed.entries)
    }

    pub fn compact_to_checkpoint<A: PlannerExternalAnchorV1 + ?Sized>(
        &mut self,
        checkpoint_identity_digest: Digest32,
        retained_state_digest: Digest32,
        retained_state_bytes: Vec<u8>,
        anchor: &mut A,
    ) -> Result<PlannerCheckpointReceiptV1, PlannerStoreError> {
        self.ensure_authoritative()?;
        if checkpoint_identity_digest.is_zero() || retained_state_digest.is_zero() {
            return Err(PlannerStoreError::EmptyDigest);
        }
        if retained_state_bytes.is_empty() || retained_state_bytes.len() > MAX_ENVELOPE_BYTES {
            return Err(PlannerStoreError::EnvelopeSize);
        }
        if Digest32::of_bytes(&retained_state_bytes) != retained_state_digest {
            return Err(PlannerStoreError::CorruptBodyDigest);
        }
        let previous_root_digest = self.root_digest()?;
        let proposal = PlannerCheckpointProposalV1 {
            previous_root_digest,
            checkpoint_identity_digest,
            retained_state_digest,
            retained_state_bytes: retained_state_bytes.clone(),
        };
        let external_anchor_digest = anchor.anchor(&proposal)?;
        if external_anchor_digest.is_zero() {
            return Err(PlannerStoreError::AnchorRejected);
        }
        let mut body = b"hepta.control.planner-checkpoint.v1".to_vec();
        body.extend_from_slice(previous_root_digest.as_array());
        body.extend_from_slice(retained_state_digest.as_array());
        body.extend_from_slice(external_anchor_digest.as_array());
        body.extend_from_slice(
            &u32::try_from(retained_state_bytes.len())
                .map_err(|_| PlannerStoreError::EnvelopeSize)?
                .to_be_bytes(),
        );
        body.extend_from_slice(&retained_state_bytes);
        let semantic_digest = Digest32::of_bytes(&body);
        let envelope = PlannerCanonicalEnvelopeV1::new(
            PlannerStoreRecordKindV1::Checkpoint,
            checkpoint_identity_digest,
            semantic_digest,
            body,
        )?;
        let entry = entry_from_envelope(1, Digest32::ZERO, envelope)?;
        let (entry, frame) = encode_entry(entry)?;
        let mut image = initial_image();
        image.extend_from_slice(&frame);
        self.replace_image(&image, vec![entry.clone()])?;
        Ok(PlannerCheckpointReceiptV1 {
            previous_root_digest,
            checkpoint_identity_digest,
            retained_state_digest,
            external_anchor_digest,
            checkpoint_frame_digest: entry.frame_digest,
        })
    }

    pub fn requires_compaction(
        &self,
        maximum_records: usize,
        maximum_bytes: usize,
    ) -> Result<bool, PlannerStoreError> {
        self.ensure_authoritative()?;
        Ok(self.entries.len() > maximum_records || self.committed_len > maximum_bytes)
    }

    pub fn migrate_from_legacy_journal(
        root: impl AsRef<Path>,
        legacy: &PlannerJournalV1,
        envelopes: Vec<PlannerCanonicalEnvelopeV1>,
    ) -> Result<Self, PlannerStoreError> {
        let mut by_identity = BTreeMap::new();
        for envelope in envelopes {
            if by_identity
                .insert(envelope.identity_digest, envelope)
                .is_some()
            {
                return Err(PlannerStoreError::IdentityConflict);
            }
        }
        let mut store = Self::open(root)?;
        if !store.entries()?.is_empty() {
            return Err(PlannerStoreError::MigrationMismatch);
        }
        for legacy_entry in legacy.entries() {
            let envelope = by_identity
                .remove(&legacy_entry.identity_digest)
                .ok_or(PlannerStoreError::MigrationMismatch)?;
            if envelope.kind != map_legacy_kind(legacy_entry.kind)
                || envelope.semantic_digest != legacy_entry.payload_digest
            {
                return Err(PlannerStoreError::MigrationMismatch);
            }
            store.append_envelope(envelope)?;
        }
        if !by_identity.is_empty() {
            return Err(PlannerStoreError::MigrationMismatch);
        }
        Ok(store)
    }

    fn replace_image(
        &mut self,
        bytes: &[u8],
        entries: Vec<PlannerStoreEntryV1>,
    ) -> Result<(), PlannerStoreError> {
        let identities = identity_index(&entries)?;
        match persist_atomic(&self.root, bytes.to_vec(), self.persistence.as_ref()) {
            Ok(()) => {
                self.entries = entries;
                self.identities = identities;
                self.committed_len = bytes.len();
                Ok(())
            }
            Err(PlannerStoreError::Indeterminate) => {
                self.indeterminate = true;
                Err(PlannerStoreError::Indeterminate)
            }
            Err(error) => Err(error),
        }
    }

    fn ensure_authoritative(&self) -> Result<(), PlannerStoreError> {
        if self.indeterminate {
            Err(PlannerStoreError::Indeterminate)
        } else {
            Ok(())
        }
    }
}

impl Drop for PlannerStoreV1 {
    fn drop(&mut self) {
        let _ = File::unlock(&self.lock);
    }
}

struct ParsedImage {
    entries: Vec<PlannerStoreEntryV1>,
    committed_len: usize,
}

fn initial_image() -> Vec<u8> {
    let mut bytes = MAGIC.to_vec();
    bytes.extend_from_slice(&STORE_SCHEMA.to_be_bytes());
    bytes
}

fn entry_from_envelope(
    sequence: u64,
    predecessor_frame_digest: Digest32,
    envelope: PlannerCanonicalEnvelopeV1,
) -> Result<PlannerStoreEntryV1, PlannerStoreError> {
    if sequence == 0 {
        return Err(PlannerStoreError::CorruptSequence);
    }
    Ok(PlannerStoreEntryV1 {
        sequence,
        kind: envelope.kind,
        identity_digest: envelope.identity_digest,
        semantic_digest: envelope.semantic_digest,
        body_digest: envelope.body_digest,
        predecessor_frame_digest,
        frame_digest: Digest32::ZERO,
        canonical_body: envelope.canonical_body,
    })
}

fn encode_entry(
    mut entry: PlannerStoreEntryV1,
) -> Result<(PlannerStoreEntryV1, Vec<u8>), PlannerStoreError> {
    if entry.identity_digest.is_zero()
        || entry.semantic_digest.is_zero()
        || entry.body_digest.is_zero()
        || entry.canonical_body.is_empty()
        || entry.canonical_body.len() > MAX_ENVELOPE_BYTES
        || Digest32::of_bytes(&entry.canonical_body) != entry.body_digest
    {
        return Err(PlannerStoreError::CorruptBodyDigest);
    }
    let mut payload = Vec::with_capacity(FIXED_FRAME_PAYLOAD_BYTES + entry.canonical_body.len());
    payload.extend_from_slice(&entry.sequence.to_be_bytes());
    payload.push(entry.kind.tag());
    payload.extend_from_slice(entry.identity_digest.as_array());
    payload.extend_from_slice(entry.semantic_digest.as_array());
    payload.extend_from_slice(entry.body_digest.as_array());
    payload.extend_from_slice(entry.predecessor_frame_digest.as_array());
    payload.extend_from_slice(
        &u32::try_from(entry.canonical_body.len())
            .map_err(|_| PlannerStoreError::EnvelopeSize)?
            .to_be_bytes(),
    );
    payload.extend_from_slice(&entry.canonical_body);
    let mut digest_material = b"hepta.control.planner-store-frame.v1".to_vec();
    digest_material.extend_from_slice(&payload);
    entry.frame_digest = Digest32::of_bytes(&digest_material);
    let mut frame = Vec::with_capacity(8 + payload.len() + 32);
    frame.extend_from_slice(FRAME_MAGIC);
    frame.extend_from_slice(
        &u32::try_from(payload.len())
            .map_err(|_| PlannerStoreError::EnvelopeSize)?
            .to_be_bytes(),
    );
    frame.extend_from_slice(&payload);
    frame.extend_from_slice(entry.frame_digest.as_array());
    Ok((entry, frame))
}

fn parse_image(bytes: &[u8], recover_partial_tail: bool) -> Result<ParsedImage, PlannerStoreError> {
    let header_len = MAGIC.len() + 4;
    if bytes.len() < header_len || &bytes[..MAGIC.len()] != MAGIC {
        return Err(PlannerStoreError::CorruptHeader);
    }
    let schema = u32::from_be_bytes(
        bytes[MAGIC.len()..header_len]
            .try_into()
            .map_err(|_| PlannerStoreError::CorruptHeader)?,
    );
    if schema != STORE_SCHEMA {
        return Err(PlannerStoreError::CorruptHeader);
    }
    let mut entries = Vec::new();
    let mut identities = BTreeMap::new();
    let mut offset = header_len;
    let mut predecessor = Digest32::ZERO;
    while offset < bytes.len() {
        let frame_start = offset;
        if bytes.len() - offset < 8 {
            if recover_partial_tail {
                return Ok(ParsedImage {
                    entries,
                    committed_len: frame_start,
                });
            }
            return Err(PlannerStoreError::CorruptFrame);
        }
        if &bytes[offset..offset + 4] != FRAME_MAGIC {
            return Err(PlannerStoreError::CorruptFrame);
        }
        offset += 4;
        let payload_len = u32::from_be_bytes(
            bytes[offset..offset + 4]
                .try_into()
                .map_err(|_| PlannerStoreError::CorruptFrame)?,
        ) as usize;
        offset += 4;
        if payload_len < FIXED_FRAME_PAYLOAD_BYTES
            || payload_len > FIXED_FRAME_PAYLOAD_BYTES + MAX_ENVELOPE_BYTES
        {
            return Err(PlannerStoreError::CorruptFrame);
        }
        let frame_end = offset
            .checked_add(payload_len)
            .and_then(|value| value.checked_add(32))
            .ok_or(PlannerStoreError::StoreSize)?;
        if frame_end > bytes.len() {
            if recover_partial_tail {
                return Ok(ParsedImage {
                    entries,
                    committed_len: frame_start,
                });
            }
            return Err(PlannerStoreError::CorruptFrame);
        }
        let payload = &bytes[offset..offset + payload_len];
        let stored_frame_digest = digest_from_slice(&bytes[offset + payload_len..frame_end])?;
        let mut digest_material = b"hepta.control.planner-store-frame.v1".to_vec();
        digest_material.extend_from_slice(payload);
        if Digest32::of_bytes(&digest_material) != stored_frame_digest {
            return Err(PlannerStoreError::CorruptFrameDigest);
        }
        let entry = parse_payload(payload, stored_frame_digest)?;
        let expected_sequence = u64::try_from(entries.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(PlannerStoreError::RecordLimit)?;
        if entry.sequence != expected_sequence {
            return Err(PlannerStoreError::CorruptSequence);
        }
        if entry.predecessor_frame_digest != predecessor {
            return Err(PlannerStoreError::CorruptPredecessor);
        }
        if identities
            .insert(entry.identity_digest, entries.len())
            .is_some()
        {
            return Err(PlannerStoreError::DuplicateSerializedIdentity);
        }
        predecessor = entry.frame_digest;
        entries.push(entry);
        if entries.len() > MAX_RECORDS {
            return Err(PlannerStoreError::RecordLimit);
        }
        offset = frame_end;
    }
    Ok(ParsedImage {
        entries,
        committed_len: offset,
    })
}

fn parse_payload(
    payload: &[u8],
    frame_digest: Digest32,
) -> Result<PlannerStoreEntryV1, PlannerStoreError> {
    let mut offset = 0;
    let sequence = read_u64(payload, &mut offset)?;
    let kind = PlannerStoreRecordKindV1::from_tag(read_u8(payload, &mut offset)?)?;
    let identity_digest = read_digest(payload, &mut offset)?;
    let semantic_digest = read_digest(payload, &mut offset)?;
    let body_digest = read_digest(payload, &mut offset)?;
    let predecessor_frame_digest = read_digest(payload, &mut offset)?;
    let body_len = read_u32(payload, &mut offset)? as usize;
    if body_len == 0 || body_len > MAX_ENVELOPE_BYTES {
        return Err(PlannerStoreError::EnvelopeSize);
    }
    let end = offset
        .checked_add(body_len)
        .ok_or(PlannerStoreError::EnvelopeSize)?;
    let canonical_body = payload
        .get(offset..end)
        .ok_or(PlannerStoreError::CorruptFrame)?
        .to_vec();
    if end != payload.len() || Digest32::of_bytes(&canonical_body) != body_digest {
        return Err(PlannerStoreError::CorruptBodyDigest);
    }
    if identity_digest.is_zero() || semantic_digest.is_zero() || body_digest.is_zero() {
        return Err(PlannerStoreError::EmptyDigest);
    }
    Ok(PlannerStoreEntryV1 {
        sequence,
        kind,
        identity_digest,
        semantic_digest,
        body_digest,
        predecessor_frame_digest,
        frame_digest,
        canonical_body,
    })
}

fn identity_index(
    entries: &[PlannerStoreEntryV1],
) -> Result<BTreeMap<Digest32, usize>, PlannerStoreError> {
    let mut identities = BTreeMap::new();
    for (index, entry) in entries.iter().enumerate() {
        if identities.insert(entry.identity_digest, index).is_some() {
            return Err(PlannerStoreError::DuplicateSerializedIdentity);
        }
    }
    Ok(identities)
}

fn persist_atomic(
    root: &Path,
    bytes: Vec<u8>,
    persistence: &dyn PlannerPersistenceV1,
) -> Result<(), PlannerStoreError> {
    if bytes.len() > MAX_STORE_BYTES {
        return Err(PlannerStoreError::StoreSize);
    }
    parse_image(&bytes, false)?;
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

fn reject_existing_symlink(path: &Path) -> Result<(), PlannerStoreError> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => Err(PlannerStoreError::Symlink),
        Ok(_) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn private_open_options() -> OpenOptions {
    let mut options = OpenOptions::new();
    #[cfg(unix)]
    options.mode(0o600);
    options
}

fn map_legacy_kind(kind: PlannerJournalKindV1) -> PlannerStoreRecordKindV1 {
    match kind {
        PlannerJournalKindV1::Snapshot => PlannerStoreRecordKindV1::Snapshot,
        PlannerJournalKindV1::Decision => PlannerStoreRecordKindV1::Decision,
        PlannerJournalKindV1::SelectedPlan => PlannerStoreRecordKindV1::SelectedPlan,
        PlannerJournalKindV1::Revocation => PlannerStoreRecordKindV1::Revocation,
    }
}

fn read_u8(bytes: &[u8], offset: &mut usize) -> Result<u8, PlannerStoreError> {
    let value = *bytes.get(*offset).ok_or(PlannerStoreError::CorruptFrame)?;
    *offset += 1;
    Ok(value)
}

fn read_u32(bytes: &[u8], offset: &mut usize) -> Result<u32, PlannerStoreError> {
    let end = offset
        .checked_add(4)
        .ok_or(PlannerStoreError::CorruptFrame)?;
    let value = u32::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(PlannerStoreError::CorruptFrame)?
            .try_into()
            .map_err(|_| PlannerStoreError::CorruptFrame)?,
    );
    *offset = end;
    Ok(value)
}

fn read_u64(bytes: &[u8], offset: &mut usize) -> Result<u64, PlannerStoreError> {
    let end = offset
        .checked_add(8)
        .ok_or(PlannerStoreError::CorruptFrame)?;
    let value = u64::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(PlannerStoreError::CorruptFrame)?
            .try_into()
            .map_err(|_| PlannerStoreError::CorruptFrame)?,
    );
    *offset = end;
    Ok(value)
}

fn read_digest(bytes: &[u8], offset: &mut usize) -> Result<Digest32, PlannerStoreError> {
    let end = offset
        .checked_add(32)
        .ok_or(PlannerStoreError::CorruptFrame)?;
    let value = digest_from_slice(
        bytes
            .get(*offset..end)
            .ok_or(PlannerStoreError::CorruptFrame)?,
    )?;
    *offset = end;
    Ok(value)
}

fn digest_from_slice(bytes: &[u8]) -> Result<Digest32, PlannerStoreError> {
    let array: [u8; 32] = bytes
        .try_into()
        .map_err(|_| PlannerStoreError::CorruptFrame)?;
    Ok(Digest32::from_array(array))
}

#[cfg(test)]
#[path = "planner_store_tests.rs"]
mod tests;
