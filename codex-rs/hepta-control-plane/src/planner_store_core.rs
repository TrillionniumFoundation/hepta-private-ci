//! Owner-local durable storage for complete planner decision envelopes.
//!
//! This store is authority-free. It persists canonical envelope bytes, detects
//! corruption, recovers a partial final frame, serializes one writer, and
//! publishes externally anchored checkpoints through same-directory atomic
//! replacement. Product activation still requires an owner-selected host and
//! independent qualification.

use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

const STORE_MAGIC: &[u8; 8] = b"HCPSTR01";
const CHECKPOINT_MAGIC: &[u8; 8] = b"HCPCPT01";
const SCHEMA_VERSION: u16 = 1;
const LOG_NAME: &str = "planner-store.v1.log";
const LOCK_NAME: &str = "planner-store.lock";
const CHECKPOINT_NAME: &str = "planner-checkpoint.v1";
const LOG_TEMP_NAME: &str = "planner-store.v1.log.tmp";
const CHECKPOINT_TEMP_NAME: &str = "planner-checkpoint.v1.tmp";
const FRAME_FIXED_BYTES: usize = 8 + 2 + 1 + 8 + 32 + 32 + 4 + 32;
const CHECKPOINT_BYTES: usize = 8 + 2 + 8 + 32 + 32 + 32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerStoreRecordKindV1 {
    Snapshot,
    Decision,
    Selection,
    Revocation,
    TerminalReceipt,
    Reconciliation,
}

impl PlannerStoreRecordKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Snapshot => 0,
            Self::Decision => 1,
            Self::Selection => 2,
            Self::Revocation => 3,
            Self::TerminalReceipt => 4,
            Self::Reconciliation => 5,
        }
    }

    fn from_tag(value: u8) -> Result<Self, PlannerStoreError> {
        match value {
            0 => Ok(Self::Snapshot),
            1 => Ok(Self::Decision),
            2 => Ok(Self::Selection),
            3 => Ok(Self::Revocation),
            4 => Ok(Self::TerminalReceipt),
            5 => Ok(Self::Reconciliation),
            _ => Err(PlannerStoreError::UnknownRecordKind(value)),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerStoreRecordV1 {
    pub sequence: u64,
    pub kind: PlannerStoreRecordKindV1,
    pub operation_identity_digest: Digest32,
    pub payload_digest: Digest32,
    pub envelope: Vec<u8>,
    pub record_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlannerStoreConfigV1 {
    pub maximum_records: usize,
    pub maximum_envelope_bytes: usize,
}

impl Default for PlannerStoreConfigV1 {
    fn default() -> Self {
        Self {
            maximum_records: 4_096,
            maximum_envelope_bytes: 1024 * 1024,
        }
    }
}

/// Deterministic one-shot crash and storage faults used by qualification.
/// Callers must treat every failpoint result as a simulated process crash and
/// reopen before issuing another operation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerStoreFailpointV1 {
    DiskFullBeforeFrameWrite,
    BeforeFrameWrite,
    AfterFrameWriteBeforeSync,
    AfterLogSyncBeforePublish,
    BeforeCheckpointRename,
    AfterCheckpointRenameBeforeDirectorySync,
    BeforeCompactionRename,
    AfterCompactionRenameBeforeDirectorySync,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerStoreCheckpointV1 {
    pub sequence: u64,
    pub store_digest: Digest32,
    pub external_anchor_digest: Digest32,
    pub checkpoint_digest: Digest32,
}

#[derive(Debug)]
pub enum PlannerStoreError {
    Io(String),
    Locked,
    CorruptLock,
    InvalidConfiguration,
    EmptyDigest(&'static str),
    RecordLimitExceeded,
    EnvelopeTooLarge { actual: usize, maximum: usize },
    IdentityConflict,
    CorruptHeader,
    UnsupportedSchemaVersion(u16),
    UnknownRecordKind(u8),
    CorruptSequence,
    CorruptRecordDigest,
    Truncated,
    CheckpointMismatch,
    Failpoint(PlannerStoreFailpointV1),
}

impl fmt::Display for PlannerStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlannerStoreError {}

impl From<std::io::Error> for PlannerStoreError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error.to_string())
    }
}

/// RAII owner lock. On Linux, a lock left by an exited process is reclaimed
/// only when the recorded PID/start-time pair is no longer current. On other
/// targets an existing lock fails closed.
struct PlannerWriterLockV1 {
    root: PathBuf,
    path: PathBuf,
    owner_token: String,
    _file: File,
}

impl PlannerWriterLockV1 {
    fn acquire(root: &Path) -> Result<Self, PlannerStoreError> {
        let path = root.join(LOCK_NAME);
        let owner_token = current_process_token()?;
        loop {
            match OpenOptions::new().create_new(true).write(true).open(&path) {
                Ok(mut file) => {
                    file.write_all(owner_token.as_bytes())?;
                    file.sync_all()?;
                    sync_directory(root)?;
                    return Ok(Self {
                        root: root.to_path_buf(),
                        path,
                        owner_token,
                        _file: file,
                    });
                }
                Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                    let existing =
                        fs::read_to_string(&path).map_err(|_| PlannerStoreError::CorruptLock)?;
                    if lock_owner_is_current(existing.trim())? {
                        return Err(PlannerStoreError::Locked);
                    }
                    fs::remove_file(&path)?;
                    sync_directory(root)?;
                }
                Err(error) => return Err(error.into()),
            }
        }
    }
}

