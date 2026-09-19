//! Explicit append-only unlearning lineage facts.
//!
//! Logical revocation remains distinct from physical erasure. These records prove
//! that a derived surface was invalidated because of an already-revoked source;
//! they do not claim that bytes were physically erased or that a model forgot.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UnlearningDerivedKindV1 {
    Dataset,
    Artifact,
    Checkpoint,
    PromptGraph,
    SensorCore,
    Replay,
    Evaluation,
    Backup,
}

impl UnlearningDerivedKindV1 {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::Dataset => 0,
            Self::Artifact => 1,
            Self::Checkpoint => 2,
            Self::PromptGraph => 3,
            Self::SensorCore => 4,
            Self::Replay => 5,
            Self::Evaluation => 6,
            Self::Backup => 7,
        }
    }

    pub(crate) const fn from_tag(tag: u8) -> Option<Self> {
        match tag {
            0 => Some(Self::Dataset),
            1 => Some(Self::Artifact),
            2 => Some(Self::Checkpoint),
            3 => Some(Self::PromptGraph),
            4 => Some(Self::SensorCore),
            5 => Some(Self::Replay),
            6 => Some(Self::Evaluation),
            7 => Some(Self::Backup),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnlearningLineageEventV1 {
    pub record_id: StableId,
    pub source_record_id: StableId,
    pub derived_id: StableId,
    pub derived_kind: UnlearningDerivedKindV1,
    pub predecessor: Option<StableId>,
    pub upstream_derived_id: Option<StableId>,
    pub upstream_derived_digest: Option<Digest32>,
    pub authority_id: StableId,
    pub reason_digest: Digest32,
    pub source_digest: Digest32,
    pub derived_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnlearningLineageReceiptV1 {
    pub record_id: StableId,
    pub source_record_id: StableId,
    pub derived_id: StableId,
    pub upstream_derived_id: Option<StableId>,
    pub event_digest: Digest32,
    pub chain_digest: Digest32,
}
