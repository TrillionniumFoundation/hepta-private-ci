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
const STORE_SCHEMA_VERSION: u32 = 1;
const HEADER_BYTES: usize = 12;
const FRAME_FIXED_BYTES: usize = 8 + 1 + 32 + 32;
const MAX_FRAME_PAYLOAD_BYTES: usize = 4 * 1024 * 1024;
const MAX_ENVELOPE_SECTION_BYTES: usize = 2 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerStoreRecordKindV1 {
    DecisionEnvelope,
    AuthorityRequest,
    Dispatch,
    TerminalReceipt,
    Reconciliation,
    Checkpoint,
    MigratedLegacyRecord,
}

impl PlannerStoreRecordKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::DecisionEnvelope => 0,
            Self::AuthorityRequest => 1,
            Self::Dispatch => 2,
            Self::TerminalReceipt => 3,
            Self::Reconciliation => 4,
            Self::Checkpoint => 5,
            Self::MigratedLegacyRecord => 6,
        }
    }

    fn from_tag(value: u8) -> Result<Self, PlannerStoreError> {
        match value {
            0 => Ok(Self::DecisionEnvelope),
            1 => Ok(Self::AuthorityRequest),
            2 => Ok(Self::Dispatch),
            3 => Ok(Self::TerminalReceipt),
            4 => Ok(Self::Reconciliation),
            5 => Ok(Self::Checkpoint),
            6 => Ok(Self::MigratedLegacyRecord),
            _ => Err(PlannerStoreError::UnknownRecordKind(value)),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerStoreFailpointV1 {
    BeforeFrameWrite,
    AfterFramePrefix,
    BeforeDataSync,
    BeforeAtomicRename,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalDecisionEnvelopeV1 {
    pub operation_identity_digest: Digest32,
    pub snapshot_bytes: Vec<u8>,
    pub prepared_plan_bytes: Vec<u8>,
    pub ndu_evaluation_bytes: Vec<u8>,
    pub plan_receipt_bytes: Vec<u8>,
    pub grant_request_set_bytes: Vec<u8>,
}

impl CanonicalDecisionEnvelopeV1 {
    pub fn validate(&self) -> Result<(), PlannerStoreError> {
        if self.operation_identity_digest.is_zero() {
            return Err(PlannerStoreError::EmptyDigest("operation identity"));
        }
        for (name, value) in [
            ("snapshot", self.snapshot_bytes.as_slice()),
            ("prepared plan", self.prepared_plan_bytes.as_slice()),
            ("NDU evaluation", self.ndu_evaluation_bytes.as_slice()),
            ("plan receipt", self.plan_receipt_bytes.as_slice()),
            ("grant request set", self.grant_request_set_bytes.as_slice()),
        ] {
            if value.is_empty() {
                return Err(PlannerStoreError::EmptyEnvelopeSection(name));
            }
            if value.len() > MAX_ENVELOPE_SECTION_BYTES {
                return Err(PlannerStoreError::EnvelopeSectionTooLarge(name));
            }
        }
        Ok(())
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, PlannerStoreError> {
        self.validate()?;
        let mut bytes = b"hepta.control.decision-envelope.v1\0".to_vec();
        bytes.extend_from_slice(self.operation_identity_digest.as_array());
        for section in [
            self.snapshot_bytes.as_slice(),
            self.prepared_plan_bytes.as_slice(),
            self.ndu_evaluation_bytes.as_slice(),
            self.plan_receipt_bytes.as_slice(),
            self.grant_request_set_bytes.as_slice(),
        ] {
            push_len(&mut bytes, section.len())?;
            bytes.extend_from_slice(section);
        }
        Ok(bytes)
    }

    pub fn digest(&self) -> Result<Digest32, PlannerStoreError> {
        Ok(Digest32::of_bytes(&self.canonical_bytes()?))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerStoreRecordV1 {
    pub sequence: u64,
    pub kind: PlannerStoreRecordKindV1,
    pub payload_digest: Digest32,
    pub frame_digest: Digest32,
    pub payload: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerStoreAppendReceiptV1 {
    pub sequence: u64,
    pub kind: PlannerStoreRecordKindV1,
    pub payload_digest: Digest32,
    pub frame_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerCheckpointV1 {
    pub through_sequence: u64,
    pub store_digest: Digest32,
    pub external_anchor_receipt: Vec<u8>,
}

#[derive(Debug)]
pub enum PlannerStoreError {
    Io(std::io::Error),
    WriterLocked,
    InvalidHeader,
    UnsupportedSchema(u32),
    UnknownRecordKind(u8),
    CorruptSequence,
    CorruptPayloadDigest,
    CorruptFrameDigest,
    EmptyDigest(&'static str),
    EmptyEnvelopeSection(&'static str),
    EnvelopeSectionTooLarge(&'static str),
    EmptyPayload,
    PayloadTooLarge,
    LengthOverflow,
    InvalidRetention,
    InvalidBackup,
    InjectedFailure(PlannerStoreFailpointV1),
}

impl fmt::Display for PlannerStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "planner store I/O failed: {error}"),
            other => write!(formatter, "{other:?}"),
        }
    }
}

impl StdError for PlannerStoreError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            _ => None,
        }
    }
}

impl From<std::io::Error> for PlannerStoreError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}

#[derive(Debug)]
pub struct PlannerStoreV1 {
    path: PathBuf,
    lock_path: PathBuf,
    file: File,
    records: Vec<PlannerStoreRecordV1>,
    next_sequence: u64,
    failpoint: Option<PlannerStoreFailpointV1>,
}

impl PlannerStoreV1 {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, PlannerStoreError> {
        let path = path.as_ref().to_path_buf();
        let parent = path.parent().unwrap_or_else(|| Path::new("."));
        fs::create_dir_all(parent)?;
        let lock_path = lock_path_for(&path);
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
        {
            Ok(mut lock) => {
                lock.write_all(b"hepta-control-planner-store-v1\n")?;
                lock.sync_all()?;
                sync_directory(parent)?;
            }
            Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                return Err(PlannerStoreError::WriterLocked);
            }
            Err(error) => return Err(error.into()),
        }

        let result = Self::open_locked(path.clone(), lock_path.clone());
        if result.is_err() {
            let _ = fs::remove_file(&lock_path);
        }
        result
    }

    fn open_locked(path: PathBuf, lock_path: PathBuf) -> Result<Self, PlannerStoreError> {
        let mut file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(&path)?;
        if file.metadata()?.len() == 0 {
            file.write_all(STORE_MAGIC)?;
            file.write_all(&STORE_SCHEMA_VERSION.to_be_bytes())?;
            file.sync_all()?;
            sync_directory(path.parent().unwrap_or_else(|| Path::new(".")))?;
        }
        file.seek(SeekFrom::Start(0))?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        let scan = scan_store(&bytes)?;
        if scan.complete_bytes < bytes.len() {
            file.set_len(
                u64::try_from(scan.complete_bytes)
                    .map_err(|_| PlannerStoreError::LengthOverflow)?,
            )?;
            file.sync_all()?;
        }
        file.seek(SeekFrom::End(0))?;
        let next_sequence = scan.records.last().map_or(Ok(1), |record| {
            record
                .sequence
                .checked_add(1)
                .ok_or(PlannerStoreError::LengthOverflow)
        })?;
        Ok(Self {
            path,
            lock_path,
            file,
            records: scan.records,
            next_sequence,
            failpoint: None,
        })
    }

    pub fn records(&self) -> &[PlannerStoreRecordV1] {
        &self.records
    }

    pub fn set_failpoint(&mut self, failpoint: Option<PlannerStoreFailpointV1>) {
        self.failpoint = failpoint;
    }

    pub fn append_decision(
        &mut self,
        envelope: &CanonicalDecisionEnvelopeV1,
    ) -> Result<PlannerStoreAppendReceiptV1, PlannerStoreError> {
        self.append(
            PlannerStoreRecordKindV1::DecisionEnvelope,
            &envelope.canonical_bytes()?,
        )
    }

    pub fn append(
        &mut self,
        kind: PlannerStoreRecordKindV1,
        payload: &[u8],
    ) -> Result<PlannerStoreAppendReceiptV1, PlannerStoreError> {
        if payload.is_empty() {
            return Err(PlannerStoreError::EmptyPayload);
        }
        if payload.len() > MAX_FRAME_PAYLOAD_BYTES {
            return Err(PlannerStoreError::PayloadTooLarge);
        }
        self.hit(PlannerStoreFailpointV1::BeforeFrameWrite)?;
        let record = build_record(self.next_sequence, kind, payload)?;
        let encoded = encode_record(&record)?;
        self.file.seek(SeekFrom::End(0))?;
        if self.failpoint == Some(PlannerStoreFailpointV1::AfterFramePrefix) {
            let partial = encoded.len().min(7);
            self.file.write_all(&encoded[..partial])?;
            self.file.sync_all()?;
            self.failpoint = None;
            return Err(PlannerStoreError::InjectedFailure(
                PlannerStoreFailpointV1::AfterFramePrefix,
            ));
        }
        self.file.write_all(&encoded)?;
        self.hit(PlannerStoreFailpointV1::BeforeDataSync)?;
        self.file.sync_all()?;
        self.next_sequence = self
            .next_sequence
            .checked_add(1)
            .ok_or(PlannerStoreError::LengthOverflow)?;
        let receipt = PlannerStoreAppendReceiptV1 {
            sequence: record.sequence,
            kind: record.kind,
            payload_digest: record.payload_digest,
            frame_digest: record.frame_digest,
        };
        self.records.push(record);
        Ok(receipt)
    }

    pub fn append_checkpoint(
        &mut self,
        external_anchor_receipt: &[u8],
    ) -> Result<PlannerCheckpointV1, PlannerStoreError> {
        if external_anchor_receipt.is_empty() {
            return Err(PlannerStoreError::EmptyPayload);
        }
        let through_sequence = self.records.last().map_or(0, |record| record.sequence);
        let store_digest = digest_records(&self.records);
        let mut payload = b"hepta.control.planner-checkpoint.v1\0".to_vec();
        payload.extend_from_slice(&through_sequence.to_be_bytes());
        payload.extend_from_slice(store_digest.as_array());
        push_len(&mut payload, external_anchor_receipt.len())?;
        payload.extend_from_slice(external_anchor_receipt);
        self.append(PlannerStoreRecordKindV1::Checkpoint, &payload)?;
        Ok(PlannerCheckpointV1 {
            through_sequence,
            store_digest,
            external_anchor_receipt: external_anchor_receipt.to_vec(),
        })
    }

    pub fn compact(&mut self, retain_last: usize) -> Result<(), PlannerStoreError> {
        if retain_last == 0 {
            return Err(PlannerStoreError::InvalidRetention);
        }
        let start = self.records.len().saturating_sub(retain_last);
        let retained = self.records[start..].to_vec();
        let bytes = encode_store(&retained)?;
        self.atomic_replace(&bytes)?;
        self.file = OpenOptions::new().read(true).write(true).open(&self.path)?;
        self.file.seek(SeekFrom::End(0))?;
        self.records = retained;
        self.next_sequence = self.records.last().map_or(Ok(1), |record| {
            record
                .sequence
                .checked_add(1)
                .ok_or(PlannerStoreError::LengthOverflow)
        })?;
        Ok(())
    }

    pub fn backup(&mut self, destination: impl AsRef<Path>) -> Result<(), PlannerStoreError> {
        self.file.sync_all()?;
        let mut source = Vec::new();
        File::open(&self.path)?.read_to_end(&mut source)?;
        let scan = scan_store(&source)?;
        if scan.complete_bytes != source.len() {
            return Err(PlannerStoreError::InvalidBackup);
        }
        atomic_write(destination.as_ref(), &source, None)
    }

    pub fn restore_from_backup(
        destination: impl AsRef<Path>,
        backup: impl AsRef<Path>,
    ) -> Result<(), PlannerStoreError> {
        let mut bytes = Vec::new();
        File::open(backup)?.read_to_end(&mut bytes)?;
        let scan = scan_store(&bytes)?;
        if scan.complete_bytes != bytes.len() {
            return Err(PlannerStoreError::InvalidBackup);
        }
        atomic_write(destination.as_ref(), &bytes, None)
    }

    pub fn migrate_v0_records(
        destination: impl AsRef<Path>,
        legacy_records: &[Vec<u8>],
    ) -> Result<(), PlannerStoreError> {
        let mut store = Self::open(destination)?;
        for record in legacy_records {
            store.append(PlannerStoreRecordKindV1::MigratedLegacyRecord, record)?;
        }
        store.append_checkpoint(b"deterministic-v0-to-v1-migration")?;
        Ok(())
    }

    fn atomic_replace(&mut self, bytes: &[u8]) -> Result<(), PlannerStoreError> {
        self.hit(PlannerStoreFailpointV1::BeforeAtomicRename)?;
        atomic_write(&self.path, bytes, None)
    }

    fn hit(&mut self, target: PlannerStoreFailpointV1) -> Result<(), PlannerStoreError> {
        if self.failpoint == Some(target) {
            self.failpoint = None;
            return Err(PlannerStoreError::InjectedFailure(target));
        }
        Ok(())
    }
}

impl Drop for PlannerStoreV1 {
    fn drop(&mut self) {
        let _ = self.file.sync_all();
        let _ = fs::remove_file(&self.lock_path);
        if let Some(parent) = self.lock_path.parent() {
            let _ = sync_directory(parent);
        }
    }
}

struct StoreScan {
    records: Vec<PlannerStoreRecordV1>,
    complete_bytes: usize,
}

fn scan_store(bytes: &[u8]) -> Result<StoreScan, PlannerStoreError> {
    if bytes.len() < HEADER_BYTES || &bytes[..8] != STORE_MAGIC {
        return Err(PlannerStoreError::InvalidHeader);
    }
    let schema = u32::from_be_bytes(
        bytes[8..12]
            .try_into()
            .map_err(|_| PlannerStoreError::InvalidHeader)?,
    );
    if schema != STORE_SCHEMA_VERSION {
        return Err(PlannerStoreError::UnsupportedSchema(schema));
    }
    let mut offset = HEADER_BYTES;
    let mut records = Vec::new();
    while offset < bytes.len() {
        if bytes.len() - offset < 4 {
            break;
        }
        let payload_len = usize::try_from(u32::from_be_bytes(
            bytes[offset..offset + 4]
                .try_into()
                .map_err(|_| PlannerStoreError::LengthOverflow)?,
        ))
        .map_err(|_| PlannerStoreError::LengthOverflow)?;
        if payload_len == 0 || payload_len > MAX_FRAME_PAYLOAD_BYTES {
            return Err(PlannerStoreError::PayloadTooLarge);
        }
        let frame_len = 4_usize
            .checked_add(FRAME_FIXED_BYTES)
            .and_then(|value| value.checked_add(payload_len))
            .ok_or(PlannerStoreError::LengthOverflow)?;
        let end = offset
            .checked_add(frame_len)
            .ok_or(PlannerStoreError::LengthOverflow)?;
        if end > bytes.len() {
            break;
        }
        let mut cursor = offset + 4;
        let sequence = read_u64(bytes, &mut cursor)?;
        let kind = PlannerStoreRecordKindV1::from_tag(bytes[cursor])?;
        cursor += 1;
        let payload_digest = read_digest(bytes, &mut cursor)?;
        let frame_digest = read_digest(bytes, &mut cursor)?;
        let payload = bytes[cursor..end].to_vec();
        let expected_sequence = records
            .last()
            .map_or(sequence, |record: &PlannerStoreRecordV1| {
                record.sequence + 1
            });
        if sequence == 0 || sequence != expected_sequence {
            return Err(PlannerStoreError::CorruptSequence);
        }
        if Digest32::of_bytes(&payload) != payload_digest {
            return Err(PlannerStoreError::CorruptPayloadDigest);
        }
        if digest_frame(sequence, kind, payload_digest, &payload) != frame_digest {
            return Err(PlannerStoreError::CorruptFrameDigest);
        }
        records.push(PlannerStoreRecordV1 {
            sequence,
            kind,
            payload_digest,
            frame_digest,
            payload,
        });
        offset = end;
    }
    Ok(StoreScan {
        records,
        complete_bytes: offset,
    })
}

fn build_record(
    sequence: u64,
    kind: PlannerStoreRecordKindV1,
    payload: &[u8],
) -> Result<PlannerStoreRecordV1, PlannerStoreError> {
    if sequence == 0 {
        return Err(PlannerStoreError::CorruptSequence);
    }
    let payload_digest = Digest32::of_bytes(payload);
    let frame_digest = digest_frame(sequence, kind, payload_digest, payload);
    Ok(PlannerStoreRecordV1 {
        sequence,
        kind,
        payload_digest,
        frame_digest,
        payload: payload.to_vec(),
    })
}

fn encode_record(record: &PlannerStoreRecordV1) -> Result<Vec<u8>, PlannerStoreError> {
    let mut bytes = Vec::with_capacity(4 + FRAME_FIXED_BYTES + record.payload.len());
    push_len(&mut bytes, record.payload.len())?;
    bytes.extend_from_slice(&record.sequence.to_be_bytes());
    bytes.push(record.kind.tag());
    bytes.extend_from_slice(record.payload_digest.as_array());
    bytes.extend_from_slice(record.frame_digest.as_array());
    bytes.extend_from_slice(&record.payload);
    Ok(bytes)
}

fn encode_store(records: &[PlannerStoreRecordV1]) -> Result<Vec<u8>, PlannerStoreError> {
    let mut bytes = STORE_MAGIC.to_vec();
    bytes.extend_from_slice(&STORE_SCHEMA_VERSION.to_be_bytes());
    for record in records {
        bytes.extend_from_slice(&encode_record(record)?);
    }
    Ok(bytes)
}

fn digest_frame(
    sequence: u64,
    kind: PlannerStoreRecordKindV1,
    payload_digest: Digest32,
    payload: &[u8],
) -> Digest32 {
    let mut bytes = b"hepta.control.planner-store-frame.v1\0".to_vec();
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.push(kind.tag());
    bytes.extend_from_slice(payload_digest.as_array());
    bytes.extend_from_slice(payload);
    Digest32::of_bytes(&bytes)
}

fn digest_records(records: &[PlannerStoreRecordV1]) -> Digest32 {
    let mut bytes = b"hepta.control.planner-store-root.v1\0".to_vec();
    for record in records {
        bytes.extend_from_slice(&record.sequence.to_be_bytes());
        bytes.extend_from_slice(record.frame_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn atomic_write(
    destination: &Path,
    bytes: &[u8],
    failpoint: Option<PlannerStoreFailpointV1>,
) -> Result<(), PlannerStoreError> {
    let parent = destination.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let file_name = destination
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("planner-store");
    let temporary = parent.join(format!(".{file_name}.tmp-{}", std::process::id()));
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(&temporary)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    if failpoint == Some(PlannerStoreFailpointV1::BeforeAtomicRename) {
        let _ = fs::remove_file(&temporary);
        return Err(PlannerStoreError::InjectedFailure(
            PlannerStoreFailpointV1::BeforeAtomicRename,
        ));
    }
    fs::rename(&temporary, destination)?;
    sync_directory(parent)?;
    Ok(())
}

fn sync_directory(path: &Path) -> Result<(), PlannerStoreError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

fn lock_path_for(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("planner-store");
    path.with_file_name(format!("{name}.writer.lock"))
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), PlannerStoreError> {
    let value = u32::try_from(value).map_err(|_| PlannerStoreError::LengthOverflow)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

fn read_u64(bytes: &[u8], cursor: &mut usize) -> Result<u64, PlannerStoreError> {
    let end = cursor
        .checked_add(8)
        .ok_or(PlannerStoreError::LengthOverflow)?;
    let value = u64::from_be_bytes(
        bytes
            .get(*cursor..end)
            .ok_or(PlannerStoreError::LengthOverflow)?
            .try_into()
            .map_err(|_| PlannerStoreError::LengthOverflow)?,
    );
    *cursor = end;
    Ok(value)
}

fn read_digest(bytes: &[u8], cursor: &mut usize) -> Result<Digest32, PlannerStoreError> {
    let end = cursor
        .checked_add(32)
        .ok_or(PlannerStoreError::LengthOverflow)?;
    let value: [u8; 32] = bytes
        .get(*cursor..end)
        .ok_or(PlannerStoreError::LengthOverflow)?
        .try_into()
        .map_err(|_| PlannerStoreError::LengthOverflow)?;
    *cursor = end;
    Ok(Digest32::from_array(value))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn envelope() -> CanonicalDecisionEnvelopeV1 {
        CanonicalDecisionEnvelopeV1 {
            operation_identity_digest: Digest32::of_bytes(b"operation"),
            snapshot_bytes: b"snapshot-body".to_vec(),
            prepared_plan_bytes: b"prepared-body".to_vec(),
            ndu_evaluation_bytes: b"ndu-body".to_vec(),
            plan_receipt_bytes: b"receipt-body".to_vec(),
            grant_request_set_bytes: b"grant-request-body".to_vec(),
        }
    }

    #[test]
    fn complete_envelope_survives_restart_backup_compaction_and_restore() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("planner.store");
        let backup = directory.path().join("planner.backup");
        let restored = directory.path().join("planner.restored");
        let digest = envelope().digest().expect("envelope digest");
        {
            let mut store = PlannerStoreV1::open(&path).expect("open");
            let receipt = store.append_decision(&envelope()).expect("append decision");
            assert_eq!(receipt.payload_digest, digest);
            store
                .append(PlannerStoreRecordKindV1::TerminalReceipt, b"terminal")
                .expect("terminal");
            store
                .append_checkpoint(b"signed-anchor")
                .expect("checkpoint");
            store.backup(&backup).expect("backup");
            store.compact(2).expect("compact");
            assert_eq!(store.records().len(), 2);
        }
        PlannerStoreV1::restore_from_backup(&restored, &backup).expect("restore");
        let restored_store = PlannerStoreV1::open(&restored).expect("reopen restored");
        assert_eq!(restored_store.records().len(), 3);
        assert_eq!(restored_store.records()[0].payload_digest, digest);
    }

    #[test]
    fn partial_tail_is_recovered_and_writer_lock_is_exclusive() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("planner.store");
        let mut store = PlannerStoreV1::open(&path).expect("open");
        assert!(matches!(
            PlannerStoreV1::open(&path),
            Err(PlannerStoreError::WriterLocked)
        ));
        store.set_failpoint(Some(PlannerStoreFailpointV1::AfterFramePrefix));
        assert!(matches!(
            store.append_decision(&envelope()),
            Err(PlannerStoreError::InjectedFailure(
                PlannerStoreFailpointV1::AfterFramePrefix
            ))
        ));
        drop(store);
        let mut reopened = PlannerStoreV1::open(&path).expect("recover partial tail");
        assert!(reopened.records().is_empty());
        reopened
            .append_decision(&envelope())
            .expect("append after recovery");
    }

    #[test]
    fn complete_frame_corruption_fails_closed() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("planner.store");
        {
            let mut store = PlannerStoreV1::open(&path).expect("open");
            store.append_decision(&envelope()).expect("append");
        }
        let mut bytes = fs::read(&path).expect("read");
        let last = bytes.last_mut().expect("payload byte");
        *last ^= 0x01;
        fs::write(&path, bytes).expect("corrupt");
        assert!(matches!(
            PlannerStoreV1::open(&path),
            Err(PlannerStoreError::CorruptPayloadDigest)
                | Err(PlannerStoreError::CorruptFrameDigest)
        ));
    }
}
