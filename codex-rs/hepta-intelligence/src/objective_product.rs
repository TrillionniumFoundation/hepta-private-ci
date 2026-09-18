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