impl Drop for PlannerWriterLockV1 {
    fn drop(&mut self) {
        let owned = fs::read_to_string(&self.path)
            .ok()
            .is_some_and(|value| value.trim() == self.owner_token);
        if owned {
            let _ = fs::remove_file(&self.path);
            let _ = sync_directory(&self.root);
        }
    }
}

pub struct PlannerStoreV1 {
    root: PathBuf,
    _lock: PlannerWriterLockV1,
    log: File,
    records: Vec<PlannerStoreRecordV1>,
    config: PlannerStoreConfigV1,
    failpoint: Option<PlannerStoreFailpointV1>,
}

impl PlannerStoreV1 {
    /// Open the current schema and acquire the owner-local single-writer lock.
    /// A partial final frame is truncated to the last complete verified frame;
    /// corruption inside a complete frame fails closed. The RAII lock is
    /// released on every failed-open path.
    pub fn open(
        root: impl AsRef<Path>,
        config: PlannerStoreConfigV1,
    ) -> Result<Self, PlannerStoreError> {
        validate_config(config)?;
        let root = root.as_ref().to_path_buf();
        fs::create_dir_all(&root)?;
        let lock = PlannerWriterLockV1::acquire(&root)?;
        let log_path = root.join(LOG_NAME);
        let mut log = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .open(log_path)?;
        let mut bytes = Vec::new();
        log.read_to_end(&mut bytes)?;
        let decoded = decode_records(&bytes, config)?;
        if decoded.partial_tail {
            let valid = u64::try_from(decoded.valid_bytes).map_err(|_| {
                PlannerStoreError::Io("valid planner log length does not fit u64".to_string())
            })?;
            log.set_len(valid)?;
            log.sync_data()?;
        }
        log.seek(SeekFrom::End(0))?;
        Ok(Self {
            root,
            _lock: lock,
            log,
            records: decoded.records,
            config,
            failpoint: None,
        })
    }

    #[must_use]
    pub fn records(&self) -> &[PlannerStoreRecordV1] {
        &self.records
    }

    #[must_use]
    pub const fn schema_version(&self) -> u16 {
        SCHEMA_VERSION
    }

    pub fn set_failpoint(&mut self, failpoint: Option<PlannerStoreFailpointV1>) {
        self.failpoint = failpoint;
    }

