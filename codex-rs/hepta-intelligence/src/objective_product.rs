//! Product caller and durable publication boundary for authenticated objectives.
//!
//! The compiler remains stateless. This module is the named owning caller that
//! atomically publishes the admitted compile receipt and its `RunStartSnapshotV1`
//! into one host-authorized append-only file. It opens no path and grants no
//! runtime or effect authority by itself.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;

use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionError;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveAdmissionReceiptV1;
use codex_hepta_objective::ObjectiveCompileReceipt;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_objective::admit_objective_v1;
use codex_hepta_objective::compile_admitted_objective_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[path = "objective_product_codec.rs"]
mod codec;


const MAGIC: &[u8; 8] = b"HEPTOB01";
const HEADER_BYTES: usize = 72;
const FRAME_FIXED_BYTES: usize = 112;
const MAX_RECORDS: usize = 4096;
const MAX_PAYLOAD_BYTES: usize = 512 * 1024;
const MAX_STORE_BYTES: u64 = 64 * 1024 * 1024;
const PUBLICATION_CHAIN_DOMAIN: &[u8] = b"hepta.intelligence.objective-publication-chain.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartBindingsV1 {
    pub run_id: StableId,
    pub preference_state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub prompt_registry_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
}

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

impl RunStartSnapshotV1 {
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.run-start-snapshot.v1".to_vec();
        push_text(&mut bytes, self.run_id.as_str());
        bytes.extend_from_slice(self.objective_digest.as_array());
        bytes.extend_from_slice(self.hard_constraint_digest.as_array());
        bytes.extend_from_slice(self.preference_state_digest.as_array());
        bytes.extend_from_slice(self.model_tuple_digest.as_array());
        bytes.extend_from_slice(self.prompt_registry_digest.as_array());
        bytes.extend_from_slice(self.artifact_set_digest.as_array());
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.generation.to_be_bytes());
        bytes.extend_from_slice(self.fence_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveProductRequestV1 {
    pub envelope: ObjectiveSourceEnvelopeV1,
    pub profile: ObjectiveAdmissionProfileV1,
    pub context: ObjectiveAdmissionContextV1,
    pub run: RunStartBindingsV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectivePublicationV1 {
    pub sequence: u64,
    pub predecessor_chain_digest: Digest32,
    pub admission: ObjectiveAdmissionReceiptV1,
    pub objective: ObjectiveCompileReceipt,
    pub run_start: RunStartSnapshotV1,
    pub publication_digest: Digest32,
    pub chain_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectivePublicationDispositionV1 {
    Appended,
    IdempotentReplay,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveProductReceiptV1 {
    pub publication: ObjectivePublicationV1,
    pub disposition: ObjectivePublicationDispositionV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ObjectivePublicationAnchorV1 {
    pub sequence: u64,
    pub chain_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectivePublicationRecoveryV1 {
    Unacknowledged,
    Acknowledged(ObjectivePublicationAnchorV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectivePublicationStoreErrorV1 {
    InvalidBinding,
    InvalidLimit,
    InvalidAnchor,
    Busy,
    NotRegular,
    AlreadyInitialized,
    MissingHeader,
    BindingMismatch,
    MissingAcknowledgedHistory,
    AnchorMismatch,
    Corrupt,
    Conflict,
    Capacity,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
}

impl fmt::Display for ObjectivePublicationStoreErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ObjectivePublicationStoreErrorV1 {}

impl From<io::Error> for ObjectivePublicationStoreErrorV1 {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

#[derive(Debug)]
pub enum ObjectiveProductErrorV1 {
    Admission(ObjectiveAdmissionError),
    ObjectiveConflict(Digest32),
    InvalidRunBinding(&'static str),
    Store(ObjectivePublicationStoreErrorV1),
}

impl fmt::Display for ObjectiveProductErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ObjectiveProductErrorV1 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Admission(error) => Some(error),
            Self::Store(error) => Some(error),
            Self::ObjectiveConflict(_) | Self::InvalidRunBinding(_) => None,
        }
    }
}

impl From<ObjectiveAdmissionError> for ObjectiveProductErrorV1 {
    fn from(value: ObjectiveAdmissionError) -> Self {
        Self::Admission(value)
    }
}

impl From<ObjectivePublicationStoreErrorV1> for ObjectiveProductErrorV1 {
    fn from(value: ObjectivePublicationStoreErrorV1) -> Self {
        Self::Store(value)
    }
}

pub struct ObjectiveProductCallerV1 {
    store: DurableObjectivePublicationStoreV1,
}

impl ObjectiveProductCallerV1 {
    pub fn create(
        file: File,
        binding: Digest32,
        max_records: usize,
    ) -> Result<Self, ObjectivePublicationStoreErrorV1> {
        Ok(Self {
            store: DurableObjectivePublicationStoreV1::create(file, binding, max_records)?,
        })
    }

    pub fn recover(
        file: File,
        binding: Digest32,
        max_records: usize,
        recovery: ObjectivePublicationRecoveryV1,
    ) -> Result<Self, ObjectivePublicationStoreErrorV1> {
        Ok(Self {
            store: DurableObjectivePublicationStoreV1::recover(
                file,
                binding,
                max_records,
                recovery,
            )?,
        })
    }

    pub fn admit_compile_publish(
        &mut self,
        request: ObjectiveProductRequestV1,
    ) -> Result<ObjectiveProductReceiptV1, ObjectiveProductErrorV1> {
        validate_run_bindings(&request.run)?;
        let admitted = admit_objective_v1(&request.envelope, &request.profile, &request.context)?;
        let admission = admitted.receipt().clone();
        let outcome = compile_admitted_objective_v1(admitted)?;
        let objective = outcome
            .compile_result
            .map_err(|conflict| ObjectiveProductErrorV1::ObjectiveConflict(conflict.conflict_digest))?;
        let run_start = RunStartSnapshotV1 {
            run_id: request.run.run_id,
            objective_digest: objective.objective.semantic_digest,
            hard_constraint_digest: objective.objective.hard_constraint_digest,
            preference_state_digest: request.run.preference_state_digest,
            model_tuple_digest: request.run.model_tuple_digest,
            prompt_registry_digest: request.run.prompt_registry_digest,
            artifact_set_digest: request.run.artifact_set_digest,
            authority_epoch: request.run.authority_epoch,
            generation: request.run.generation,
            fence_digest: request.run.fence_digest,
        };
        let (publication, disposition) =
            self.store.publish(admission, objective, run_start)?;
        Ok(ObjectiveProductReceiptV1 {
            publication,
            disposition,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub fn records(
        &self,
    ) -> Result<&[ObjectivePublicationV1], ObjectivePublicationStoreErrorV1> {
        self.store.records()
    }

    pub fn publication_for_run(
        &self,
        run_id: &StableId,
    ) -> Result<Option<&ObjectivePublicationV1>, ObjectivePublicationStoreErrorV1> {
        self.store.publication_for_run(run_id)
    }

    pub fn anchor(&self) -> Result<ObjectivePublicationAnchorV1, ObjectivePublicationStoreErrorV1> {
        self.store.anchor()
    }
}

pub struct DurableObjectivePublicationStoreV1 {
    file: LockedFile,
    records: Vec<ObjectivePublicationV1>,
    max_records: usize,
    durable_length: u64,
    poisoned: bool,
}

impl DurableObjectivePublicationStoreV1 {
    pub fn create(
        file: File,
        binding: Digest32,
        max_records: usize,
    ) -> Result<Self, ObjectivePublicationStoreErrorV1> {
        validate_store_domain(binding, max_records)?;
        let mut file = LockedFile::acquire(file)?;
        if file.metadata()?.len() != 0 {
            return Err(ObjectivePublicationStoreErrorV1::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| ObjectivePublicationStoreErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            records: Vec::new(),
            max_records,
            durable_length: HEADER_BYTES as u64,
            poisoned: false,
        })
    }

    pub fn recover(
        file: File,
        binding: Digest32,
        max_records: usize,
        recovery: ObjectivePublicationRecoveryV1,
    ) -> Result<Self, ObjectivePublicationStoreErrorV1> {
        validate_store_domain(binding, max_records)?;
        validate_recovery(recovery, max_records)?;
        let mut file = LockedFile::acquire(file)?;
        let (records, cursor, length) = replay(&mut file, binding, max_records)?;
        validate_anchor(&records, recovery)?;
        if cursor != length {
            file.set_len(cursor)
                .map_err(|_| ObjectivePublicationStoreErrorV1::Indeterminate)?;
        }
        file.sync_all()
            .map_err(|_| ObjectivePublicationStoreErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            records,
            max_records,
            durable_length: cursor,
            poisoned: false,
        })
    }

    fn publish(
        &mut self,
        admission: ObjectiveAdmissionReceiptV1,
        objective: ObjectiveCompileReceipt,
        run_start: RunStartSnapshotV1,
    ) -> Result<
        (ObjectivePublicationV1, ObjectivePublicationDispositionV1),
        ObjectivePublicationStoreErrorV1,
    > {
        if self.poisoned {
            return Err(ObjectivePublicationStoreErrorV1::Poisoned);
        }
        validate_publication_semantics(&admission, &objective, &run_start)?;
        let payload = codec::encode_publication(&admission, &objective, &run_start)?;
        if payload.len() > MAX_PAYLOAD_BYTES {
            return Err(ObjectivePublicationStoreErrorV1::Capacity);
        }
        let publication_digest = Digest32::of_bytes(&payload);

        for existing in &self.records {
            if existing.run_start.run_id == run_start.run_id {
                if existing.publication_digest == publication_digest {
                    return Ok((
                        existing.clone(),
                        ObjectivePublicationDispositionV1::IdempotentReplay,
                    ));
                }
                return Err(ObjectivePublicationStoreErrorV1::Conflict);
            }
            if existing.objective.objective.request_id == objective.objective.request_id
                && existing.objective.objective.revision == objective.objective.revision
                && (existing.objective.objective.semantic_digest
                    != objective.objective.semantic_digest
                    || existing.admission.intent_digest != admission.intent_digest
                    || existing.admission.profile_digest != admission.profile_digest
                    || existing.admission.admitted_source_digest != admission.admitted_source_digest)
            {
                return Err(ObjectivePublicationStoreErrorV1::Conflict);
            }
        }
        if self.records.len() >= self.max_records {
            return Err(ObjectivePublicationStoreErrorV1::Capacity);
        }

        let sequence = self.records.len() as u64 + 1;
        let predecessor_chain_digest = self
            .records
            .last()
            .map_or(Digest32::ZERO, |record| record.chain_digest);
        let chain_digest =
            publication_chain_digest(sequence, predecessor_chain_digest, publication_digest);
        let frame = encode_frame(
            sequence,
            predecessor_chain_digest,

            publication_digest,
            chain_digest,
            &payload,
        )?;
        let next_length = self
            .durable_length
            .checked_add(frame.len() as u64)
            .ok_or(ObjectivePublicationStoreErrorV1::Capacity)?;
        if next_length > MAX_STORE_BYTES {
            return Err(ObjectivePublicationStoreErrorV1::Capacity);
        }

        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.durable_length {
            return Err(ObjectivePublicationStoreErrorV1::Corrupt);
        }
        self.file
            .write_all(&frame)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| ObjectivePublicationStoreErrorV1::Indeterminate)?;

        let publication = ObjectivePublicationV1 {
            sequence,
            predecessor_chain_digest,
            admission,
            objective,
            run_start,
            publication_digest,
            chain_digest,
        };
        self.records.push(publication.clone());
        self.durable_length = next_length;
        self.poisoned = false;
        Ok((publication, ObjectivePublicationDispositionV1::Appended))
    }

    pub fn records(
        &self,
    ) -> Result<&[ObjectivePublicationV1], ObjectivePublicationStoreErrorV1> {
        if self.poisoned {
            Err(ObjectivePublicationStoreErrorV1::Poisoned)
        } else {
            Ok(&self.records)
        }
    }

    pub fn publication_for_run(
        &self,
        run_id: &StableId,
    ) -> Result<Option<&ObjectivePublicationV1>, ObjectivePublicationStoreErrorV1> {
        Ok(self
            .records()?
            .iter()
            .find(|record| &record.run_start.run_id == run_id))
    }

    pub fn anchor(&self) -> Result<ObjectivePublicationAnchorV1, ObjectivePublicationStoreErrorV1> {
        let records = self.records()?;
        Ok(ObjectivePublicationAnchorV1 {
            sequence: records.len() as u64,
            chain_digest: records
                .last()
                .map_or(Digest32::ZERO, |record| record.chain_digest),
        })
    }
}

fn validate_run_bindings(run: &RunStartBindingsV1) -> Result<(), ObjectiveProductErrorV1> {
    if run.run_id.as_str().is_empty() {
        return Err(ObjectiveProductErrorV1::InvalidRunBinding("run id"));
    }
    for (name, digest) in [
        ("preference state", run.preference_state_digest),
        ("model tuple", run.model_tuple_digest),
        ("prompt registry", run.prompt_registry_digest),
        ("artifact set", run.artifact_set_digest),
        ("fence", run.fence_digest),
    ] {
        if digest.is_zero() {
            return Err(ObjectiveProductErrorV1::InvalidRunBinding(name));
        }
    }
    if run.authority_epoch == 0 {
        return Err(ObjectiveProductErrorV1::InvalidRunBinding("authority epoch"));
    }
    if run.generation == 0 {
        return Err(ObjectiveProductErrorV1::InvalidRunBinding("generation"));
    }
    Ok(())
}

fn validate_publication_semantics(
    admission: &ObjectiveAdmissionReceiptV1,
    objective: &ObjectiveCompileReceipt,
    run_start: &RunStartSnapshotV1,
) -> Result<(), ObjectivePublicationStoreErrorV1> {
    if admission.authority.grants_any()
        || admission.profile_digest.is_zero()
        || admission.intent_digest.is_zero()
        || admission.admitted_source_digest.is_zero()
        || objective.objective.semantic_digest.is_zero()
        || objective.objective.hard_constraint_digest.is_zero()
        || run_start.objective_digest != objective.objective.semantic_digest
        || run_start.hard_constraint_digest != objective.objective.hard_constraint_digest
        || run_start.preference_state_digest.is_zero()
        || run_start.model_tuple_digest.is_zero()
        || run_start.prompt_registry_digest.is_zero()
        || run_start.artifact_set_digest.is_zero()
        || run_start.fence_digest.is_zero()
        || run_start.authority_epoch == 0
        || run_start.generation == 0
    {
        return Err(ObjectivePublicationStoreErrorV1::Corrupt);
    }
    Ok(())
}

fn validate_store_domain(
    binding: Digest32,
    max_records: usize,
) -> Result<(), ObjectivePublicationStoreErrorV1> {
    if binding.is_zero() {
        return Err(ObjectivePublicationStoreErrorV1::InvalidBinding);
    }
    if !(1..=MAX_RECORDS).contains(&max_records) {
        return Err(ObjectivePublicationStoreErrorV1::InvalidLimit);
    }
    Ok(())
}

fn validate_recovery(
    recovery: ObjectivePublicationRecoveryV1,
    max_records: usize,
) -> Result<(), ObjectivePublicationStoreErrorV1> {
    if let ObjectivePublicationRecoveryV1::Acknowledged(anchor) = recovery
        && (anchor.sequence == 0
            || anchor.sequence > max_records as u64
            || anchor.chain_digest.is_zero())
    {
        return Err(ObjectivePublicationStoreErrorV1::InvalidAnchor);
    }
    Ok(())
}

fn validate_anchor(
    records: &[ObjectivePublicationV1],
    recovery: ObjectivePublicationRecoveryV1,
) -> Result<(), ObjectivePublicationStoreErrorV1> {
    let ObjectivePublicationRecoveryV1::Acknowledged(anchor) = recovery else {
        return Ok(());
    };
    let record = records
        .get((anchor.sequence - 1) as usize)
        .ok_or(ObjectivePublicationStoreErrorV1::MissingAcknowledgedHistory)?;
    if record.chain_digest != anchor.chain_digest {
        return Err(ObjectivePublicationStoreErrorV1::AnchorMismatch);
    }
    Ok(())
}

fn replay(
    file: &mut File,
    binding: Digest32,
    max_records: usize,
) -> Result<(Vec<ObjectivePublicationV1>, u64, u64), ObjectivePublicationStoreErrorV1> {
    let length = file.metadata()?.len();
    if length < HEADER_BYTES as u64 {
        return Err(ObjectivePublicationStoreErrorV1::MissingHeader);
    }
    if length > MAX_STORE_BYTES {
        return Err(ObjectivePublicationStoreErrorV1::Capacity);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut header = [0_u8; HEADER_BYTES];
    file.read_exact(&mut header)?;
    if &header[..8] != MAGIC
        || &header[8..40] != binding.as_array()
        || &header[40..] != Digest32::of_bytes(&header[..40]).as_array()
    {
        return if &header[8..40] != binding.as_array() {
            Err(ObjectivePublicationStoreErrorV1::BindingMismatch)
        } else {
            Err(ObjectivePublicationStoreErrorV1::Corrupt)
        };
    }

    let mut records = Vec::new();
    let mut cursor = HEADER_BYTES as u64;
    let mut head = Digest32::ZERO;
    while cursor < length {
        if length - cursor < FRAME_FIXED_BYTES as u64 {
            break;
        }
        let mut fixed = [0_u8; 48];
        file.read_exact(&mut fixed)?;
        let payload_len = u32::from_be_bytes(
            fixed[..4]
                .try_into()
                .map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)?,
        );

        let complement = u32::from_be_bytes(
            fixed[4..8]
                .try_into()
                .map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)?,
        );
        if payload_len != !complement
            || payload_len == 0
            || payload_len as usize > MAX_PAYLOAD_BYTES
        {
            return Err(ObjectivePublicationStoreErrorV1::Corrupt);
        }
        let sequence = u64::from_be_bytes(
            fixed[8..16]
                .try_into()
                .map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)?,
        );
        let predecessor_chain_digest = digest_from_slice(&fixed[16..48])?;
        let frame_len = FRAME_FIXED_BYTES
            .checked_add(payload_len as usize)
            .ok_or(ObjectivePublicationStoreErrorV1::Capacity)?;
        if length - cursor < frame_len as u64 {
            break;
        }
        if records.len() >= max_records
            || sequence != records.len() as u64 + 1
            || predecessor_chain_digest != head
        {
            return Err(ObjectivePublicationStoreErrorV1::Corrupt);
        }
        let mut payload = vec![0_u8; payload_len as usize];
        file.read_exact(&mut payload)?;
        let mut trailer = [0_u8; 64];
        file.read_exact(&mut trailer)?;
        let publication_digest = digest_from_slice(&trailer[..32])?;
        let chain_digest = digest_from_slice(&trailer[32..])?;
        if publication_digest != Digest32::of_bytes(&payload)
            || chain_digest
                != publication_chain_digest(
                    sequence,
                    predecessor_chain_digest,
                    publication_digest,
                )
        {
            return Err(ObjectivePublicationStoreErrorV1::Corrupt);
        }
        let (admission, objective, run_start) = codec::decode_publication(&payload)?;
        validate_publication_semantics(&admission, &objective, &run_start)?;
        let record = ObjectivePublicationV1 {
            sequence,
            predecessor_chain_digest,
            admission,
            objective,
            run_start,
            publication_digest,
            chain_digest,
        };
        validate_replayed_identity(&records, &record)?;
        head = chain_digest;
        records.push(record);
        cursor += frame_len as u64;
    }
    Ok((records, cursor, length))
}

fn validate_replayed_identity(
    records: &[ObjectivePublicationV1],
    candidate: &ObjectivePublicationV1,
) -> Result<(), ObjectivePublicationStoreErrorV1> {
    for existing in records {
        if existing.run_start.run_id == candidate.run_start.run_id {
            return Err(ObjectivePublicationStoreErrorV1::Corrupt);
        }
        if existing.objective.objective.request_id == candidate.objective.objective.request_id
            && existing.objective.objective.revision == candidate.objective.objective.revision
            && (existing.objective.objective.semantic_digest
                != candidate.objective.objective.semantic_digest
                || existing.admission.intent_digest != candidate.admission.intent_digest
                || existing.admission.profile_digest != candidate.admission.profile_digest
                || existing.admission.admitted_source_digest
                    != candidate.admission.admitted_source_digest)
        {
            return Err(ObjectivePublicationStoreErrorV1::Corrupt);
        }
    }
    Ok(())
}

fn encode_frame(
    sequence: u64,
    predecessor: Digest32,
    publication_digest: Digest32,
    chain_digest: Digest32,
    payload: &[u8],
) -> Result<Vec<u8>, ObjectivePublicationStoreErrorV1> {
    let size =
        u32::try_from(payload.len()).map_err(|_| ObjectivePublicationStoreErrorV1::Capacity)?;
    let mut frame = Vec::with_capacity(FRAME_FIXED_BYTES + payload.len());
    frame.extend_from_slice(&size.to_be_bytes());
    frame.extend_from_slice(&(!size).to_be_bytes());
    frame.extend_from_slice(&sequence.to_be_bytes());
    frame.extend_from_slice(predecessor.as_array());
    frame.extend_from_slice(payload);
    frame.extend_from_slice(publication_digest.as_array());
    frame.extend_from_slice(chain_digest.as_array());
    Ok(frame)
}

fn publication_chain_digest(
    sequence: u64,
    predecessor: Digest32,
    publication_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::with_capacity(PUBLICATION_CHAIN_DOMAIN.len() + 72);
    bytes.extend_from_slice(PUBLICATION_CHAIN_DOMAIN);
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(publication_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_from_slice(bytes: &[u8]) -> Result<Digest32, ObjectivePublicationStoreErrorV1> {
    let array: [u8; 32] = bytes
        .try_into()
        .map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)?;
    Ok(Digest32::from_array(array))
}

struct LockedFile(File);

impl LockedFile {
    fn acquire(file: File) -> Result<Self, ObjectivePublicationStoreErrorV1> {
        if !file.metadata()?.is_file() {
            return Err(ObjectivePublicationStoreErrorV1::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(ObjectivePublicationStoreErrorV1::Busy),
            Err(TryLockError::Error(error)) => Err(ObjectivePublicationStoreErrorV1::Io(error.kind())),
        }
    }
}

impl Deref for LockedFile {
    type Target = File;

    fn deref(&self) -> &File {
        &self.0
    }
}

impl DerefMut for LockedFile {
    fn deref_mut(&mut self) -> &mut File {
        &mut self.0
    }
}

impl Drop for LockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    let length = u32::try_from(value.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
#[path = "objective_product_tests.rs"]
mod tests;
