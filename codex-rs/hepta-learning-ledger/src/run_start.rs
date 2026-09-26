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

use codex_hepta_types::AuthorityFlagsV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAGIC: &[u8; 8] = b"HEPTRS01";
const HEADER: usize = 72;
const FRAME_OVERHEAD: usize = 112;
const RECORD_DOMAIN_V1: &[u8] = b"hepta.run-start-record.v1";
const RECORD_DOMAIN: &[u8] = b"hepta.run-start-record.v2";
const CONFLICT_RECORD_DOMAIN: &[u8] = b"hepta.run-start-conflict.v1";
const CHAIN_DOMAIN: &[u8] = b"hepta.run-start-chain.v1";
const MAX_RECORDS: usize = 4096;
const MAX_OBJECTIVE_SEMANTIC_BYTES: usize = 256 * 1024;
const MAX_OBJECTIVE_PROTOCOL_BYTES: usize = 256 * 1024;
const MAX_RUN_START_PAYLOAD_BYTES: usize =
    MAX_OBJECTIVE_SEMANTIC_BYTES + MAX_OBJECTIVE_PROTOCOL_BYTES + 4096;
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
    pub expires_at_ms: u64,
    pub scope_digest: Digest32,
    pub signed_body_digest: Digest32,
    pub signature: [u8; 64],
}

/// Admission facts required to recover the exact source/profile/deadline
/// identity without reconstructing or trusting ambient caller state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartAdmissionBindingV1 {
    pub profile_id: StableId,
    pub profile_revision: u64,
    pub profile_digest: Digest32,
    pub supplied_source_digest: Digest32,
    pub intent_digest: Digest32,
    pub admitted_source_digest: Digest32,
    pub observed_at_unix_micros: u64,
    pub deadline_unix_micros: u64,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RunStartObjectiveDispositionV1 {
    Compiled,
    ExplicitAbstain,
}

/// Durable publication unit.
///
/// objective_semantic_bytes bind the owner-native compiler identity recorded by
/// RunStartSnapshotV1.objective_digest. objective_function_v1_bytes separately
/// bind the registered canonical JSON protocol identity. Neither digest may be
/// substituted for the other.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartRecordV1 {
    pub authentication: RunStartAuthenticationV1,
    pub admission: RunStartAdmissionBindingV1,
    pub disposition: RunStartObjectiveDispositionV1,
    pub snapshot: RunStartSnapshotV1,
    pub runtime_body_digest: Digest32,
    pub objective_semantic_bytes: Vec<u8>,
    pub objective_function_v1_digest: Digest32,
    pub objective_function_v1_bytes: Vec<u8>,
}

impl RunStartRecordV1 {
    /// Digest of the validated canonical bytes used by the durable journal.
    /// This includes authentication, all snapshot fields and both objective
    /// encodings; it does not authenticate an arbitrary caller-created record.
    pub fn identity_digest(&self) -> Result<Digest32, RunStartStoreError> {
        validate_record(self)?;
        Ok(Digest32::of_bytes(&encode_record(self)))
    }
}

/// Durable hard-conflict outcome for an authenticated objective admission.
///
/// Conflict receipts do not create a runtime snapshot. They still consume the
/// same durable run identity and signed replay sequence so restart/retry cannot
/// forget that the exact admitted request terminated in a hard conflict.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartConflictRecordV1 {
    pub authentication: RunStartAuthenticationV1,
    pub admission: RunStartAdmissionBindingV1,
    pub run_id: StableId,
    pub runtime_body_digest: Digest32,
    pub conflict_digest: Digest32,
    pub conflict_receipt_bytes: Vec<u8>,
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
    ObjectiveProtocolDigestMismatch,
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
enum StoredRunStartRecord {
    Run(Box<RunStartRecordV1>),
    Conflict(Box<RunStartConflictRecordV1>),
}

impl StoredRunStartRecord {
    fn run_id(&self) -> &StableId {
        match self {
            Self::Run(record) => &record.snapshot.run_id,
            Self::Conflict(record) => &record.run_id,
        }
    }