    /// Append one complete canonical envelope. Equal operation identity and
    /// semantics are idempotent; identity reuse with different semantics is a
    /// conflict. The record is published in memory only after `sync_data`.
    pub fn append(
        &mut self,
        kind: PlannerStoreRecordKindV1,
        operation_identity_digest: Digest32,
        payload_digest: Digest32,
        envelope: &[u8],
    ) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
        require_digest(operation_identity_digest, "operation identity")?;
        require_digest(payload_digest, "payload")?;
        if envelope.len() > self.config.maximum_envelope_bytes {
            return Err(PlannerStoreError::EnvelopeTooLarge {
                actual: envelope.len(),
                maximum: self.config.maximum_envelope_bytes,
            });
        }
        if let Some(existing) = self
            .records
            .iter()
            .find(|record| record.operation_identity_digest == operation_identity_digest)
        {
            if existing.kind == kind
                && existing.payload_digest == payload_digest
                && existing.envelope == envelope
            {
                return Ok(existing.clone());
            }
            return Err(PlannerStoreError::IdentityConflict);
        }
        if self.records.len() >= self.config.maximum_records {
            return Err(PlannerStoreError::RecordLimitExceeded);
        }
        let sequence = self.records.last().map_or(Ok(1), |record| {
            record
                .sequence
                .checked_add(1)
                .ok_or(PlannerStoreError::RecordLimitExceeded)
        })?;
        let record_digest = digest_record(
            sequence,
            kind,
            operation_identity_digest,
            payload_digest,
            envelope,
        );
        let record = PlannerStoreRecordV1 {
            sequence,
            kind,
            operation_identity_digest,
            payload_digest,
            envelope: envelope.to_vec(),
            record_digest,
        };
        let frame = encode_record(&record)?;
        self.trip(PlannerStoreFailpointV1::DiskFullBeforeFrameWrite)?;
        self.trip(PlannerStoreFailpointV1::BeforeFrameWrite)?;
        let start = self.log.seek(SeekFrom::End(0))?;
        if let Err(error) = self.log.write_all(&frame) {
            self.log.set_len(start)?;
            self.log.seek(SeekFrom::End(0))?;
            self.log.sync_data()?;
            return Err(error.into());
        }
        self.trip(PlannerStoreFailpointV1::AfterFrameWriteBeforeSync)?;
        self.log.sync_data()?;
        self.trip(PlannerStoreFailpointV1::AfterLogSyncBeforePublish)?;
        self.records.push(record.clone());
        Ok(record)
    }

    /// Atomically publish a checkpoint bound to an external non-zero anchor.
    /// The anchor may be a signed evidence-ledger receipt, TPM measurement or
    /// another independently retained digest; this store does not mint it.
    pub fn checkpoint(
        &mut self,
        external_anchor_digest: Digest32,
    ) -> Result<PlannerStoreCheckpointV1, PlannerStoreError> {
        require_digest(external_anchor_digest, "external checkpoint anchor")?;
        self.log.sync_data()?;
        let sequence = self.records.last().map_or(0, |record| record.sequence);
        let store_digest = digest_store(&self.records);
        let checkpoint_digest = digest_checkpoint(sequence, store_digest, external_anchor_digest);
        let checkpoint = PlannerStoreCheckpointV1 {
            sequence,
            store_digest,
            external_anchor_digest,
            checkpoint_digest,
        };
        let bytes = encode_checkpoint(&checkpoint);
        let temp_path = self.root.join(CHECKPOINT_TEMP_NAME);
        let final_path = self.root.join(CHECKPOINT_NAME);
        write_new_file(&temp_path, &bytes)?;
        self.trip(PlannerStoreFailpointV1::BeforeCheckpointRename)?;
        fs::rename(&temp_path, &final_path)?;
        self.trip(PlannerStoreFailpointV1::AfterCheckpointRenameBeforeDirectorySync)?;
        sync_directory(&self.root)?;
        Ok(checkpoint)
    }

    pub fn verify_checkpoint(
        &self,
        expected_anchor_digest: Digest32,
    ) -> Result<PlannerStoreCheckpointV1, PlannerStoreError> {
        require_digest(expected_anchor_digest, "expected checkpoint anchor")?;
        let bytes = fs::read(self.root.join(CHECKPOINT_NAME))?;
        let checkpoint = decode_checkpoint(&bytes)?;
        if checkpoint.external_anchor_digest != expected_anchor_digest
            || checkpoint.sequence != self.records.last().map_or(0, |record| record.sequence)
            || checkpoint.store_digest != digest_store(&self.records)
        {
            return Err(PlannerStoreError::CheckpointMismatch);
        }
        Ok(checkpoint)
    }

    /// Rewrite the log to retain only the newest bounded suffix. Compaction
    /// invalidates the prior checkpoint, which must be anchored again.
    pub fn compact(&mut self, retain_last: usize) -> Result<(), PlannerStoreError> {
        if retain_last == 0 || retain_last > self.config.maximum_records {
            return Err(PlannerStoreError::InvalidConfiguration);
        }
        let first = self.records.len().saturating_sub(retain_last);
        let retained = self.records[first..].to_vec();
        let mut bytes = Vec::new();
        for record in &retained {
            bytes.extend_from_slice(&encode_record(record)?);
        }
        let temp_path = self.root.join(LOG_TEMP_NAME);
        write_new_file(&temp_path, &bytes)?;
        self.trip(PlannerStoreFailpointV1::BeforeCompactionRename)?;
        fs::rename(&temp_path, self.root.join(LOG_NAME))?;
        self.trip(PlannerStoreFailpointV1::AfterCompactionRenameBeforeDirectorySync)?;
        let checkpoint_path = self.root.join(CHECKPOINT_NAME);
        if checkpoint_path.exists() {
            fs::remove_file(checkpoint_path)?;
        }
        sync_directory(&self.root)?;
        self.log = OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join(LOG_NAME))?;
        self.log.seek(SeekFrom::End(0))?;
        self.records = retained;
        Ok(())
    }

    pub fn backup_to(&mut self, destination: impl AsRef<Path>) -> Result<(), PlannerStoreError> {
        self.log.sync_data()?;
        let checkpoint_bytes = fs::read(self.root.join(CHECKPOINT_NAME))?;
        let checkpoint = decode_checkpoint(&checkpoint_bytes)?;
        if checkpoint.store_digest != digest_store(&self.records) {
            return Err(PlannerStoreError::CheckpointMismatch);
        }
        let destination = destination.as_ref();
        fs::create_dir_all(destination)?;
        atomic_write(destination, LOG_NAME, &fs::read(self.root.join(LOG_NAME))?)?;
        atomic_write(destination, CHECKPOINT_NAME, &checkpoint_bytes)?;
        sync_directory(destination)
    }

    pub fn restore_from_backup(
        backup: impl AsRef<Path>,
        destination: impl AsRef<Path>,
        config: PlannerStoreConfigV1,
    ) -> Result<Self, PlannerStoreError> {
        validate_config(config)?;
        let backup = backup.as_ref();
        let destination = destination.as_ref();
        if destination.join(LOCK_NAME).exists() {
            let existing = fs::read_to_string(destination.join(LOCK_NAME))
                .map_err(|_| PlannerStoreError::CorruptLock)?;
            if lock_owner_is_current(existing.trim())? {
                return Err(PlannerStoreError::Locked);
            }
            fs::remove_file(destination.join(LOCK_NAME))?;
        }
        let log_bytes = fs::read(backup.join(LOG_NAME))?;
        let decoded = decode_records(&log_bytes, config)?;
        if decoded.partial_tail {
            return Err(PlannerStoreError::Truncated);
        }
        let checkpoint_bytes = fs::read(backup.join(CHECKPOINT_NAME))?;
        let checkpoint = decode_checkpoint(&checkpoint_bytes)?;
        if checkpoint.sequence != decoded.records.last().map_or(0, |record| record.sequence)
            || checkpoint.store_digest != digest_store(&decoded.records)
        {
            return Err(PlannerStoreError::CheckpointMismatch);
        }
        fs::create_dir_all(destination)?;
        atomic_write(destination, LOG_NAME, &log_bytes)?;
        atomic_write(destination, CHECKPOINT_NAME, &checkpoint_bytes)?;
        sync_directory(destination)?;
        Self::open(destination, config)
    }

    pub fn validate_migration(from: u16, to: u16) -> Result<(), PlannerStoreError> {
        if from == SCHEMA_VERSION && to == SCHEMA_VERSION {
            Ok(())
        } else {
            Err(PlannerStoreError::UnsupportedSchemaVersion(to))
        }
    }

    fn trip(&mut self, point: PlannerStoreFailpointV1) -> Result<(), PlannerStoreError> {
        if self.failpoint == Some(point) {
            self.failpoint = None;
            if point == PlannerStoreFailpointV1::DiskFullBeforeFrameWrite {
                return Err(PlannerStoreError::Io("injected disk full".to_string()));
            }
            return Err(PlannerStoreError::Failpoint(point));
        }
        Ok(())
    }
}

