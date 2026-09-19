//! Durable owner store for immutable run-start snapshots.
//!
//! This is a separate journal from causal learning events so extending run-start
//! publication does not change the historical learning-ledger file format. The
//! host supplies and authorizes the file handle and scope binding; this module
//! grants no model, tool, network, selection, promotion or release authority.

use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAGIC: &[u8; 8] = b"HEPTRS01";
const HEADER: usize = 72;
const FRAME_OVERHEAD: usize = 112;
const RECORD_DOMAIN: &[u8] = b"hepta.run-start-record.v1";
const CHAIN_DOMAIN: &[u8] = b"hepta.run-start-chain.v1";
const MAX_RECORDS: usize = 4096;
const MAX_OBJECTIVE_SEMANTIC_BYTES: usize = 256 * 1024;
const MAX_FILE_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartSnapshotV1 {
    pub run_id: StableId,
    pub objective_digest: Digest32,
    pub hard_constraint_digest: Digest32,
    pub preference_state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub prompt_registry_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
}

/// Authenticated ingress identity consumed by the durable run-start owner.
/// Authentication itself is performed by the product host; persisting these
/// fields atomically with the objective makes replay state recoverable.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartAuthenticationV1 {
    pub issuer_id: StableId,
    pub key_epoch: u64,
    pub message_id: StableId,
    pub sequence: u64,
    pub signed_body_digest: Digest32,
}

/// Admission facts required to recover the exact source/profile/deadline
/// identity without reconstructing or trusting ambient caller state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartAdmissionBindingV1 {
    pub profile_digest: Digest32,
    pub intent_digest: Digest32,
    pub admitted_source_digest: Digest32,
    pub observed_at_unix_micros: u64,
    pub deadline_unix_micros: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RunStartObjectiveDispositionV1 {
    Compiled,
    ExplicitAbstain,
}