    fn authentication(&self) -> &RunStartAuthenticationV1 {
        match self {
            Self::Run(record) => &record.authentication,
            Self::Conflict(record) => &record.authentication,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct StoredRunStart {
    sequence: u64,
    predecessor_chain_digest: Digest32,
    record_digest: Digest32,
    chain_digest: Digest32,
    record: StoredRunStartRecord,
}

type ReplayedRunStarts = (Vec<StoredRunStart>, BTreeMap<StableId, usize>, u64, u64);

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
        validate_record(&record)?;
        self.append_outcome(
            expected_predecessor,
            StoredRunStartRecord::Run(Box::new(record)),
        )
    }

    /// Append a durable hard-conflict outcome through the same predecessor
    /// chain and run-identity index as successful run starts.
    pub fn append_conflict(
        &mut self,
        expected_predecessor: Digest32,
        record: RunStartConflictRecordV1,
    ) -> Result<RunStartAppendReceipt, RunStartStoreError> {
        validate_conflict_record(&record)?;
        self.append_outcome(
            expected_predecessor,
            StoredRunStartRecord::Conflict(Box::new(record)),
        )
    }

    fn append_outcome(
        &mut self,
        expected_predecessor: Digest32,
        record: StoredRunStartRecord,
    ) -> Result<RunStartAppendReceipt, RunStartStoreError> {
        if self.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        let payload = encode_outcome_record(&record);
        let record_digest = Digest32::of_bytes(&payload);
        let run_id = record.run_id().clone();
        if let Some(index) = self.by_run.get(&run_id).copied() {
            let existing = &self.records[index];
            if existing.record_digest != record_digest || existing.record != record {
                return Err(RunStartStoreError::Conflict);
            }
            // Exact run identity is sufficient for idempotent replay even when
            // later outcomes have advanced the journal head. The predecessor
            // fence applies only to new appends.
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
        self.by_run.insert(run_id, index);
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
        Ok(self
            .records
            .iter()
            .filter_map(|value| match &value.record {
                StoredRunStartRecord::Run(record) => Some(record.as_ref()),
                StoredRunStartRecord::Conflict(_) => None,
            })
            .collect())
    }

    pub fn conflicts(&self) -> Result<Vec<&RunStartConflictRecordV1>, RunStartStoreError> {
        if self.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        Ok(self
            .records
            .iter()
            .filter_map(|value| match &value.record {
                StoredRunStartRecord::Run(_) => None,
                StoredRunStartRecord::Conflict(record) => Some(record.as_ref()),
            })
            .collect())
    }

    pub fn authentication_records(
        &self,
    ) -> Result<Vec<(&RunStartAuthenticationV1, &StableId)>, RunStartStoreError> {
        if self.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        Ok(self
            .records
            .iter()
            .map(|value| (value.record.authentication(), value.record.run_id()))
            .collect())
    }

    pub fn get(&self, run_id: &StableId) -> Result<Option<&RunStartRecordV1>, RunStartStoreError> {
        if self.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        Ok(self
            .by_run
            .get(run_id)
            .and_then(|index| self.records.get(*index))
            .and_then(|value| match &value.record {
                StoredRunStartRecord::Run(record) => Some(record.as_ref()),
                StoredRunStartRecord::Conflict(_) => None,
            }))
    }

    pub fn get_conflict(
        &self,
        run_id: &StableId,
    ) -> Result<Option<&RunStartConflictRecordV1>, RunStartStoreError> {
        if self.poisoned {
            return Err(RunStartStoreError::Poisoned);
        }
        Ok(self
            .by_run
            .get(run_id)
            .and_then(|index| self.records.get(*index))
            .and_then(|value| match &value.record {
                StoredRunStartRecord::Run(_) => None,
                StoredRunStartRecord::Conflict(record) => Some(record.as_ref()),
            }))
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

    fn append_objective_conflict(
        &mut self,
        expected_predecessor: Digest32,
        record: RunStartConflictRecordV1,
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

    fn append_objective_conflict(
        &mut self,
        expected_predecessor: Digest32,
        record: RunStartConflictRecordV1,
    ) -> Result<RunStartAppendReceipt, RunStartStoreError> {
        self.append_conflict(expected_predecessor, record)
    }
}

fn validate_record(record: &RunStartRecordV1) -> Result<(), RunStartStoreError> {
    validate_record_compat(record, true)
}

fn validate_record_compat(
    record: &RunStartRecordV1,
    require_protocol: bool,
) -> Result<(), RunStartStoreError> {
    if record.authentication.key_epoch == 0
        || record.authentication.sequence == 0
        || record.authentication.expires_at_ms == 0
        || record
            .authentication
            .signature
            .iter()
            .all(|byte| *byte == 0)
    {
        return Err(RunStartStoreError::InvalidSnapshot("authentication"));
    }
    if record.admission.profile_revision == 0
        || record.admission.observed_at_unix_micros == 0
        || record.admission.deadline_unix_micros <= record.admission.observed_at_unix_micros
        || record.admission.authority.grants_any()
    {
        return Err(RunStartStoreError::InvalidSnapshot("admission"));
    }
    let snapshot = &record.snapshot;
    for (name, digest) in [
        ("scopeDigest", record.authentication.scope_digest),
        ("signedBodyDigest", record.authentication.signed_body_digest),
        ("profileDigest", record.admission.profile_digest),
        (
            "suppliedSourceDigest",
            record.admission.supplied_source_digest,
        ),
        ("intentDigest", record.admission.intent_digest),
        (
            "admittedSourceDigest",
            record.admission.admitted_source_digest,
        ),
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
    if require_protocol {
        if record.objective_function_v1_digest.is_zero()
            || record.objective_function_v1_bytes.is_empty()
            || record.objective_function_v1_bytes.len() > MAX_OBJECTIVE_PROTOCOL_BYTES
        {
            return Err(RunStartStoreError::InvalidSnapshot("objectiveFunctionV1"));
        }
        if Digest32::of_bytes(&record.objective_function_v1_bytes)
            != record.objective_function_v1_digest
        {
            return Err(RunStartStoreError::ObjectiveProtocolDigestMismatch);
        }
    } else if !record.objective_function_v1_digest.is_zero()
        || !record.objective_function_v1_bytes.is_empty()
    {
        return Err(RunStartStoreError::Corrupt);
    }
    Ok(())
}

fn validate_conflict_record(record: &RunStartConflictRecordV1) -> Result<(), RunStartStoreError> {
    if record.authentication.key_epoch == 0
        || record.authentication.sequence == 0
        || record.authentication.expires_at_ms == 0
        || record
            .authentication
            .signature
            .iter()
            .all(|byte| *byte == 0)
    {
        return Err(RunStartStoreError::InvalidSnapshot("authentication"));
    }
    if record.admission.profile_revision == 0
        || record.admission.observed_at_unix_micros == 0
        || record.admission.deadline_unix_micros <= record.admission.observed_at_unix_micros
        || record.admission.authority.grants_any()
    {
        return Err(RunStartStoreError::InvalidSnapshot("admission"));
    }
    for (name, digest) in [
        ("scopeDigest", record.authentication.scope_digest),
        ("signedBodyDigest", record.authentication.signed_body_digest),
        ("profileDigest", record.admission.profile_digest),
        (
            "suppliedSourceDigest",
            record.admission.supplied_source_digest,
        ),
        ("intentDigest", record.admission.intent_digest),
        (
            "admittedSourceDigest",
            record.admission.admitted_source_digest,
        ),
        ("runtimeBodyDigest", record.runtime_body_digest),
        ("conflictDigest", record.conflict_digest),
    ] {
        if digest.is_zero() {
            return Err(RunStartStoreError::InvalidSnapshot(name));
        }
    }
    if record.conflict_receipt_bytes.is_empty()
        || record.conflict_receipt_bytes.len() > MAX_OBJECTIVE_SEMANTIC_BYTES
    {
        return Err(RunStartStoreError::InvalidSnapshot("conflictReceiptBytes"));
    }
    if Digest32::of_bytes(&record.conflict_receipt_bytes) != record.conflict_digest {
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
    push_u64(&mut bytes, record.authentication.expires_at_ms);
    push_digest(&mut bytes, record.authentication.scope_digest);
    push_digest(&mut bytes, record.authentication.signed_body_digest);
    bytes.extend_from_slice(&record.authentication.signature);
    push_id(&mut bytes, &record.admission.profile_id);
    push_u64(&mut bytes, record.admission.profile_revision);
    push_digest(&mut bytes, record.admission.profile_digest);
    push_digest(&mut bytes, record.admission.supplied_source_digest);
    push_digest(&mut bytes, record.admission.intent_digest);
    push_digest(&mut bytes, record.admission.admitted_source_digest);
    push_u64(&mut bytes, record.admission.observed_at_unix_micros);
    push_u64(&mut bytes, record.admission.deadline_unix_micros);
    push_authority(&mut bytes, record.admission.authority);
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
    push_digest(&mut bytes, record.objective_function_v1_digest);
    push_len(&mut bytes, record.objective_function_v1_bytes.len());
    bytes.extend_from_slice(&record.objective_function_v1_bytes);
    bytes
}

fn encode_conflict_record(record: &RunStartConflictRecordV1) -> Vec<u8> {
    let mut bytes = CONFLICT_RECORD_DOMAIN.to_vec();
    push_id(&mut bytes, &record.authentication.issuer_id);
    push_u64(&mut bytes, record.authentication.key_epoch);
    push_id(&mut bytes, &record.authentication.message_id);
    push_u64(&mut bytes, record.authentication.sequence);
    push_u64(&mut bytes, record.authentication.expires_at_ms);
    push_digest(&mut bytes, record.authentication.scope_digest);
    push_digest(&mut bytes, record.authentication.signed_body_digest);
    bytes.extend_from_slice(&record.authentication.signature);
    push_id(&mut bytes, &record.admission.profile_id);
    push_u64(&mut bytes, record.admission.profile_revision);
    push_digest(&mut bytes, record.admission.profile_digest);
    push_digest(&mut bytes, record.admission.supplied_source_digest);
    push_digest(&mut bytes, record.admission.intent_digest);
    push_digest(&mut bytes, record.admission.admitted_source_digest);
    push_u64(&mut bytes, record.admission.observed_at_unix_micros);
    push_u64(&mut bytes, record.admission.deadline_unix_micros);
    push_authority(&mut bytes, record.admission.authority);
    push_id(&mut bytes, &record.run_id);
    push_digest(&mut bytes, record.runtime_body_digest);
    push_digest(&mut bytes, record.conflict_digest);
    push_len(&mut bytes, record.conflict_receipt_bytes.len());
    bytes.extend_from_slice(&record.conflict_receipt_bytes);
    bytes
}

fn encode_outcome_record(record: &StoredRunStartRecord) -> Vec<u8> {
    match record {
        StoredRunStartRecord::Run(record) => encode_record(record),
        StoredRunStartRecord::Conflict(record) => encode_conflict_record(record),
    }
}

fn decode_record(input: &[u8]) -> Result<RunStartRecordV1, RunStartStoreError> {
    let (input, require_protocol) = if let Some(value) = input.strip_prefix(RECORD_DOMAIN) {
        (value, true)
    } else if let Some(value) = input.strip_prefix(RECORD_DOMAIN_V1) {
        (value, false)
    } else {
        return Err(RunStartStoreError::Corrupt);
    };
    let mut reader = Reader(input);
    let authentication = RunStartAuthenticationV1 {
        issuer_id: reader.id()?,
        key_epoch: reader.u64()?,
        message_id: reader.id()?,
        sequence: reader.u64()?,
        expires_at_ms: reader.u64()?,
        scope_digest: reader.digest()?,
        signed_body_digest: reader.digest()?,
        signature: reader
            .bytes(64)?
            .try_into()
            .map_err(|_| RunStartStoreError::Corrupt)?,
    };
    let admission = RunStartAdmissionBindingV1 {
        profile_id: reader.id()?,
        profile_revision: reader.u64()?,
        profile_digest: reader.digest()?,
        supplied_source_digest: reader.digest()?,
        intent_digest: reader.digest()?,
        admitted_source_digest: reader.digest()?,
        observed_at_unix_micros: reader.u64()?,
        deadline_unix_micros: reader.u64()?,
        authority: reader.authority()?,
    };
    let disposition = match reader.u64()? {
        0 => RunStartObjectiveDispositionV1::Compiled,
        1 => RunStartObjectiveDispositionV1::ExplicitAbstain,
        _ => return Err(RunStartStoreError::Corrupt),
    };
    let snapshot = RunStartSnapshotV1 {
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
    };
    let runtime_body_digest = reader.digest()?;
    let objective_semantic_bytes = {
        let length = reader.len()?;
        if length == 0 || length > MAX_OBJECTIVE_SEMANTIC_BYTES {
            return Err(RunStartStoreError::Corrupt);
        }
        reader.bytes(length)?.to_vec()
    };
    let (objective_function_v1_digest, objective_function_v1_bytes) = if require_protocol {
        let digest = reader.digest()?;
        let length = reader.len()?;
        if length == 0 || length > MAX_OBJECTIVE_PROTOCOL_BYTES {
            return Err(RunStartStoreError::Corrupt);
        }
        (digest, reader.bytes(length)?.to_vec())
    } else {
        (Digest32::ZERO, Vec::new())
    };
    let record = RunStartRecordV1 {
        authentication,
        admission,
        disposition,
        snapshot,
        runtime_body_digest,
        objective_semantic_bytes,
        objective_function_v1_digest,
        objective_function_v1_bytes,
    };
    if !reader.0.is_empty() || validate_record_compat(&record, require_protocol).is_err() {
        return Err(RunStartStoreError::Corrupt);
    }
    Ok(record)
}

fn decode_conflict_record(input: &[u8]) -> Result<RunStartConflictRecordV1, RunStartStoreError> {
    let input = input
        .strip_prefix(CONFLICT_RECORD_DOMAIN)
        .ok_or(RunStartStoreError::Corrupt)?;
    let mut reader = Reader(input);
    let authentication = RunStartAuthenticationV1 {
        issuer_id: reader.id()?,
        key_epoch: reader.u64()?,
        message_id: reader.id()?,
        sequence: reader.u64()?,
        expires_at_ms: reader.u64()?,
        scope_digest: reader.digest()?,
        signed_body_digest: reader.digest()?,
        signature: reader
            .bytes(64)?
            .try_into()
            .map_err(|_| RunStartStoreError::Corrupt)?,
    };
    let admission = RunStartAdmissionBindingV1 {
        profile_id: reader.id()?,
        profile_revision: reader.u64()?,
        profile_digest: reader.digest()?,
        supplied_source_digest: reader.digest()?,
        intent_digest: reader.digest()?,
        admitted_source_digest: reader.digest()?,
        observed_at_unix_micros: reader.u64()?,
        deadline_unix_micros: reader.u64()?,
        authority: reader.authority()?,
    };
    let record = RunStartConflictRecordV1 {
        authentication,
        admission,
        run_id: reader.id()?,
        runtime_body_digest: reader.digest()?,
        conflict_digest: reader.digest()?,
        conflict_receipt_bytes: {
            let length = reader.len()?;
            if length == 0 || length > MAX_OBJECTIVE_SEMANTIC_BYTES {
                return Err(RunStartStoreError::Corrupt);
            }
            reader.bytes(length)?.to_vec()
        },
    };
    if !reader.0.is_empty() || validate_conflict_record(&record).is_err() {
        return Err(RunStartStoreError::Corrupt);
    }
    Ok(record)
}

fn decode_outcome_record(input: &[u8]) -> Result<StoredRunStartRecord, RunStartStoreError> {
    if input.starts_with(RECORD_DOMAIN) || input.starts_with(RECORD_DOMAIN_V1) {
        return decode_record(input).map(|record| StoredRunStartRecord::Run(Box::new(record)));
    }
    if input.starts_with(CONFLICT_RECORD_DOMAIN) {
        return decode_conflict_record(input)
            .map(|record| StoredRunStartRecord::Conflict(Box::new(record)));
    }
    Err(RunStartStoreError::Corrupt)
}

fn encode_frame(stored: &StoredRunStart) -> Result<Vec<u8>, RunStartStoreError> {
    let payload = encode_outcome_record(&stored.record);
    if payload.len() > MAX_RUN_START_PAYLOAD_BYTES {
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
        if size == 0 || (size as u32) != !complement || size > MAX_RUN_START_PAYLOAD_BYTES {
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
        let record = decode_outcome_record(&frame[48..payload_end])?;
        if by_run.contains_key(record.run_id()) {
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
        by_run.insert(record.run_id().clone(), index);
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

fn push_authority(bytes: &mut Vec<u8>, authority: AuthorityPosture) {
    let flags = authority.flags();
    for value in [
        flags.runtime,
        flags.production_writer,
        flags.model_invocation,
        flags.provider_dispatch,
        flags.external_effect,
        flags.selection,
        flags.promotion,
        flags.release,
    ] {
        bytes.push(u8::from(value));
    }
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
    fn authority(&mut self) -> Result<AuthorityPosture, RunStartStoreError> {
        let values = self.take::<8>()?;
        if values.iter().any(|value| *value > 1) {
            return Err(RunStartStoreError::Corrupt);
        }
        AuthorityPosture::try_from_flags(AuthorityFlagsV1 {
            runtime: values[0] != 0,
            production_writer: values[1] != 0,
            model_invocation: values[2] != 0,
            provider_dispatch: values[3] != 0,
            external_effect: values[4] != 0,
            selection: values[5] != 0,
            promotion: values[6] != 0,
            release: values[7] != 0,
        })
        .map_err(|_| RunStartStoreError::Corrupt)
    }
    fn len(&mut self) -> Result<usize, RunStartStoreError> {
        Ok(u32::from_be_bytes(self.take()?) as usize)
    }
}

#[cfg(test)]
#[path = "run_start_tests.rs"]
mod tests;
