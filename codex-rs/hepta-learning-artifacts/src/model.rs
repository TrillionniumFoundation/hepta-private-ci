use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ArtifactKind {
    Prompt,
    Policy,
    Model,
    Workflow,
    Skill,
    Parameters,
    Topology,
    Code,
    ExternalAdapter,
}

impl ArtifactKind {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::Prompt => 0,
            Self::Policy => 1,
            Self::Model => 2,
            Self::Workflow => 3,
            Self::Skill => 4,
            Self::Parameters => 5,
            Self::Topology => 6,
            Self::Code => 7,
            Self::ExternalAdapter => 8,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LineageDisposition {
    Genesis,
    Derived,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactManifest {
    pub artifact_id: StableId,
    pub kind: ArtifactKind,
    pub generation: Generation,
    pub predecessor_id: Option<StableId>,
    pub content_digest: Digest32,
    pub objective_digest: Digest32,
    pub support_digest: Digest32,
    pub producer_id: StableId,
    pub compatibility_digest: Digest32,
    pub encoded_size_bytes: u64,
}

impl ArtifactManifest {
    #[must_use]
    pub const fn lineage_disposition(&self) -> LineageDisposition {
        if self.predecessor_id.is_some() {
            LineageDisposition::Derived
        } else {
            LineageDisposition::Genesis
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactState {
    Candidate,
    Quarantined,
    Revoked,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StateChange {
    pub event_id: StableId,
    pub artifact_id: StableId,
    pub evaluator_id: StableId,
    pub reason_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactEvent {
    Register {
        event_id: StableId,
        manifest: ArtifactManifest,
    },
    Quarantine(StateChange),
    Revoke(StateChange),
}

impl ArtifactEvent {
    pub(crate) fn event_id(&self) -> &StableId {
        match self {
            Self::Register { event_id, .. } => event_id,
            Self::Quarantine(value) | Self::Revoke(value) => &value.event_id,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactRecord {
    pub sequence: LogicalSequence,
    pub predecessor_chain_digest: Digest32,
    pub event_digest: Digest32,
    pub chain_digest: Digest32,
    pub event: ArtifactEvent,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RegistryAppendDisposition {
    Appended,
    IdempotentReplay,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegistryAppendReceipt {
    pub disposition: RegistryAppendDisposition,
    pub sequence: LogicalSequence,
    pub event_digest: Digest32,
    pub chain_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactRegistrySnapshot {
    pub(crate) records: Vec<ArtifactRecord>,
    pub head_digest: Digest32,
}

impl ArtifactRegistrySnapshot {
    #[must_use]
    pub fn records(&self) -> &[ArtifactRecord] {
        &self.records
    }
}
