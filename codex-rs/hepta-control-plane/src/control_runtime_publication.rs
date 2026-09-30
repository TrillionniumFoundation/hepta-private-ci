use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::PlannerJournalHeadV1;

const PUBLICATION_MAGIC: &[u8; 8] = b"HCRPUB01";
const MAX_PUBLICATION_RECORDS: usize = 4096;
const MAX_PUBLICATION_PAYLOAD_BYTES: usize = 64 * 1024;
const MAX_OWNER_ID_BYTES: usize = 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ControlRuntimePublicationKindV1 {
    SnapshotAdmitted,
    DecisionCommitted,
    GrantRequestsCommitted,
    AttemptTransition,
    PlanRevoked,
}

impl ControlRuntimePublicationKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::SnapshotAdmitted => 0,
            Self::DecisionCommitted => 1,
            Self::GrantRequestsCommitted => 2,
            Self::AttemptTransition => 3,
            Self::PlanRevoked => 4,
        }
    }

    fn from_tag(tag: u8) -> Result<Self, ControlRuntimePublicationErrorV1> {
        match tag {
            0 => Ok(Self::SnapshotAdmitted),
            1 => Ok(Self::DecisionCommitted),
            2 => Ok(Self::GrantRequestsCommitted),
            3 => Ok(Self::AttemptTransition),
            4 => Ok(Self::PlanRevoked),
            _ => Err(ControlRuntimePublicationErrorV1::UnknownKind(tag)),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ControlRuntimePublicationHeadV1 {
    pub sequence: u64,
    pub publication_digest: Digest32,
}

impl ControlRuntimePublicationHeadV1 {
    #[must_use]
    pub const fn empty() -> Self {
        Self {
            sequence: 0,
            publication_digest: Digest32::ZERO,
        }
    }
}

impl Default for ControlRuntimePublicationHeadV1 {
    fn default() -> Self {
        Self::empty()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlRuntimePublicationV1 {
    pub owner_id: StableId,
    pub sequence: u64,
    pub policy_epoch: u64,
    pub kind: ControlRuntimePublicationKindV1,
    pub subject_digest: Digest32,
    pub payload: Vec<u8>,
    pub journal_head: PlannerJournalHeadV1,
    pub occurred_at_micros: u64,
    pub predecessor_publication_digest: Digest32,
    pub publication_digest: Digest32,
}

impl ControlRuntimePublicationV1 {
    pub fn new(
        owner_id: StableId,
        expected: ControlRuntimePublicationHeadV1,
        policy_epoch: u64,
        kind: ControlRuntimePublicationKindV1,
        subject_digest: Digest32,
        payload: Vec<u8>,
        journal_head: PlannerJournalHeadV1,
        occurred_at_micros: u64,
    ) -> Result<Self, ControlRuntimePublicationErrorV1> {
        if policy_epoch == 0 {
            return Err(ControlRuntimePublicationErrorV1::InvalidPolicyEpoch);
        }
        if subject_digest.is_zero() {
            return Err(ControlRuntimePublicationErrorV1::EmptyDigest);
        }
        if payload.len() > MAX_PUBLICATION_PAYLOAD_BYTES {
            return Err(ControlRuntimePublicationErrorV1::PayloadTooLarge {
                actual: payload.len(),
            });
        }
        if Digest32::of_bytes(&payload) != subject_digest {
            return Err(ControlRuntimePublicationErrorV1::PayloadDigestMismatch);
        }
        let sequence = expected
            .sequence
            .checked_add(1)
            .ok_or(ControlRuntimePublicationErrorV1::RecordLimitExceeded)?;
        let mut record = Self {
            owner_id,
            sequence,
            policy_epoch,
            kind,
            subject_digest,
            payload,
            journal_head,
            occurred_at_micros,
            predecessor_publication_digest: expected.publication_digest,
            publication_digest: Digest32::ZERO,
        };
        record.publication_digest = digest_publication(&record);
        record.verify_against(expected)?;
        Ok(record)
    }

    #[must_use]
    pub const fn head(&self) -> ControlRuntimePublicationHeadV1 {
        ControlRuntimePublicationHeadV1 {
            sequence: self.sequence,
            publication_digest: self.publication_digest,
        }
    }

    pub fn verify_against(
        &self,
        expected: ControlRuntimePublicationHeadV1,
    ) -> Result<(), ControlRuntimePublicationErrorV1> {
        if self.sequence != expected.sequence.saturating_add(1)
            || self.predecessor_publication_digest != expected.publication_digest
        {
            return Err(ControlRuntimePublicationErrorV1::InvalidChain);
        }
        if self.policy_epoch == 0 || self.subject_digest.is_zero() {
            return Err(ControlRuntimePublicationErrorV1::EmptyDigest);
        }
        if self.payload.len() > MAX_PUBLICATION_PAYLOAD_BYTES {
            return Err(ControlRuntimePublicationErrorV1::PayloadTooLarge {
                actual: self.payload.len(),
            });
        }
        if Digest32::of_bytes(&self.payload) != self.subject_digest {
            return Err(ControlRuntimePublicationErrorV1::PayloadDigestMismatch);
        }
        if self.publication_digest != digest_publication(self) {
            return Err(ControlRuntimePublicationErrorV1::CorruptRecord);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlRuntimePublicationReceiptV1 {
    pub committed_head: ControlRuntimePublicationHeadV1,
    pub durable_log_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlRuntimePublicationErrorV1 {
    Io {
        operation: &'static str,
        kind: ErrorKind,
    },
    Busy,
    InvalidPolicyEpoch,
    EmptyDigest,
    PayloadTooLarge {
        actual: usize,
    },
    PayloadDigestMismatch,
    RecordLimitExceeded,
    InvalidChain,
    Conflict {
        expected: ControlRuntimePublicationHeadV1,
        actual: ControlRuntimePublicationHeadV1,
    },
    OwnerMismatch,
    CorruptHeader,
    CorruptRecord,
    Truncated,
    UnknownKind(u8),
}

impl std::fmt::Display for ControlRuntimePublicationErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ControlRuntimePublicationErrorV1 {}

pub trait ControlRuntimeDecisionPublisherV1 {
    fn load_records(
        &mut self,
        owner_id: &StableId,
    ) -> Result<Vec<ControlRuntimePublicationV1>, ControlRuntimePublicationErrorV1>;

    fn compare_and_publish(
        &mut self,
        expected: ControlRuntimePublicationHeadV1,
        record: &ControlRuntimePublicationV1,
    ) -> Result<ControlRuntimePublicationReceiptV1, ControlRuntimePublicationErrorV1>;
}

#[derive(Clone, Debug, Default)]
pub struct InMemoryControlRuntimeDecisionPublisherV1 {
    records: Vec<ControlRuntimePublicationV1>,
}

impl InMemoryControlRuntimeDecisionPublisherV1 {
    #[must_use]
    pub fn records(&self) -> &[ControlRuntimePublicationV1] {
        &self.records
    }
}

impl ControlRuntimeDecisionPublisherV1 for InMemoryControlRuntimeDecisionPublisherV1 {
    fn load_records(
        &mut self,
        owner_id: &StableId,
    ) -> Result<Vec<ControlRuntimePublicationV1>, ControlRuntimePublicationErrorV1> {
        validate_records(owner_id, &self.records)?;
        Ok(self.records.clone())
    }

    fn compare_and_publish(
        &mut self,
        expected: ControlRuntimePublicationHeadV1,
        record: &ControlRuntimePublicationV1,
    ) -> Result<ControlRuntimePublicationReceiptV1, ControlRuntimePublicationErrorV1> {
        if let Some(last) = self.records.last()
            && last == record
            && record.predecessor_publication_digest == expected.publication_digest
            && record.sequence == expected.sequence.saturating_add(1)
        {
            return Ok(receipt(&self.records));
        }
        let actual = publication_head(&self.records);
        if actual != expected {
            return Err(ControlRuntimePublicationErrorV1::Conflict { expected, actual });
        }
        record.verify_against(expected)?;
        if let Some(first) = self.records.first()
            && first.owner_id != record.owner_id
        {
            return Err(ControlRuntimePublicationErrorV1::OwnerMismatch);
        }
        if self.records.len() >= MAX_PUBLICATION_RECORDS {
            return Err(ControlRuntimePublicationErrorV1::RecordLimitExceeded);
        }
        self.records.push(record.clone());
        Ok(receipt(&self.records))
    }
}

#[derive(Clone, Debug)]
pub struct FileControlRuntimeDecisionPublisherV1 {
    path: PathBuf,
    backup_path: PathBuf,
    lock_path: PathBuf,
    owner_id: StableId,
}

impl FileControlRuntimeDecisionPublisherV1 {
    #[must_use]
    pub fn new(path: impl Into<PathBuf>, owner_id: StableId) -> Self {
        let path = path.into();
        Self {
            backup_path: path.with_extension("bak"),
            lock_path: path.with_extension("lock"),
            path,
            owner_id,
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
}

impl ControlRuntimeDecisionPublisherV1 for FileControlRuntimeDecisionPublisherV1 {
    fn load_records(
        &mut self,
        owner_id: &StableId,
    ) -> Result<Vec<ControlRuntimePublicationV1>, ControlRuntimePublicationErrorV1> {
        if owner_id != &self.owner_id {
            return Err(ControlRuntimePublicationErrorV1::OwnerMismatch);
        }
        let records = match read_optional(&self.path, "read publication log")? {
            Some(bytes) => decode_records(&bytes)?,
            None => Vec::new(),
        };
        validate_records(owner_id, &records)?;
        Ok(records)
    }

    fn compare_and_publish(
        &mut self,
        expected: ControlRuntimePublicationHeadV1,
        record: &ControlRuntimePublicationV1,
    ) -> Result<ControlRuntimePublicationReceiptV1, ControlRuntimePublicationErrorV1> {
        if record.owner_id != self.owner_id {
            return Err(ControlRuntimePublicationErrorV1::OwnerMismatch);
        }
        ensure_parent(&self.path)?;
        let _guard = FileLockGuard::acquire(&self.lock_path)?;
        let current_bytes = read_optional(&self.path, "read publication log before commit")?;
        let mut records = match current_bytes.as_deref() {
            Some(bytes) => decode_records(bytes)?,
            None => Vec::new(),
        };
        validate_records(&self.owner_id, &records)?;
        if let Some(last) = records.last()
            && last == record
            && record.predecessor_publication_digest == expected.publication_digest
            && record.sequence == expected.sequence.saturating_add(1)
        {
            return Ok(receipt(&records));
        }
        let actual = publication_head(&records);
        if actual != expected {
            return Err(ControlRuntimePublicationErrorV1::Conflict { expected, actual });
        }
        record.verify_against(expected)?;
        if records.len() >= MAX_PUBLICATION_RECORDS {
            return Err(ControlRuntimePublicationErrorV1::RecordLimitExceeded);
        }
        if let Some(bytes) = current_bytes {
            atomic_replace(
                &self.backup_path,
                &self.backup_path.with_extension("bak.tmp"),
                &bytes,
                "write publication backup",
            )?;
        }
        records.push(record.clone());
        let encoded = encode_records(&records)?;
        atomic_replace(
            &self.path,
            &self.path.with_extension("tmp"),
            &encoded,
            "write publication log",
        )?;
        let verified = read_optional(&self.path, "verify publication commit")?
            .ok_or(ControlRuntimePublicationErrorV1::Io {
                operation: "verify publication commit",
                kind: ErrorKind::NotFound,
            })?;
        let reopened = decode_records(&verified)?;
        validate_records(&self.owner_id, &reopened)?;
        if reopened != records {
            return Err(ControlRuntimePublicationErrorV1::CorruptRecord);
        }
        Ok(receipt(&records))
    }
}

fn validate_records(
    owner_id: &StableId,
    records: &[ControlRuntimePublicationV1],
) -> Result<(), ControlRuntimePublicationErrorV1> {
    if records.len() > MAX_PUBLICATION_RECORDS {
        return Err(ControlRuntimePublicationErrorV1::RecordLimitExceeded);
    }
    let mut head = ControlRuntimePublicationHeadV1::empty();
    for record in records {
        if &record.owner_id != owner_id {
            return Err(ControlRuntimePublicationErrorV1::OwnerMismatch);
        }
        record.verify_against(head)?;
        head = record.head();
    }
    Ok(())
}

fn publication_head(records: &[ControlRuntimePublicationV1]) -> ControlRuntimePublicationHeadV1 {
    records
        .last()
        .map_or_else(ControlRuntimePublicationHeadV1::empty, ControlRuntimePublicationV1::head)
}

fn receipt(records: &[ControlRuntimePublicationV1]) -> ControlRuntimePublicationReceiptV1 {
    let bytes = encode_records(records).unwrap_or_default();
    ControlRuntimePublicationReceiptV1 {
        committed_head: publication_head(records),
        durable_log_digest: Digest32::of_bytes(&bytes),
    }
}

fn digest_publication(record: &ControlRuntimePublicationV1) -> Digest32 {
    let mut bytes = b"hepta.control.runtime-publication.v1".to_vec();
    push_text(&mut bytes, record.owner_id.as_str());
    bytes.extend_from_slice(&record.sequence.to_be_bytes());
    bytes.extend_from_slice(&record.policy_epoch.to_be_bytes());
    bytes.push(record.kind.tag());
    bytes.extend_from_slice(record.subject_digest.as_array());
    bytes.extend_from_slice(&(record.payload.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&record.payload);
    bytes.extend_from_slice(&record.journal_head.sequence.to_be_bytes());
    bytes.extend_from_slice(record.journal_head.entry_digest.as_array());
    bytes.extend_from_slice(&record.occurred_at_micros.to_be_bytes());
    bytes.extend_from_slice(record.predecessor_publication_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn encode_records(
    records: &[ControlRuntimePublicationV1],
) -> Result<Vec<u8>, ControlRuntimePublicationErrorV1> {
    if records.len() > MAX_PUBLICATION_RECORDS {
        return Err(ControlRuntimePublicationErrorV1::RecordLimitExceeded);
    }
    let mut bytes = Vec::new();
    bytes.extend_from_slice(PUBLICATION_MAGIC);
    bytes.extend_from_slice(
        &u32::try_from(records.len())
            .map_err(|_| ControlRuntimePublicationErrorV1::RecordLimitExceeded)?
            .to_be_bytes(),
    );
    for record in records {
        let owner = record.owner_id.as_str().as_bytes();
        if owner.is_empty() || owner.len() > MAX_OWNER_ID_BYTES {
            return Err(ControlRuntimePublicationErrorV1::CorruptRecord);
        }
        bytes.extend_from_slice(
            &u16::try_from(owner.len())
                .map_err(|_| ControlRuntimePublicationErrorV1::CorruptRecord)?
                .to_be_bytes(),
        );
        bytes.extend_from_slice(owner);
        bytes.extend_from_slice(&record.sequence.to_be_bytes());
        bytes.extend_from_slice(&record.policy_epoch.to_be_bytes());
        bytes.push(record.kind.tag());
        bytes.extend_from_slice(record.subject_digest.as_array());
        bytes.extend_from_slice(
            &u32::try_from(record.payload.len())
                .map_err(|_| ControlRuntimePublicationErrorV1::PayloadTooLarge {
                    actual: record.payload.len(),
                })?
                .to_be_bytes(),
        );
        bytes.extend_from_slice(&record.payload);
        bytes.extend_from_slice(&record.journal_head.sequence.to_be_bytes());
        bytes.extend_from_slice(record.journal_head.entry_digest.as_array());
        bytes.extend_from_slice(&record.occurred_at_micros.to_be_bytes());
        bytes.extend_from_slice(record.predecessor_publication_digest.as_array());
        bytes.extend_from_slice(record.publication_digest.as_array());
    }
    Ok(bytes)
}

fn decode_records(
    bytes: &[u8],
) -> Result<Vec<ControlRuntimePublicationV1>, ControlRuntimePublicationErrorV1> {
    if bytes.len() < 12 {
        return Err(ControlRuntimePublicationErrorV1::Truncated);
    }
    if &bytes[..8] != PUBLICATION_MAGIC {
        return Err(ControlRuntimePublicationErrorV1::CorruptHeader);
    }
    let count = usize::try_from(u32::from_be_bytes(
        bytes[8..12]
            .try_into()
            .map_err(|_| ControlRuntimePublicationErrorV1::Truncated)?,
    ))
    .map_err(|_| ControlRuntimePublicationErrorV1::RecordLimitExceeded)?;
    if count > MAX_PUBLICATION_RECORDS {
        return Err(ControlRuntimePublicationErrorV1::RecordLimitExceeded);
    }
    let mut offset = 12;
    let mut records = Vec::with_capacity(count);
    for _ in 0..count {
        let owner_len = usize::from(read_u16(bytes, &mut offset)?);
        if owner_len == 0 || owner_len > MAX_OWNER_ID_BYTES {
            return Err(ControlRuntimePublicationErrorV1::CorruptRecord);
        }
        let owner_end = offset
            .checked_add(owner_len)
            .ok_or(ControlRuntimePublicationErrorV1::Truncated)?;
        let owner = std::str::from_utf8(
            bytes
                .get(offset..owner_end)
                .ok_or(ControlRuntimePublicationErrorV1::Truncated)?,
        )
        .map_err(|_| ControlRuntimePublicationErrorV1::CorruptRecord)?;
        let owner_id =
            StableId::new(owner).map_err(|_| ControlRuntimePublicationErrorV1::CorruptRecord)?;
        offset = owner_end;
        let sequence = read_u64(bytes, &mut offset)?;
        let policy_epoch = read_u64(bytes, &mut offset)?;
        let kind = ControlRuntimePublicationKindV1::from_tag(read_u8(bytes, &mut offset)?)?;
        let subject_digest = read_digest(bytes, &mut offset)?;
        let payload_len = usize::try_from(read_u32(bytes, &mut offset)?)
            .map_err(|_| ControlRuntimePublicationErrorV1::PayloadTooLarge { actual: usize::MAX })?;
        if payload_len > MAX_PUBLICATION_PAYLOAD_BYTES {
            return Err(ControlRuntimePublicationErrorV1::PayloadTooLarge {
                actual: payload_len,
            });
        }
        let payload_end = offset
            .checked_add(payload_len)
            .ok_or(ControlRuntimePublicationErrorV1::Truncated)?;
        let payload = bytes
            .get(offset..payload_end)
            .ok_or(ControlRuntimePublicationErrorV1::Truncated)?
            .to_vec();
        offset = payload_end;
        let journal_head = PlannerJournalHeadV1 {
            sequence: read_u64(bytes, &mut offset)?,
            entry_digest: read_digest(bytes, &mut offset)?,
        };
        let occurred_at_micros = read_u64(bytes, &mut offset)?;
        let predecessor_publication_digest = read_digest(bytes, &mut offset)?;
        let publication_digest = read_digest(bytes, &mut offset)?;
        records.push(ControlRuntimePublicationV1 {
            owner_id,
            sequence,
            policy_epoch,
            kind,
            subject_digest,
            payload,
            journal_head,
            occurred_at_micros,
            predecessor_publication_digest,
            publication_digest,
        });
    }
    if offset != bytes.len() {
        return Err(ControlRuntimePublicationErrorV1::CorruptRecord);
    }
    Ok(records)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn read_u8(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<u8, ControlRuntimePublicationErrorV1> {
    let value = *bytes
        .get(*offset)
        .ok_or(ControlRuntimePublicationErrorV1::Truncated)?;
    *offset = (*offset)
        .checked_add(1)
        .ok_or(ControlRuntimePublicationErrorV1::Truncated)?;
    Ok(value)
}

fn read_u16(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<u16, ControlRuntimePublicationErrorV1> {
    let end = (*offset)
        .checked_add(2)
        .ok_or(ControlRuntimePublicationErrorV1::Truncated)?;
    let value = u16::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(ControlRuntimePublicationErrorV1::Truncated)?
            .try_into()
            .map_err(|_| ControlRuntimePublicationErrorV1::Truncated)?,
    );
    *offset = end;
    Ok(value)
}

fn read_u32(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<u32, ControlRuntimePublicationErrorV1> {
    let end = (*offset)
        .checked_add(4)
        .ok_or(ControlRuntimePublicationErrorV1::Truncated)?;
    let value = u32::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(ControlRuntimePublicationErrorV1::Truncated)?
            .try_into()
            .map_err(|_| ControlRuntimePublicationErrorV1::Truncated)?,
    );
    *offset = end;
    Ok(value)
}

fn read_u64(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<u64, ControlRuntimePublicationErrorV1> {
    let end = (*offset)
        .checked_add(8)
        .ok_or(ControlRuntimePublicationErrorV1::Truncated)?;
    let value = u64::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(ControlRuntimePublicationErrorV1::Truncated)?
            .try_into()
            .map_err(|_| ControlRuntimePublicationErrorV1::Truncated)?,
    );
    *offset = end;
    Ok(value)
}

fn read_digest(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<Digest32, ControlRuntimePublicationErrorV1> {
    let end = (*offset)
        .checked_add(32)
        .ok_or(ControlRuntimePublicationErrorV1::Truncated)?;
    let digest = Digest32::from_array(
        bytes
            .get(*offset..end)
            .ok_or(ControlRuntimePublicationErrorV1::Truncated)?
            .try_into()
            .map_err(|_| ControlRuntimePublicationErrorV1::Truncated)?,
    );
    *offset = end;
    Ok(digest)
}

fn read_optional(
    path: &Path,
    operation: &'static str,
) -> Result<Option<Vec<u8>>, ControlRuntimePublicationErrorV1> {
    match fs::read(path) {
        Ok(bytes) => Ok(Some(bytes)),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(None),
        Err(error) => Err(io_error(operation, error.kind())),
    }
}

fn ensure_parent(path: &Path) -> Result<(), ControlRuntimePublicationErrorV1> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)
        .map_err(|error| io_error("create publication directory", error.kind()))
}

fn atomic_replace(
    path: &Path,
    temporary: &Path,
    bytes: &[u8],
    operation: &'static str,
) -> Result<(), ControlRuntimePublicationErrorV1> {
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
fn sync_parent(parent: &Path) -> Result<(), ControlRuntimePublicationErrorV1> {
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| io_error("sync publication directory", error.kind()))
}

#[cfg(not(unix))]
fn sync_parent(_parent: &Path) -> Result<(), ControlRuntimePublicationErrorV1> {
    Ok(())
}

fn io_error(operation: &'static str, kind: ErrorKind) -> ControlRuntimePublicationErrorV1 {
    ControlRuntimePublicationErrorV1::Io { operation, kind }
}

struct FileLockGuard {
    path: PathBuf,
    _file: File,
}

impl FileLockGuard {
    fn acquire(path: &Path) -> Result<Self, ControlRuntimePublicationErrorV1> {
        let file = match OpenOptions::new().write(true).create_new(true).open(path) {
            Ok(file) => file,
            Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                return Err(ControlRuntimePublicationErrorV1::Busy);
            }
            Err(error) => return Err(io_error("acquire publication lock", error.kind())),
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
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn record(
        expected: ControlRuntimePublicationHeadV1,
        payload: &[u8],
    ) -> ControlRuntimePublicationV1 {
        ControlRuntimePublicationV1::new(
            id("control.runtime"),
            expected,
            1,
            ControlRuntimePublicationKindV1::DecisionCommitted,
            Digest32::of_bytes(payload),
            payload.to_vec(),
            PlannerJournalHeadV1 {
                sequence: 1,
                entry_digest: digest("journal"),
            },
            10,
        )
        .expect("record")
    }

    #[test]
    fn memory_publisher_is_compare_and_publish_and_idempotent() {
        let mut publisher = InMemoryControlRuntimeDecisionPublisherV1::default();
        let expected = ControlRuntimePublicationHeadV1::empty();
        let record = record(expected, b"decision");
        let first = publisher
            .compare_and_publish(expected, &record)
            .expect("publish");
        let replay = publisher
            .compare_and_publish(expected, &record)
            .expect("idempotent replay");
        assert_eq!(first, replay);
        assert_eq!(publisher.records().len(), 1);
    }

    #[test]
    fn file_publisher_round_trips_and_rejects_stale_head() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("publication.log");
        let owner = id("control.runtime");
        let mut publisher = FileControlRuntimeDecisionPublisherV1::new(&path, owner.clone());
        let expected = ControlRuntimePublicationHeadV1::empty();
        let record = record(expected, b"decision");
        publisher
            .compare_and_publish(expected, &record)
            .expect("publish");
        assert_eq!(
            publisher.load_records(&owner).expect("load"),
            vec![record.clone()]
        );
        let conflicting = record(expected, b"other");
        assert!(matches!(
            publisher.compare_and_publish(expected, &conflicting),
            Err(ControlRuntimePublicationErrorV1::Conflict { .. })
        ));
    }
}