/// Durable publication unit. The objective bytes are the objective compiler's
/// native canonical semantic bytes and MUST hash to `objective_digest`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartRecordV1 {
    pub authentication: RunStartAuthenticationV1,
    pub admission: RunStartAdmissionBindingV1,
    pub disposition: RunStartObjectiveDispositionV1,
    pub snapshot: RunStartSnapshotV1,
    pub runtime_body_digest: Digest32,
    pub objective_semantic_bytes: Vec<u8>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RunStartAppendDisposition {
    Appended,
    IdempotentReplay,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartAppendReceipt {
    pub disposition: RunStartAppendDisposition,
    pub sequence: u64,
    pub record_digest: Digest32,
    pub chain_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RunStartAnchor {
    pub sequence: u64,
    pub chain_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RunStartRecovery {
    Unacknowledged,
    Acknowledged(RunStartAnchor),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RunStartStoreError {
    InvalidBinding,
    InvalidLimit,
    InvalidAnchor,
    InvalidSnapshot(&'static str),
    ObjectiveDigestMismatch,
    Busy,
    NotRegular,
    AlreadyInitialized,
    MissingHeader,
    BindingMismatch,
    AcknowledgedHistoryMissing,
    AnchorMismatch,
    Corrupt,
    Conflict,
    Capacity,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
}

impl fmt::Display for RunStartStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for RunStartStoreError {}
impl From<io::Error> for RunStartStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct StoredRunStart {
    sequence: u64,
    predecessor_chain_digest: Digest32,
    record_digest: Digest32,
    chain_digest: Digest32,
    record: RunStartRecordV1,
}

type ReplayedRunStarts = (
    Vec<StoredRunStart>,
    BTreeMap<StableId, usize>,
    u64,
    u64,
);

struct LockedRunStartFile(File);

impl LockedRunStartFile {
    fn acquire(file: File) -> Result<Self, RunStartStoreError> {
        if !file.metadata()?.is_file() {
            return Err(RunStartStoreError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(RunStartStoreError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}

impl Drop for LockedRunStartFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

pub struct DurableRunStartJournal {
    file: LockedRunStartFile,
    records: Vec<StoredRunStart>,
    by_run: BTreeMap<StableId, usize>,
    max_records: usize,
    durable_length: u64,
    poisoned: bool,
}

impl DurableRunStartJournal {
    /// Create a new empty run-start journal. File creation and directory
    /// durability remain host responsibilities.
    pub fn create(
        file: File,
        binding: Digest32,
        max_records: usize,
    ) -> Result<Self, RunStartStoreError> {
        validate_domain(binding, max_records)?;
        let mut file = LockedRunStartFile::acquire(file)?;
        if file.0.metadata()?.len() != 0 {
            return Err(RunStartStoreError::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        let checksum = Digest32::of_bytes(&header);
        header.extend_from_slice(checksum.as_array());
        file.0.seek(SeekFrom::Start(0))?;
        file.0
            .write_all(&header)
            .and_then(|()| file.0.sync_all())
            .map_err(|_| RunStartStoreError::Indeterminate)?;
        Ok(Self {
            file,
            records: Vec::new(),
            by_run: BTreeMap::new(),
            max_records,
            durable_length: HEADER as u64,
            poisoned: false,
        })
    }

    /// Recover complete frames and, only after validating an optional external
    /// acknowledgement anchor, truncate an incomplete unacknowledged tail.
    pub fn recover(
        file: File,
        binding: Digest32,
        max_records: usize,
        recovery: RunStartRecovery,
    ) -> Result<Self, RunStartStoreError> {
        validate_domain(binding, max_records)?;
        validate_recovery(recovery, max_records)?;
        let mut file = LockedRunStartFile::acquire(file)?;
        let (records, by_run, cursor, length) = replay_frames(&mut file.0, binding, max_records)?;
        if let RunStartRecovery::Acknowledged(anchor) = recovery {
            let record = records
                .get((anchor.sequence - 1) as usize)
                .ok_or(RunStartStoreError::AcknowledgedHistoryMissing)?;
            if record.chain_digest != anchor.chain_digest {
                return Err(RunStartStoreError::AnchorMismatch);
            }
        }
        if cursor != length {
            file.0
                .set_len(cursor)
                .map_err(|_| RunStartStoreError::Indeterminate)?;
            file.0
                .sync_all()
                .map_err(|_| RunStartStoreError::Indeterminate)?;
        }
        Ok(Self {
            file,
            records,
            by_run,
            max_records,
            durable_length: cursor,
            poisoned: false,
        })
    }

    /// Append one immutable run-start publication. Reuse of `run_id` is
    /// idempotent only for identical canonical record bytes.
    pub fn append(
        &mut self,
        expected_predecessor: Digest32,
        record: RunStartRecordV1,
    ) -> Result<RunStartAppendReceipt, RunStartStoreError> {
        if self.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        validate_record(&record)?;
        let record_digest = Digest32::of_bytes(&encode_record(&record));
        if let Some(index) = self.by_run.get(&record.snapshot.run_id).copied() {
            let existing = &self.records[index];
            if existing.record_digest != record_digest || existing.record != record {
                return Err(RunStartStoreError::Conflict);
            }
            if existing.predecessor_chain_digest != expected_predecessor {
                return Err(RunStartStoreError::Conflict);
            }
            return Ok(RunStartAppendReceipt {
                disposition: RunStartAppendDisposition::IdempotentReplay,
                sequence: existing.sequence,
                record_digest: existing.record_digest,
                chain_digest: existing.chain_digest,
            });
        }
        if self.records.len() >= self.max_records {
            return Err(RunStartStoreError::Capacity);
        }
        let predecessor = self
            .records
            .last()
            .map_or(Digest32::ZERO, |value| value.chain_digest);
        if predecessor != expected_predecessor {
            return Err(RunStartStoreError::Conflict);
        }
        let sequence = self.records.len() as u64 + 1;
        let chain_digest = digest_chain(predecessor, sequence, record_digest);
        let stored = StoredRunStart {
            sequence,
            predecessor_chain_digest: predecessor,
            record_digest,
            chain_digest,
            record,
        };
        let frame = encode_frame(&stored)?;
        let next_length = self.durable_length + frame.len() as u64;
        if next_length > MAX_FILE_BYTES {
            return Err(RunStartStoreError::Capacity);
        }
        self.poisoned = true;
        if self.file.0.seek(SeekFrom::End(0))? != self.durable_length {
            return Err(RunStartStoreError::Corrupt);
        }
        self.file
            .0
            .write_all(&frame)
            .and_then(|()| self.file.0.sync_all())
            .map_err(|_| RunStartStoreError::Indeterminate)?;
        let index = self.records.len();
        self.by_run
            .insert(stored.record.snapshot.run_id.clone(), index);
        self.records.push(stored);
        self.durable_length = next_length;
        self.poisoned = false;
        Ok(RunStartAppendReceipt {
            disposition: RunStartAppendDisposition::Appended,
            sequence,
            record_digest,
            chain_digest,
        })
    }

    pub fn records(&self) -> Result<Vec<&RunStartRecordV1>, RunStartStoreError> {
        if self.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        Ok(self.records.iter().map(|value| &value.record).collect())
    }

    pub fn get(&self, run_id: &StableId) -> Result<Option<&RunStartRecordV1>, RunStartStoreError> {
        if self.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        Ok(self
            .by_run
            .get(run_id)
            .and_then(|index| self.records.get(*index))
            .map(|value| &value.record))
    }

    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.records
            .last()
            .map_or(Digest32::ZERO, |value| value.chain_digest)
    }
}

mod sealed {
    pub trait Journal {}
    impl Journal for super::DurableRunStartJournal {}
}

/// Destination-owner publication port. Callers may request publication through
/// this interface but cannot implement a fake durable writer.
pub trait RunStartJournal: sealed::Journal {
    fn append_run_start(
        &mut self,
        expected_predecessor: Digest32,
        record: RunStartRecordV1,
    ) -> Result<RunStartAppendReceipt, RunStartStoreError>;
}

impl RunStartJournal for DurableRunStartJournal {
    fn append_run_start(
        &mut self,
        expected_predecessor: Digest32,
        record: RunStartRecordV1,
    ) -> Result<RunStartAppendReceipt, RunStartStoreError> {
        self.append(expected_predecessor, record)
    }
}

fn validate_record(record: &RunStartRecordV1) -> Result<(), RunStartStoreError> {
    if record.authentication.key_epoch == 0 || record.authentication.sequence == 0 {
        return Err(RunStartStoreError::InvalidSnapshot("authentication"));
    }
    if record.admission.observed_at_unix_micros == 0
        || record.admission.deadline_unix_micros <= record.admission.observed_at_unix_micros
    {
        return Err(RunStartStoreError::InvalidSnapshot("admissionTime"));
    }
    let snapshot = &record.snapshot;
    for (name, digest) in [
        ("signedBodyDigest", record.authentication.signed_body_digest),
        ("profileDigest", record.admission.profile_digest),
        ("intentDigest", record.admission.intent_digest),
        ("admittedSourceDigest", record.admission.admitted_source_digest),
        ("runtimeBodyDigest", record.runtime_body_digest),
        ("objectiveDigest", snapshot.objective_digest),
        ("hardConstraintDigest", snapshot.hard_constraint_digest),
        ("preferenceStateDigest", snapshot.preference_state_digest),
        ("modelTupleDigest", snapshot.model_tuple_digest),
        ("promptRegistryDigest", snapshot.prompt_registry_digest),
        ("artifactSetDigest", snapshot.artifact_set_digest),
        ("fenceDigest", snapshot.fence_digest),
    ] {
        if digest.is_zero() {
            return Err(RunStartStoreError::InvalidSnapshot(name));
        }
    }
    if record.objective_semantic_bytes.is_empty()
        || record.objective_semantic_bytes.len() > MAX_OBJECTIVE_SEMANTIC_BYTES
    {
        return Err(RunStartStoreError::InvalidSnapshot(
            "objectiveSemanticBytes",
        ));
    }
    if Digest32::of_bytes(&record.objective_semantic_bytes) != snapshot.objective_digest {
        return Err(RunStartStoreError::ObjectiveDigestMismatch);
    }
    Ok(())
}

fn encode_record(record: &RunStartRecordV1) -> Vec<u8> {
    let snapshot = &record.snapshot;
    let mut bytes = RECORD_DOMAIN.to_vec();
    push_id(&mut bytes, &record.authentication.issuer_id);
    push_u64(&mut bytes, record.authentication.key_epoch);
    push_id(&mut bytes, &record.authentication.message_id);
    push_u64(&mut bytes, record.authentication.sequence);
    push_digest(&mut bytes, record.authentication.signed_body_digest);
    push_digest(&mut bytes, record.admission.profile_digest);
    push_digest(&mut bytes, record.admission.intent_digest);
    push_digest(&mut bytes, record.admission.admitted_source_digest);
    push_u64(&mut bytes, record.admission.observed_at_unix_micros);
    push_u64(&mut bytes, record.admission.deadline_unix_micros);
    push_u64(
        &mut bytes,
        match record.disposition {
            RunStartObjectiveDispositionV1::Compiled => 0,
            RunStartObjectiveDispositionV1::ExplicitAbstain => 1,
        },
    );
    push_id(&mut bytes, &snapshot.run_id);
    push_digest(&mut bytes, snapshot.objective_digest);
    push_digest(&mut bytes, snapshot.hard_constraint_digest);
    push_digest(&mut bytes, snapshot.preference_state_digest);
    push_digest(&mut bytes, snapshot.model_tuple_digest);
    push_digest(&mut bytes, snapshot.prompt_registry_digest);
    push_digest(&mut bytes, snapshot.artifact_set_digest);
    push_u64(&mut bytes, snapshot.authority_epoch);
    push_u64(&mut bytes, snapshot.generation);
    push_digest(&mut bytes, snapshot.fence_digest);
    push_digest(&mut bytes, record.runtime_body_digest);
    push_len(&mut bytes, record.objective_semantic_bytes.len());
    bytes.extend_from_slice(&record.objective_semantic_bytes);
    bytes
}

fn decode_record(input: &[u8]) -> Result<RunStartRecordV1, RunStartStoreError> {
    let input = input
        .strip_prefix(RECORD_DOMAIN)
        .ok_or(RunStartStoreError::Corrupt)?;
    let mut reader = Reader(input);
    let authentication = RunStartAuthenticationV1 {
        issuer_id: reader.id()?,
        key_epoch: reader.u64()?,
        message_id: reader.id()?,
        sequence: reader.u64()?,
        signed_body_digest: reader.digest()?,
    };
    let admission = RunStartAdmissionBindingV1 {
        profile_digest: reader.digest()?,
        intent_digest: reader.digest()?,
        admitted_source_digest: reader.digest()?,
        observed_at_unix_micros: reader.u64()?,
        deadline_unix_micros: reader.u64()?,
    };
    let disposition = match reader.u64()? {
        0 => RunStartObjectiveDispositionV1::Compiled,
        1 => RunStartObjectiveDispositionV1::ExplicitAbstain,
        _ => return Err(RunStartStoreError::Corrupt),
    };
    let record = RunStartRecordV1 {
        authentication,
        admission,
        disposition,
        snapshot: RunStartSnapshotV1 {
            run_id: reader.id()?,
            objective_digest: reader.digest()?,
            hard_constraint_digest: reader.digest()?,
            preference_state_digest: reader.digest()?,
            model_tuple_digest: reader.digest()?,
            prompt_registry_digest: reader.digest()?,
            artifact_set_digest: reader.digest()?,
            authority_epoch: reader.u64()?,
            generation: reader.u64()?,
            fence_digest: reader.digest()?,
        },
        runtime_body_digest: reader.digest()?,
        objective_semantic_bytes: {
            let length = reader.len()?;
            if length == 0 || length > MAX_OBJECTIVE_SEMANTIC_BYTES {
                return Err(RunStartStoreError::Corrupt);
            }
            reader.bytes(length)?.to_vec()
        },
    };
    if !reader.0.is_empty() || validate_record(&record).is_err() {
        return Err(RunStartStoreError::Corrupt);
    }
    Ok(record)
}

fn encode_frame(stored: &StoredRunStart) -> Result<Vec<u8>, RunStartStoreError> {
    let payload = encode_record(&stored.record);
    if payload.len() > MAX_OBJECTIVE_SEMANTIC_BYTES + 1024 {
        return Err(RunStartStoreError::Capacity);
    }
    let size = u32::try_from(payload.len()).map_err(|_| RunStartStoreError::Capacity)?;
    let mut frame = Vec::with_capacity(payload.len() + FRAME_OVERHEAD);
    frame.extend_from_slice(&size.to_be_bytes());
    frame.extend_from_slice(&(!size).to_be_bytes());
    frame.extend_from_slice(&stored.sequence.to_be_bytes());
    frame.extend_from_slice(stored.predecessor_chain_digest.as_array());
    frame.extend_from_slice(&payload);
    frame.extend_from_slice(stored.chain_digest.as_array());
    let checksum = Digest32::of_bytes(&frame);
    frame.extend_from_slice(checksum.as_array());
    Ok(frame)
}

fn replay_frames(
    file: &mut File,
    binding: Digest32,
    max_records: usize,
) -> Result<ReplayedRunStarts, RunStartStoreError> {
    let length = file.metadata()?.len();
    if length < HEADER as u64 {
        return Err(RunStartStoreError::MissingHeader);
    }
    if length > MAX_FILE_BYTES {
        return Err(RunStartStoreError::Capacity);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut header = [0_u8; HEADER];
    file.read_exact(&mut header)?;
    if &header[..8] != MAGIC || Digest32::of_bytes(&header[..40]).as_array() != &header[40..] {
        return Err(RunStartStoreError::Corrupt);
    }
    if &header[8..40] != binding.as_array() {
        return Err(RunStartStoreError::BindingMismatch);
    }

    let mut records = Vec::new();
    let mut by_run = BTreeMap::new();
    let mut cursor = HEADER as u64;
    while cursor < length {
        if length - cursor < 8 {
            break;
        }
        let mut prefix = [0_u8; 8];
        file.read_exact(&mut prefix)?;
        let size = u32::from_be_bytes(
            prefix[..4]
                .try_into()
                .map_err(|_| RunStartStoreError::Corrupt)?,
        ) as usize;
        let complement = u32::from_be_bytes(
            prefix[4..]
                .try_into()
                .map_err(|_| RunStartStoreError::Corrupt)?,
        );
        if size == 0 || (size as u32) != !complement || size > MAX_OBJECTIVE_SEMANTIC_BYTES + 1024 {
            return Err(RunStartStoreError::Corrupt);
        }
        let total = size + FRAME_OVERHEAD;
        if length - cursor < total as u64 {
            break;
        }
        if records.len() >= max_records {
            return Err(RunStartStoreError::Capacity);
        }
        let mut frame = vec![0_u8; total];
        frame[..8].copy_from_slice(&prefix);
        file.read_exact(&mut frame[8..])?;
        if Digest32::of_bytes(&frame[..total - 32]).as_array() != &frame[total - 32..] {
            return Err(RunStartStoreError::Corrupt);
        }
        let sequence = u64::from_be_bytes(
            frame[8..16]
                .try_into()
                .map_err(|_| RunStartStoreError::Corrupt)?,
        );
        if sequence != records.len() as u64 + 1 {
            return Err(RunStartStoreError::Corrupt);
        }
        let predecessor = Digest32::from_array(
            frame[16..48]
                .try_into()
                .map_err(|_| RunStartStoreError::Corrupt)?,
        );
        let expected_predecessor = records
            .last()
            .map_or(Digest32::ZERO, |value: &StoredRunStart| value.chain_digest);
        if predecessor != expected_predecessor {
            return Err(RunStartStoreError::Corrupt);
        }
        let payload_end = 48 + size;
        let record = decode_record(&frame[48..payload_end])?;
        if by_run.contains_key(&record.snapshot.run_id) {
            return Err(RunStartStoreError::Corrupt);
        }
        let record_digest = Digest32::of_bytes(&frame[48..payload_end]);
        let chain_digest = Digest32::from_array(
            frame[payload_end..payload_end + 32]
                .try_into()
                .map_err(|_| RunStartStoreError::Corrupt)?,
        );
        if chain_digest != digest_chain(predecessor, sequence, record_digest) {
            return Err(RunStartStoreError::Corrupt);
        }
        let index = records.len();
        by_run.insert(record.snapshot.run_id.clone(), index);
        records.push(StoredRunStart {
            sequence,
            predecessor_chain_digest: predecessor,
            record_digest,
            chain_digest,
            record,
        });
        cursor += total as u64;
    }
    Ok((records, by_run, cursor, length))
}

fn digest_chain(predecessor: Digest32, sequence: u64, record_digest: Digest32) -> Digest32 {
    let mut bytes = CHAIN_DOMAIN.to_vec();
    push_digest(&mut bytes, predecessor);
    push_u64(&mut bytes, sequence);
    push_digest(&mut bytes, record_digest);
    Digest32::of_bytes(&bytes)
}

fn validate_domain(binding: Digest32, max_records: usize) -> Result<(), RunStartStoreError> {
    if binding.is_zero() {
        return Err(RunStartStoreError::InvalidBinding);
    }
    if !(1..=MAX_RECORDS).contains(&max_records) {
        return Err(RunStartStoreError::InvalidLimit);
    }
    Ok(())
}

fn validate_recovery(
    recovery: RunStartRecovery,
    max_records: usize,
) -> Result<(), RunStartStoreError> {
    if let RunStartRecovery::Acknowledged(anchor) = recovery
        && (anchor.sequence == 0
            || anchor.sequence > max_records as u64
            || anchor.chain_digest.is_zero())
    {
        return Err(RunStartStoreError::InvalidAnchor);
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_len(bytes, value.as_str().len());
    bytes.extend_from_slice(value.as_str().as_bytes());
}
fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}
fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}
fn push_len(bytes: &mut Vec<u8>, value: usize) {
    let converted = u32::try_from(value).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&converted.to_be_bytes());
}

struct Reader<'a>(&'a [u8]);
impl Reader<'_> {
    fn bytes(&mut self, count: usize) -> Result<&[u8], RunStartStoreError> {
        let Some((value, remaining)) = self.0.split_at_checked(count) else {
            return Err(RunStartStoreError::Corrupt);
        };
        self.0 = remaining;
        Ok(value)
    }
    fn take<const N: usize>(&mut self) -> Result<[u8; N], RunStartStoreError> {
        self.bytes(N)?
            .try_into()
            .map_err(|_| RunStartStoreError::Corrupt)
    }
    fn id(&mut self) -> Result<StableId, RunStartStoreError> {
        let length = self.len()?;
        if !(1..=128).contains(&length) {
            return Err(RunStartStoreError::Corrupt);
        }
        let text =
            std::str::from_utf8(self.bytes(length)?).map_err(|_| RunStartStoreError::Corrupt)?;
        StableId::new(text).map_err(|_| RunStartStoreError::Corrupt)
    }
    fn digest(&mut self) -> Result<Digest32, RunStartStoreError> {
        Ok(Digest32::from_array(self.take()?))
    }
    fn u64(&mut self) -> Result<u64, RunStartStoreError> {
        Ok(u64::from_be_bytes(self.take()?))
    }
    fn len(&mut self) -> Result<usize, RunStartStoreError> {
        Ok(u32::from_be_bytes(self.take()?) as usize)
    }
}

#[cfg(test)]
#[path = "run_start_tests.rs"]
mod tests;