impl Drop for PlannerStoreV1 {
    fn drop(&mut self) {
        let _ = self.log.sync_data();
    }
}

struct DecodedRecords {
    records: Vec<PlannerStoreRecordV1>,
    valid_bytes: usize,
    partial_tail: bool,
}

fn decode_records(
    bytes: &[u8],
    config: PlannerStoreConfigV1,
) -> Result<DecodedRecords, PlannerStoreError> {
    let mut records = Vec::new();
    let mut offset = 0;
    while offset < bytes.len() {
        let frame_start = offset;
        if bytes.len() - offset < FRAME_FIXED_BYTES {
            return Ok(DecodedRecords {
                records,
                valid_bytes: frame_start,
                partial_tail: true,
            });
        }
        if take(bytes, &mut offset, 8)? != STORE_MAGIC {
            return Err(PlannerStoreError::CorruptHeader);
        }
        let version = read_u16(bytes, &mut offset)?;
        if version != SCHEMA_VERSION {
            return Err(PlannerStoreError::UnsupportedSchemaVersion(version));
        }
        let kind = PlannerStoreRecordKindV1::from_tag(read_u8(bytes, &mut offset)?)?;
        let sequence = read_u64(bytes, &mut offset)?;
        let operation_identity_digest = read_digest(bytes, &mut offset)?;
        let payload_digest = read_digest(bytes, &mut offset)?;
        require_digest(operation_identity_digest, "serialized operation identity")?;
        require_digest(payload_digest, "serialized payload")?;
        let envelope_len = usize::try_from(read_u32(bytes, &mut offset)?).map_err(|_| {
            PlannerStoreError::EnvelopeTooLarge {
                actual: usize::MAX,
                maximum: config.maximum_envelope_bytes,
            }
        })?;
        if envelope_len > config.maximum_envelope_bytes {
            return Err(PlannerStoreError::EnvelopeTooLarge {
                actual: envelope_len,
                maximum: config.maximum_envelope_bytes,
            });
        }
        let required_tail = envelope_len
            .checked_add(32)
            .ok_or(PlannerStoreError::Truncated)?;
        if bytes.len() - offset < required_tail {
            return Ok(DecodedRecords {
                records,
                valid_bytes: frame_start,
                partial_tail: true,
            });
        }
        let envelope = take(bytes, &mut offset, envelope_len)?.to_vec();
        let record_digest = read_digest(bytes, &mut offset)?;
        let expected_sequence =
            records
                .last()
                .map_or(Ok(sequence), |record: &PlannerStoreRecordV1| {
                    record
                        .sequence
                        .checked_add(1)
                        .ok_or(PlannerStoreError::CorruptSequence)
                })?;
        if sequence == 0 || sequence != expected_sequence {
            return Err(PlannerStoreError::CorruptSequence);
        }
        let expected_digest = digest_record(
            sequence,
            kind,
            operation_identity_digest,
            payload_digest,
            &envelope,
        );
        if expected_digest != record_digest {
            return Err(PlannerStoreError::CorruptRecordDigest);
        }
        if records
            .iter()
            .any(|record| record.operation_identity_digest == operation_identity_digest)
        {
            return Err(PlannerStoreError::IdentityConflict);
        }
        records.push(PlannerStoreRecordV1 {
            sequence,
            kind,
            operation_identity_digest,
            payload_digest,
            envelope,
            record_digest,
        });
        if records.len() > config.maximum_records {
            return Err(PlannerStoreError::RecordLimitExceeded);
        }
    }
    Ok(DecodedRecords {
        records,
        valid_bytes: offset,
        partial_tail: false,
    })
}

