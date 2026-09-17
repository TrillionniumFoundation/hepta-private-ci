//! Prompt registry domain model and immutable receipt types.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

const ADMISSION_RECORD_DOMAIN: &[u8] = b"hepta.prompt-registry.admission-record.v1";
const LIFECYCLE_EVENT_DOMAIN: &[u8] = b"hepta.prompt-registry.lifecycle-event.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FactorSource {
    GovernedInternal,
    ExternalUntrusted,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Lifecycle {
    Draft,
    Admitted,
    Retired,
    Revoked,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptFactor {
    pub factor_id: StableId,
    pub proposer_id: StableId,
    pub semantic_version: StableId,
    pub content_digest: Digest32,
    pub source: FactorSource,
    pub lifecycle: Lifecycle,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRealization {
    pub realization_id: StableId,
    pub factor_id: StableId,
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub content_digest: Digest32,
    pub active: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmissionRequest {
    pub factor_id: StableId,
    pub reviewer_id: StableId,
    pub evidence_digest: Digest32,
    pub reviewed_scope_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FactorAdmissionRecord {
    pub factor_id: StableId,
    pub reviewer_id: StableId,
    pub evidence_digest: Digest32,
    pub reviewed_scope_digest: Digest32,
    pub revision: Revision,
    pub admission_digest: Digest32,
}

impl FactorAdmissionRecord {
    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ADMISSION_RECORD_DOMAIN);
        push_id(&mut bytes, &self.factor_id);
        push_id(&mut bytes, &self.reviewer_id);
        bytes.extend_from_slice(self.evidence_digest.as_array());
        bytes.extend_from_slice(self.reviewed_scope_digest.as_array());
        bytes.extend_from_slice(&self.revision.get().to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), Error> {
        if self.evidence_digest.is_zero() || self.reviewed_scope_digest.is_zero() {
            return Err(Error::EmptyDigest("admission lineage"));
        }
        if self.admission_digest != self.compute_digest() {
            return Err(Error::IntegrityMismatch("admission record"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LifecycleEventKind {
    Registered,
    Admitted,
    Retired,
    Revoked,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LifecycleEvent {
    pub factor_id: StableId,
    pub kind: LifecycleEventKind,
    pub from: Option<Lifecycle>,
    pub to: Lifecycle,
    pub revision: Revision,
    pub actor_id: StableId,
    pub evidence_digest: Option<Digest32>,
    pub reviewed_scope_digest: Option<Digest32>,
    pub reason_digest: Option<Digest32>,
    pub cutoff_unix_ms: Option<u64>,
    pub event_digest: Digest32,
}

impl LifecycleEvent {
    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(LIFECYCLE_EVENT_DOMAIN);
        push_id(&mut bytes, &self.factor_id);
        bytes.push(lifecycle_event_kind_code(self.kind));
        match self.from {
            Some(value) => {
                bytes.push(1);
                bytes.push(lifecycle_code(value));
            }
            None => bytes.push(0),
        }
        bytes.push(lifecycle_code(self.to));
        bytes.extend_from_slice(&self.revision.get().to_be_bytes());
        push_id(&mut bytes, &self.actor_id);
        push_optional_digest(&mut bytes, self.evidence_digest);
        push_optional_digest(&mut bytes, self.reviewed_scope_digest);
        push_optional_digest(&mut bytes, self.reason_digest);
        match self.cutoff_unix_ms {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(&value.to_be_bytes());
            }
            None => bytes.push(0),
        }
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), Error> {
        if self.event_digest != self.compute_digest() {
            return Err(Error::IntegrityMismatch("lifecycle event"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MutationDisposition {
    Inserted,
    Unchanged,
    Transitioned,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegistryReceipt {
    pub revision: Revision,
    pub disposition: MutationDisposition,
    pub registry_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    ZeroCapacity,
    CapacityExceeded,
    LifecycleHistoryCapacityExceeded,
    EmptyDigest(&'static str),
    FactorConflict(String),
    RealizationConflict(String),
    ActiveRealizationConflict(String),
    InvalidSupersession(String),
    FactorNotFound(String),
    FactorNotAdmitted(String),
    RealizationNotFound(String),
    ExternalSelfAdmission,
    SelfReview,
    AuthenticatedAdmissionRequired,
    LifecycleReasonRequired,
    InvalidTransition,
    RevisionOverflow,
    Authority(String),
    IntegrityMismatch(&'static str),
    PayloadRequired,
    PayloadTooLarge,
    PayloadCapacityExceeded,
    PayloadDigestMismatch,
    PayloadMissing(String),
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub(crate) fn lifecycle_event(
    factor_id: StableId,
    kind: LifecycleEventKind,
    from: Option<Lifecycle>,
    to: Lifecycle,
    revision: Revision,
    actor_id: StableId,
    evidence_digest: Option<Digest32>,
    reviewed_scope_digest: Option<Digest32>,
    reason_digest: Option<Digest32>,
    cutoff_unix_ms: Option<u64>,
) -> LifecycleEvent {
    let mut event = LifecycleEvent {
        factor_id,
        kind,
        from,
        to,
        revision,
        actor_id,
        evidence_digest,
        reviewed_scope_digest,
        reason_digest,
        cutoff_unix_ms,
        event_digest: Digest32::ZERO,
    };
    event.event_digest = event.compute_digest();
    event
}

pub(crate) fn lifecycle_code(lifecycle: Lifecycle) -> u8 {
    match lifecycle {
        Lifecycle::Draft => 0,
        Lifecycle::Admitted => 1,
        Lifecycle::Retired => 2,
        Lifecycle::Revoked => 3,
    }
}

fn lifecycle_event_kind_code(kind: LifecycleEventKind) -> u8 {
    match kind {
        LifecycleEventKind::Registered => 0,
        LifecycleEventKind::Admitted => 1,
        LifecycleEventKind::Retired => 2,
        LifecycleEventKind::Revoked => 3,
    }
}

pub(crate) fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
}
