//! Bounded, single-writer planner storage with an independently retained head.
//!
//! A checkpoint anchor is a trusted owner port, not a caller-supplied checksum.
//! Successful append means frame sync and anchor compare-and-swap completed.
//! An uncertain append fences this handle; reopening reconciles the anchor.
//! This module stores decision evidence; it does not authorize its execution.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

const MAGIC: &[u8; 8] = b"HCPSTR01";
const HEADER_BYTES: usize = 44;
const FIXED_FRAME_BYTES: usize = 8 + 1 + 32 + 32 + 32;
pub const MAX_PLANNER_STORE_BODY_BYTES: usize = 1024 * 1024;
pub const MAX_PLANNER_STORE_BYTES: usize = 64 * 1024 * 1024;
pub const MAX_PLANNER_STORE_RECORDS: usize = 4096;

/// Length-prefixed canonical storage envelope. Each component is the complete
/// byte representation under `codec_digest`, not its hash. The selected owner
/// codec verifies component semantics; storage does not recompute NDU utility.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerDecisionEnvelopeV1 {
    pub codec_digest: Digest32,
    pub snapshot: Vec<u8>,
    pub prepared_plan: Vec<u8>,
    pub ndu_evaluation: Vec<u8>,
    pub plan_receipt: Vec<u8>,
}