fn encode_record(record: &PlannerStoreRecordV1) -> Result<Vec<u8>, PlannerStoreError> {
    let envelope_len =
        u32::try_from(record.envelope.len()).map_err(|_| PlannerStoreError::EnvelopeTooLarge {
            actual: record.envelope.len(),
            maximum: usize::try_from(u32::MAX).unwrap_or(usize::MAX),
        })?;
    let mut bytes = Vec::with_capacity(FRAME_FIXED_BYTES + record.envelope.len());
    bytes.extend_from_slice(STORE_MAGIC);
    bytes.extend_from_slice(&SCHEMA_VERSION.to_be_bytes());
    bytes.push(record.kind.tag());
    bytes.extend_from_slice(&record.sequence.to_be_bytes());
    bytes.extend_from_slice(record.operation_identity_digest.as_array());
    bytes.extend_from_slice(record.payload_digest.as_array());
    bytes.extend_from_slice(&envelope_len.to_be_bytes());
    bytes.extend_from_slice(&record.envelope);
    bytes.extend_from_slice(record.record_digest.as_array());
    Ok(bytes)
}

fn digest_record(
    sequence: u64,
    kind: PlannerStoreRecordKindV1,
    operation_identity_digest: Digest32,
    payload_digest: Digest32,
    envelope: &[u8],
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.control.planner-store-record.v1");
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.push(kind.tag());
    bytes.extend_from_slice(operation_identity_digest.as_array());
    bytes.extend_from_slice(payload_digest.as_array());
    bytes.extend_from_slice(
        &u64::try_from(envelope.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(envelope);
    Digest32::of_bytes(&bytes)
}

fn digest_store(records: &[PlannerStoreRecordV1]) -> Digest32 {
    let mut bytes = b"hepta.control.planner-store.v1".to_vec();
    bytes.extend_from_slice(
        &u64::try_from(records.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    for record in records {
        bytes.extend_from_slice(record.record_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_checkpoint(
    sequence: u64,
    store_digest: Digest32,
    external_anchor_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.control.planner-checkpoint.v1".to_vec();
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(store_digest.as_array());
    bytes.extend_from_slice(external_anchor_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn encode_checkpoint(checkpoint: &PlannerStoreCheckpointV1) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(CHECKPOINT_BYTES);
    bytes.extend_from_slice(CHECKPOINT_MAGIC);
    bytes.extend_from_slice(&SCHEMA_VERSION.to_be_bytes());
    bytes.extend_from_slice(&checkpoint.sequence.to_be_bytes());
    bytes.extend_from_slice(checkpoint.store_digest.as_array());
    bytes.extend_from_slice(checkpoint.external_anchor_digest.as_array());
    bytes.extend_from_slice(checkpoint.checkpoint_digest.as_array());
    bytes
}

fn decode_checkpoint(bytes: &[u8]) -> Result<PlannerStoreCheckpointV1, PlannerStoreError> {
    if bytes.len() != CHECKPOINT_BYTES {
        return Err(PlannerStoreError::Truncated);
    }
    let mut offset = 0;
    if take(bytes, &mut offset, 8)? != CHECKPOINT_MAGIC {
        return Err(PlannerStoreError::CorruptHeader);
    }
    let version = read_u16(bytes, &mut offset)?;
    if version != SCHEMA_VERSION {
        return Err(PlannerStoreError::UnsupportedSchemaVersion(version));
    }
    let sequence = read_u64(bytes, &mut offset)?;
    let store_digest = read_digest(bytes, &mut offset)?;
    let external_anchor_digest = read_digest(bytes, &mut offset)?;
    let checkpoint_digest = read_digest(bytes, &mut offset)?;
    require_digest(store_digest, "checkpoint store")?;
    require_digest(external_anchor_digest, "checkpoint external anchor")?;
    let expected = digest_checkpoint(sequence, store_digest, external_anchor_digest);
    if checkpoint_digest != expected {
        return Err(PlannerStoreError::CheckpointMismatch);
    }
    Ok(PlannerStoreCheckpointV1 {
        sequence,
        store_digest,
        external_anchor_digest,
        checkpoint_digest,
    })
}

fn validate_config(config: PlannerStoreConfigV1) -> Result<(), PlannerStoreError> {
    if config.maximum_records == 0 || config.maximum_envelope_bytes == 0 {
        return Err(PlannerStoreError::InvalidConfiguration);
    }
    Ok(())
}

fn require_digest(value: Digest32, field: &'static str) -> Result<(), PlannerStoreError> {
    if value.is_zero() {
        return Err(PlannerStoreError::EmptyDigest(field));
    }
    Ok(())
}

fn write_new_file(path: &Path, bytes: &[u8]) -> Result<(), PlannerStoreError> {
    if path.exists() {
        fs::remove_file(path)?;
    }
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

fn atomic_write(root: &Path, name: &str, bytes: &[u8]) -> Result<(), PlannerStoreError> {
    let temp_path = root.join(format!("{name}.tmp"));
    write_new_file(&temp_path, bytes)?;
    fs::rename(temp_path, root.join(name))?;
    sync_directory(root)
}

fn sync_directory(path: &Path) -> Result<(), PlannerStoreError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

fn current_process_token() -> Result<String, PlannerStoreError> {
    process_token(std::process::id())?.ok_or(PlannerStoreError::CorruptLock)
}

#[cfg(target_os = "linux")]
fn process_token(pid: u32) -> Result<Option<String>, PlannerStoreError> {
    let path = format!("/proc/{pid}/stat");
    let stat = match fs::read_to_string(path) {
        Ok(value) => value,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let end = stat.rfind(')').ok_or(PlannerStoreError::CorruptLock)?;
    let tail = stat.get(end + 1..).ok_or(PlannerStoreError::CorruptLock)?;
    // The tail starts at proc field 3; starttime is field 22.
    let start_time = tail
        .split_whitespace()
        .nth(19)
        .ok_or(PlannerStoreError::CorruptLock)?;
    Ok(Some(format!("{pid}:{start_time}")))
}

#[cfg(not(target_os = "linux"))]
fn process_token(pid: u32) -> Result<Option<String>, PlannerStoreError> {
    Ok(Some(pid.to_string()))
}

fn lock_owner_is_current(token: &str) -> Result<bool, PlannerStoreError> {
    let (pid, _) = token
        .split_once(':')
        .ok_or(PlannerStoreError::CorruptLock)?;
    let pid = pid
        .parse::<u32>()
        .map_err(|_| PlannerStoreError::CorruptLock)?;
    Ok(process_token(pid)?.as_deref() == Some(token))
}

fn take<'a>(
    bytes: &'a [u8],
    offset: &mut usize,
    count: usize,
) -> Result<&'a [u8], PlannerStoreError> {
    let end = (*offset)
        .checked_add(count)
        .ok_or(PlannerStoreError::Truncated)?;
    let value = bytes
        .get(*offset..end)
        .ok_or(PlannerStoreError::Truncated)?;
    *offset = end;
    Ok(value)
}

fn read_u8(bytes: &[u8], offset: &mut usize) -> Result<u8, PlannerStoreError> {
    Ok(take(bytes, offset, 1)?[0])
}

fn read_u16(bytes: &[u8], offset: &mut usize) -> Result<u16, PlannerStoreError> {
    let value: [u8; 2] = take(bytes, offset, 2)?
        .try_into()
        .map_err(|_| PlannerStoreError::Truncated)?;
    Ok(u16::from_be_bytes(value))
}

fn read_u32(bytes: &[u8], offset: &mut usize) -> Result<u32, PlannerStoreError> {
    let value: [u8; 4] = take(bytes, offset, 4)?
        .try_into()
        .map_err(|_| PlannerStoreError::Truncated)?;
    Ok(u32::from_be_bytes(value))
}

fn read_u64(bytes: &[u8], offset: &mut usize) -> Result<u64, PlannerStoreError> {
    let value: [u8; 8] = take(bytes, offset, 8)?
        .try_into()
        .map_err(|_| PlannerStoreError::Truncated)?;
    Ok(u64::from_be_bytes(value))
}

fn read_digest(bytes: &[u8], offset: &mut usize) -> Result<Digest32, PlannerStoreError> {
    let value: [u8; 32] = take(bytes, offset, 32)?
        .try_into()
        .map_err(|_| PlannerStoreError::Truncated)?;
    Ok(Digest32::from_array(value))
}

#[cfg(test)]
#[path = "planner_store_tests.rs"]
mod tests;
