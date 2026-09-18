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

use codec::StoredPublicationBody;

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
        let body = StoredPublicationBody::from_typed(&admission, &objective, &run_start);
        let payload =
            serde_json::to_vec(&body).map_err(|_| ObjectivePublicationStoreErrorV1::Corrupt)?;
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