impl PlannerDecisionEnvelopeV1 {
    pub fn encode(&self) -> Result<Vec<u8>, PlannerStoreError> {
        if self.codec_digest.is_zero() {
            return Err(PlannerStoreError::InvalidIdentity);
        }
        let fields = [
            &self.snapshot,
            &self.prepared_plan,
            &self.ndu_evaluation,
            &self.plan_receipt,
        ];
        let mut total = 40_usize;
        for field in fields {
            if field.is_empty() {
                return Err(PlannerStoreError::Corrupt);
            }
            total = total
                .checked_add(4)
                .and_then(|size| size.checked_add(field.len()))
                .ok_or(PlannerStoreError::LimitExceeded)?;
        }
        if total > MAX_PLANNER_STORE_BODY_BYTES {
            return Err(PlannerStoreError::LimitExceeded);
        }
        let mut bytes = b"HCPDEC01".to_vec();
        bytes.extend_from_slice(self.codec_digest.as_array());
        for field in fields {
            let length =
                u32::try_from(field.len()).map_err(|_| PlannerStoreError::LimitExceeded)?;
            bytes.extend_from_slice(&length.to_be_bytes());
            bytes.extend_from_slice(field);
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PlannerStoreError> {
        if bytes.len() > MAX_PLANNER_STORE_BODY_BYTES
            || bytes.get(..8) != Some(b"HCPDEC01".as_slice())
        {
            return Err(PlannerStoreError::Corrupt);
        }
        let codec_digest = digest_at(bytes, 8)?;
        if codec_digest.is_zero() {
            return Err(PlannerStoreError::InvalidIdentity);
        }
        let mut offset = 40_usize;
        let mut field = || -> Result<Vec<u8>, PlannerStoreError> {
            let prefix_end = offset.checked_add(4).ok_or(PlannerStoreError::Corrupt)?;
            let prefix = bytes
                .get(offset..prefix_end)
                .ok_or(PlannerStoreError::Corrupt)?;
            let length = u32::from_be_bytes(
                prefix.try_into().map_err(|_| PlannerStoreError::Corrupt)?,
            ) as usize;
            if length == 0 {
                return Err(PlannerStoreError::Corrupt);
            }
            let end = prefix_end
                .checked_add(length)
                .ok_or(PlannerStoreError::Corrupt)?;
            let result = bytes
                .get(prefix_end..end)
                .ok_or(PlannerStoreError::Corrupt)?
                .to_vec();
            offset = end;
            Ok(result)
        };
        let result = Self {
            codec_digest,
            snapshot: field()?,
            prepared_plan: field()?,
            ndu_evaluation: field()?,
            plan_receipt: field()?,
        };
        if offset != bytes.len() {
            return Err(PlannerStoreError::Corrupt);
        }
        Ok(result)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlannerStoreCheckpointV1 {
    pub store_id: Digest32,
    pub sequence: u64,
    pub head_digest: Digest32,
}

/// Implementations MUST authenticate the external owner, durably compare and
/// swap the entire checkpoint, and never return an older checkpoint after a
/// successful advance. In-memory test doubles are not production anchors.
pub trait PlannerCheckpointAnchorV1 {
    fn load(&mut self, store_id: Digest32) -> Result<PlannerStoreCheckpointV1, PlannerStoreError>;
    fn advance(
        &mut self,
        expected: PlannerStoreCheckpointV1,
        next: PlannerStoreCheckpointV1,
    ) -> Result<(), PlannerStoreError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerStoreRecordKindV1 {
    Decision,
    Selected,
    Revoked,
    Observation,
}

impl PlannerStoreRecordKindV1 {
    fn tag(self) -> u8 {
        match self {
            Self::Decision => 0,
            Self::Selected => 1,
            Self::Revoked => 2,
            Self::Observation => 3,
        }
    }

    fn from_tag(value: u8) -> Result<Self, PlannerStoreError> {
        match value {
            0 => Ok(Self::Decision),
            1 => Ok(Self::Selected),
            2 => Ok(Self::Revoked),
            3 => Ok(Self::Observation),
            _ => Err(PlannerStoreError::Corrupt),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerStoreRecordV1 {
    pub sequence: u64,
    pub kind: PlannerStoreRecordKindV1,
    pub operation_digest: Digest32,
    pub decision_digest: Digest32,
    pub body: Vec<u8>,
    pub predecessor_digest: Digest32,
    pub record_digest: Digest32,
}

#[derive(Debug)]
pub enum PlannerStoreError {
    Io(io::Error),
    Busy,
    Fenced,
    UnsafePath,
    UnsupportedSchema,
    Corrupt,
    LimitExceeded,
    InvalidIdentity,
    IdentityConflict,
    DecisionNotRecorded,
    Revoked,
    AnchorUnavailable,
    AnchorMismatch,
    StaleBackup,
}

impl std::fmt::Display for PlannerStoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(f, "planner store I/O: {}", error.kind()),
            other => write!(f, "{other:?}"),
        }
    }
}

impl std::error::Error for PlannerStoreError {}

impl From<io::Error> for PlannerStoreError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

pub struct PlannerStoreV1<A: PlannerCheckpointAnchorV1> {
    root: PathBuf,
    _writer_lock: File,
    log: File,
    anchor: A,
    checkpoint: PlannerStoreCheckpointV1,
    records: Vec<PlannerStoreRecordV1>,
    identities: BTreeMap<Digest32, usize>,
    decisions: BTreeSet<Digest32>,
    revoked: BTreeSet<Digest32>,
    selected: Option<Digest32>,
    committed_bytes: u64,
    fenced: bool,
}

impl<A: PlannerCheckpointAnchorV1> PlannerStoreV1<A> {
    /// The owner provisions the private directory and genesis anchor first.
    /// No missing file, unknown schema or failed anchor is silently reset.
    pub fn create(
        root: &Path,
        store_id: Digest32,
        mut anchor: A,
    ) -> Result<Self, PlannerStoreError> {
        let lock = lock_root(root)?;
        let checkpoint = validate_checkpoint(anchor.load(store_id)?, store_id)?;
        if checkpoint.sequence != 0 || !checkpoint.head_digest.is_zero() {
            return Err(PlannerStoreError::AnchorMismatch);
        }
        let mut log = private_options()
            .read(true)
            .write(true)
            .create_new(true)
            .open(root.join("planner.log"))?;
        log.write_all(&header(store_id))?;
        log.sync_all()?;
        sync_directory(root)?;
        Self::from_committed(root, lock, log, anchor, checkpoint, &header(store_id))
    }

    pub fn open(
        root: &Path,
        store_id: Digest32,
        mut anchor: A,
    ) -> Result<Self, PlannerStoreError> {
        let lock = lock_root(root)?;
        let checkpoint = validate_checkpoint(anchor.load(store_id)?, store_id)?;
        let path = root.join("planner.log");
        require_regular_file(&path)?;
        let mut log = private_options().read(true).write(true).open(path)?;
        let bytes = read_bounded(&mut log)?;
        let store = Self::from_committed(root, lock, log, anchor, checkpoint, &bytes)?;
        if store.committed_bytes != bytes.len() as u64 {
            // Only unacknowledged tail bytes beyond the authenticated head may
            // be discarded. Truncation of an acknowledged frame rejects open.
            store.log.set_len(store.committed_bytes)?;
            store.log.sync_all()?;
        }
        Ok(store)
    }

    fn from_committed(
        root: &Path,
        lock: File,
        log: File,
        anchor: A,
        checkpoint: PlannerStoreCheckpointV1,
        bytes: &[u8],
    ) -> Result<Self, PlannerStoreError> {
        if bytes.len() < HEADER_BYTES || &bytes[..8] != MAGIC {
            return Err(PlannerStoreError::Corrupt);
        }
        if bytes[8..12] != 1_u32.to_be_bytes() {
            return Err(PlannerStoreError::UnsupportedSchema);
        }
        if bytes[12..44] != *checkpoint.store_id.as_array() {
            return Err(PlannerStoreError::AnchorMismatch);
        }
        let mut result = Self {
            root: root.to_path_buf(),
            _writer_lock: lock,
            log,
            anchor,
            checkpoint,
            records: Vec::new(),
            identities: BTreeMap::new(),
            decisions: BTreeSet::new(),
            revoked: BTreeSet::new(),
            selected: None,
            committed_bytes: HEADER_BYTES as u64,
            fenced: false,
        };
        let mut offset = HEADER_BYTES;
        let mut predecessor = Digest32::ZERO;
        for sequence in 1..=checkpoint.sequence {
            let record = decode_frame(bytes, &mut offset, checkpoint.store_id)?;
            if record.sequence != sequence || record.predecessor_digest != predecessor {
                return Err(PlannerStoreError::Corrupt);
            }
            result.validate_record(&record)?;
            predecessor = record.record_digest;
            result.apply_record(record);
        }
        if predecessor != checkpoint.head_digest {
            return Err(PlannerStoreError::AnchorMismatch);
        }
        result.committed_bytes = offset as u64;
        Ok(result)
    }

    pub fn checkpoint(&self) -> PlannerStoreCheckpointV1 {
        self.checkpoint
    }

    pub fn records(&self) -> &[PlannerStoreRecordV1] {
        &self.records
    }

    pub fn selected_decision(&self) -> Option<Digest32> {
        self.selected
    }

    /// Store a complete versioned envelope as the Decision body, not just its
    /// digest. The owner remains responsible for semantic envelope validation.
    /// Other records carry their exact canonical evidence bodies as well.
    pub fn append(
        &mut self,
        kind: PlannerStoreRecordKindV1,
        operation_digest: Digest32,
        decision_digest: Digest32,
        body: &[u8],
    ) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
        if self.fenced {
            return Err(PlannerStoreError::Fenced);
        }
        if body.len() > MAX_PLANNER_STORE_BODY_BYTES || body.is_empty() {
            return Err(PlannerStoreError::LimitExceeded);
        }
        if let Some(index) = self.identities.get(&operation_digest) {
            let existing = &self.records[*index];
            if existing.kind == kind
                && existing.decision_digest == decision_digest
                && existing.body == body
            {
                return Ok(existing.clone());
            }
            return Err(PlannerStoreError::IdentityConflict);
        }
        if self.records.len() >= MAX_PLANNER_STORE_RECORDS {
            return Err(PlannerStoreError::LimitExceeded);
        }
        let mut record = PlannerStoreRecordV1 {
            sequence: self
                .checkpoint
                .sequence
                .checked_add(1)
                .ok_or(PlannerStoreError::LimitExceeded)?,
            kind,
            operation_digest,
            decision_digest,
            body: body.to_vec(),
            predecessor_digest: self.checkpoint.head_digest,
            record_digest: Digest32::ZERO,
        };
        self.validate_record(&record)?;
        let frame = encode_frame(&mut record, self.checkpoint.store_id)?;
        let next_length = self
            .committed_bytes
            .checked_add(frame.len() as u64)
            .ok_or(PlannerStoreError::LimitExceeded)?;
        if next_length > MAX_PLANNER_STORE_BYTES as u64 {
            return Err(PlannerStoreError::LimitExceeded);
        }
        let next = PlannerStoreCheckpointV1 {
            store_id: self.checkpoint.store_id,
            sequence: record.sequence,
            head_digest: record.record_digest,
        };
        // Fence before the first mutating operation. I/O and anchor errors may
        // represent an unknown commit outcome, so no blind append retry follows.
        self.fenced = true;
        self.log.seek(SeekFrom::Start(self.committed_bytes))?;
        self.log.write_all(&frame)?;
        self.log.sync_all()?;
        self.anchor.advance(self.checkpoint, next)?;
        self.checkpoint = next;
        self.committed_bytes = next_length;
        self.apply_record(record.clone());
        self.fenced = false;
        Ok(record)
    }

    /// Byte-exact, immutable, fully synced backup at the current anchored head.
    /// Existing destinations are never overwritten.
    pub fn backup(
        &mut self,
        destination: &Path,
    ) -> Result<PlannerStoreCheckpointV1, PlannerStoreError> {
        if self.fenced {
            return Err(PlannerStoreError::Fenced);
        }
        if self.anchor.load(self.checkpoint.store_id)? != self.checkpoint {
            self.fenced = true;
            return Err(PlannerStoreError::AnchorMismatch);
        }
        let parent = destination.parent().ok_or(PlannerStoreError::UnsafePath)?;
        require_private_directory(parent)?;
        let mut output = private_options()
            .write(true)
            .create_new(true)
            .open(destination)?;
        self.log.seek(SeekFrom::Start(0))?;
        let copied = io::copy(&mut (&mut self.log).take(self.committed_bytes), &mut output)?;
        if copied != self.committed_bytes {
            return Err(PlannerStoreError::Corrupt);
        }
        output.sync_all()?;
        sync_directory(parent)?;
        Ok(self.checkpoint)
    }

    /// Atomically republish the exact committed stream after verifying its
    /// current external anchor. This preserves all identities and revocations;
    /// it does not pretend that dropping history is a safe retention policy.
    pub fn checkpoint_file(&mut self) -> Result<(), PlannerStoreError> {
        if self.fenced {
            return Err(PlannerStoreError::Fenced);
        }
        let temporary = self.root.join("planner.checkpoint.tmp");
        let checkpoint = self.backup(&temporary)?;
        self.fenced = true;
        if self.anchor.load(checkpoint.store_id)? != checkpoint {
            return Err(PlannerStoreError::AnchorMismatch);
        }
        fs::rename(&temporary, self.root.join("planner.log"))?;
        sync_directory(&self.root)?;
        self.log = private_options()
            .read(true)
            .write(true)
            .open(self.root.join("planner.log"))?;
        self.fenced = false;
        Ok(())
    }

    /// Restore only to an empty, owner-provisioned directory, and only when the
    /// backup covers the CURRENT authenticated checkpoint. A stale backup may
    /// not resurrect an older selection. The anchor is never rolled backwards.
    pub fn restore(
        root: &Path,
        store_id: Digest32,
        backup: &Path,
        mut anchor: A,
    ) -> Result<Self, PlannerStoreError> {
        let lock = lock_root(root)?;
        if root.join("planner.log").try_exists()? {
            return Err(PlannerStoreError::UnsafePath);
        }
        let checkpoint = validate_checkpoint(anchor.load(store_id)?, store_id)?;
        require_regular_file(backup)?;
        let mut input = File::open(backup)?;
        let bytes = read_bounded(&mut input)?;
        let temporary = root.join("planner.restore.tmp");
        let mut log = private_options()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        // Parse and replay every committed record before publishing a path.
        let mut store =
            Self::from_committed(root, lock, log.try_clone()?, anchor, checkpoint, &bytes)
                .map_err(|_| PlannerStoreError::StaleBackup)?;
        if store.committed_bytes != bytes.len() as u64 {
            return Err(PlannerStoreError::StaleBackup);
        }
        log.write_all(&bytes)?;
        log.sync_all()?;
        if store.anchor.load(store_id)? != checkpoint {
            return Err(PlannerStoreError::AnchorMismatch);
        }
        fs::rename(&temporary, root.join("planner.log"))?;
        sync_directory(root)?;
        store.log = log;
        Ok(store)
    }

    fn validate_record(&self, record: &PlannerStoreRecordV1) -> Result<(), PlannerStoreError> {
        if record.operation_digest.is_zero() || record.decision_digest.is_zero() {
            return Err(PlannerStoreError::InvalidIdentity);
        }
        if record.body.is_empty() || record.body.len() > MAX_PLANNER_STORE_BODY_BYTES {
            return Err(PlannerStoreError::LimitExceeded);
        }
        if self.identities.contains_key(&record.operation_digest) {
            return Err(PlannerStoreError::IdentityConflict);
        }
        if record.kind == PlannerStoreRecordKindV1::Decision {
            PlannerDecisionEnvelopeV1::decode(&record.body)?;
        }
        match record.kind {
            PlannerStoreRecordKindV1::Decision
                if self.decisions.contains(&record.decision_digest) =>
            {
                Err(PlannerStoreError::IdentityConflict)
            }
            PlannerStoreRecordKindV1::Selected if self.revoked.contains(&record.decision_digest) => {
                Err(PlannerStoreError::Revoked)
            }
            PlannerStoreRecordKindV1::Selected
                if !self.decisions.contains(&record.decision_digest) =>
            {
                Err(PlannerStoreError::DecisionNotRecorded)
            }
            _ => Ok(()),
        }
    }

    fn apply_record(&mut self, record: PlannerStoreRecordV1) {
        match record.kind {
            PlannerStoreRecordKindV1::Decision => {
                self.decisions.insert(record.decision_digest);
            }
            PlannerStoreRecordKindV1::Selected => {
                self.selected = Some(record.decision_digest);
            }
            PlannerStoreRecordKindV1::Revoked => {
                self.revoked.insert(record.decision_digest);
                if self.selected == Some(record.decision_digest) {
                    self.selected = None;
                }
            }
            PlannerStoreRecordKindV1::Observation => {}
        }
        self.identities
            .insert(record.operation_digest, self.records.len());
        self.records.push(record);
    }
}

fn validate_checkpoint(
    checkpoint: PlannerStoreCheckpointV1,
    expected_id: Digest32,
) -> Result<PlannerStoreCheckpointV1, PlannerStoreError> {
    if expected_id.is_zero()
        || checkpoint.store_id != expected_id
        || checkpoint.sequence > MAX_PLANNER_STORE_RECORDS as u64
        || (checkpoint.sequence == 0) != checkpoint.head_digest.is_zero()
    {
        return Err(PlannerStoreError::AnchorMismatch);
    }
    Ok(checkpoint)
}

fn header(id: Digest32) -> Vec<u8> {
    let mut bytes = MAGIC.to_vec();
    bytes.extend_from_slice(&1_u32.to_be_bytes());
    bytes.extend_from_slice(id.as_array());
    bytes
}

fn encode_frame(
    record: &mut PlannerStoreRecordV1,
    store: Digest32,
) -> Result<Vec<u8>, PlannerStoreError> {
    let mut payload = record.sequence.to_be_bytes().to_vec();
    payload.push(record.kind.tag());
    payload.extend_from_slice(record.operation_digest.as_array());
    payload.extend_from_slice(record.decision_digest.as_array());
    payload.extend_from_slice(record.predecessor_digest.as_array());
    payload.extend_from_slice(&record.body);
    record.record_digest = frame_digest(store, &payload);
    let length = u32::try_from(payload.len()).map_err(|_| PlannerStoreError::LimitExceeded)?;
    let mut frame = length.to_be_bytes().to_vec();
    frame.extend_from_slice(&(!length).to_be_bytes());
    frame.extend_from_slice(&payload);
    frame.extend_from_slice(record.record_digest.as_array());
    Ok(frame)
}

fn frame_digest(store: Digest32, payload: &[u8]) -> Digest32 {
    let mut material = b"hepta.control.planner-store-frame.v1\0".to_vec();
    material.extend_from_slice(store.as_array());
    material.extend_from_slice(payload);
    Digest32::of_bytes(&material)
}

fn decode_frame(
    bytes: &[u8],
    offset: &mut usize,
    store: Digest32,
) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
    let prefix_end = offset.checked_add(8).ok_or(PlannerStoreError::Corrupt)?;
    let prefix = bytes
        .get(*offset..prefix_end)
        .ok_or(PlannerStoreError::Corrupt)?;
    let length = u32::from_be_bytes(
        prefix[..4]
            .try_into()
            .map_err(|_| PlannerStoreError::Corrupt)?,
    );
    let complement = u32::from_be_bytes(
        prefix[4..]
            .try_into()
            .map_err(|_| PlannerStoreError::Corrupt)?,
    );
    if complement != !length
        || length as usize <= FIXED_FRAME_BYTES
        || length as usize > FIXED_FRAME_BYTES + MAX_PLANNER_STORE_BODY_BYTES
    {
        return Err(PlannerStoreError::Corrupt);
    }
    let end = prefix_end
        .checked_add(length as usize)
        .ok_or(PlannerStoreError::Corrupt)?;
    let digest_end = end.checked_add(32).ok_or(PlannerStoreError::Corrupt)?;
    let payload = bytes
        .get(prefix_end..end)
        .ok_or(PlannerStoreError::Corrupt)?;
    let digest = digest_at(bytes, end)?;
    if digest != frame_digest(store, payload) {
        return Err(PlannerStoreError::Corrupt);
    }
    let sequence = u64::from_be_bytes(
        payload[..8]
            .try_into()
            .map_err(|_| PlannerStoreError::Corrupt)?,
    );
    let record = PlannerStoreRecordV1 {
        sequence,
        kind: PlannerStoreRecordKindV1::from_tag(payload[8])?,
        operation_digest: digest_at(payload, 9)?,
        decision_digest: digest_at(payload, 41)?,
        predecessor_digest: digest_at(payload, 73)?,
        body: payload[FIXED_FRAME_BYTES..].to_vec(),
        record_digest: digest,
    };
    *offset = digest_end;
    Ok(record)
}

fn digest_at(bytes: &[u8], offset: usize) -> Result<Digest32, PlannerStoreError> {
    let end = offset.checked_add(32).ok_or(PlannerStoreError::Corrupt)?;
    let value = bytes.get(offset..end).ok_or(PlannerStoreError::Corrupt)?;
    Ok(Digest32::from_array(
        value.try_into().map_err(|_| PlannerStoreError::Corrupt)?,
    ))
}

fn read_bounded(file: &mut File) -> Result<Vec<u8>, PlannerStoreError> {
    if file.metadata()?.len() > MAX_PLANNER_STORE_BYTES as u64 {
        return Err(PlannerStoreError::LimitExceeded);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    file.take(MAX_PLANNER_STORE_BYTES as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_PLANNER_STORE_BYTES {
        return Err(PlannerStoreError::LimitExceeded);
    }
    Ok(bytes)
}

fn private_options() -> OpenOptions {
    let mut options = OpenOptions::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options
}

fn require_private_directory(path: &Path) -> Result<(), PlannerStoreError> {
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(PlannerStoreError::UnsafePath);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(PlannerStoreError::UnsafePath);
        }
    }
    Ok(())
}

fn require_regular_file(path: &Path) -> Result<(), PlannerStoreError> {
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(PlannerStoreError::UnsafePath);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;
        if metadata.nlink() != 1 || metadata.permissions().mode() & 0o077 != 0 {
            return Err(PlannerStoreError::UnsafePath);
        }
    }
    Ok(())
}

fn lock_root(root: &Path) -> Result<File, PlannerStoreError> {
    require_private_directory(root)?;
    let path = root.join("planner.lock");
    let file = match private_options()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)
    {
        Ok(file) => {
            file.sync_all()?;
            sync_directory(root)?;
            file
        }
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
            require_regular_file(&path)?;
            private_options().read(true).write(true).open(path)?
        }
        Err(error) => return Err(error.into()),
    };
    match file.try_lock() {
        Ok(()) => Ok(file),
        Err(fs::TryLockError::WouldBlock) => Err(PlannerStoreError::Busy),
        Err(fs::TryLockError::Error(error)) => Err(error.into()),
    }
}

fn sync_directory(path: &Path) -> Result<(), PlannerStoreError> {
    File::open(path)?.sync_all()?;
    Ok(())
}
