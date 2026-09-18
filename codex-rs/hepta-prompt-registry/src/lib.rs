//! Governed prompt-factor and realization registry.
//!
//! The registry stores bounded identities and content digests, never executable
//! instructions or ambient authority. External untrusted material cannot admit
//! itself, and revocation is terminal and cascades to realizations.

#![forbid(unsafe_code)]

mod admission;
mod delivery;
mod durable;
mod protocol;
mod v2;

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

pub use admission::AdmissionAuthority;
pub use admission::AdmissionBindingV1;
pub use admission::AdmissionError;
pub use admission::AdmissionGrantV1;
pub use admission::FinalUseAdmissionAuthority;
pub use admission::SignedAdmissionGrantV1;
pub use admission::VerifiedAdmission;
pub use admission::final_use_admission_binding;
pub use delivery::MAX_REALIZATION_PAYLOAD_BYTES;
pub use delivery::RealizationDeliveryV2;
pub use durable::DurablePromptRegistry;
pub use durable::DurableRegistryError;
pub use protocol::PromptFactorV1;
pub use protocol::PromptRealizationV1;
pub use protocol::ProtocolCodecError;
pub use v2::CompatibleRealizationSetV2;
pub use v2::MAX_COMPATIBLE_REALIZATIONS_V2;
pub use v2::PromptModelTupleV2;
pub use v2::PromptRealizationBindingV2;
pub use v2::PromptRegistrySnapshotV2;
pub use v2::PromptRegistryV2Error;
pub use v2::PromptRoleV2;

const MAX_RECORDS: usize = 16_384;

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
    EmptyDigest(&'static str),
    FactorConflict(String),
    RealizationConflict(String),
    RealizationProfileConflict(String),
    PayloadTooLarge,
    PayloadDigestMismatch,
    FactorNotFound(String),
    FactorNotAdmitted(String),
    ExternalSelfAdmission,
    SelfReview,
    InvalidTransition,
    RevisionOverflow,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LifecycleEventKind {
    Registered,
    Admitted,
    Retired,
    Revoked,
    Imported,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LifecycleEvent {
    pub revision: Revision,
    pub factor_id: StableId,
    pub kind: LifecycleEventKind,
    pub from: Option<Lifecycle>,
    pub to: Lifecycle,
    pub actor_id: StableId,
    pub admission_grant_id: Option<StableId>,
    pub evidence_digest: Digest32,
    pub scope_digest: Option<Digest32>,
    pub reason_digest: Option<Digest32>,
    pub cutoff_unix_ms: Option<u64>,
    pub event_digest: Digest32,
}

impl LifecycleEvent {
    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-factor-lifecycle.event.v1".to_vec();
        bytes.extend_from_slice(&self.revision.get().to_be_bytes());
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
        push_id(&mut bytes, &self.actor_id);
        push_optional_id(&mut bytes, self.admission_grant_id.as_ref());
        bytes.extend_from_slice(self.evidence_digest.as_array());
        push_optional_digest(&mut bytes, self.scope_digest);
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
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistry {
    factors: BTreeMap<StableId, PromptFactor>,
    realizations: BTreeMap<StableId, PromptRealization>,
    realization_bindings: BTreeMap<StableId, PromptRealizationBindingV2>,
    realization_payloads: BTreeMap<StableId, Vec<u8>>,
    realization_supersessions: BTreeMap<StableId, StableId>,
    lifecycle_events: Vec<LifecycleEvent>,
    revision: Revision,
    lifecycle_frontier: u64,
    revocation_frontier: u64,
    maximum_records: usize,
}

impl PromptRegistry {
    pub(crate) fn new(maximum_records: usize) -> Result<Self, Error> {
        if maximum_records == 0 {
            return Err(Error::ZeroCapacity);
        }
        let Ok(revision) = Revision::new(/*value*/ 1) else {
            return Err(Error::RevisionOverflow);
        };
        Ok(Self {
            factors: BTreeMap::new(),
            realizations: BTreeMap::new(),
            realization_bindings: BTreeMap::new(),
            realization_payloads: BTreeMap::new(),
            realization_supersessions: BTreeMap::new(),
            lifecycle_events: Vec::new(),
            revision,
            lifecycle_frontier: 0,
            revocation_frontier: 0,
            maximum_records: maximum_records.min(MAX_RECORDS),
        })
    }

    pub(crate) fn register_factor(
        &mut self,
        factor: PromptFactor,
    ) -> Result<RegistryReceipt, Error> {
        if factor.content_digest.is_zero() {
            return Err(Error::EmptyDigest("factor content"));
        }
        if factor.lifecycle != Lifecycle::Draft {
            return Err(Error::InvalidTransition);
        }
        if let Some(existing) = self.factors.get(&factor.factor_id) {
            if existing == &factor {
                return Ok(self.receipt(MutationDisposition::Unchanged));
            }
            return Err(Error::FactorConflict(factor.factor_id.to_string()));
        }
        self.ensure_capacity(/*additional*/ 1)?;
        let next_revision = self.next_revision()?;
        let event = lifecycle_event(
            next_revision,
            factor.factor_id.clone(),
            LifecycleEventKind::Registered,
            None,
            Lifecycle::Draft,
            factor.proposer_id.clone(),
            None,
            factor.content_digest,
            None,
            None,
            None,
        );
        self.factors.insert(factor.factor_id.clone(), factor);
        self.lifecycle_events.push(event);
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Inserted))
    }

    #[cfg(test)]
    pub(crate) fn admit_factor(
        &mut self,
        factor_id: &StableId,
        reviewer_id: &StableId,
        evidence_digest: Digest32,
    ) -> Result<RegistryReceipt, Error> {
        if evidence_digest.is_zero() {
            return Err(Error::EmptyDigest("admission evidence"));
        }
        let Some(factor) = self.factors.get(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        if factor.source == FactorSource::ExternalUntrusted {
            return Err(Error::ExternalSelfAdmission);
        }
        if &factor.proposer_id == reviewer_id {
            return Err(Error::SelfReview);
        }
        if factor.lifecycle != Lifecycle::Draft {
            return Err(Error::InvalidTransition);
        }
        let next_revision = self.next_revision()?;
        let Some(factor) = self.factors.get_mut(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        factor.lifecycle = Lifecycle::Admitted;
        let event = lifecycle_event(
            next_revision,
            factor_id.clone(),
            LifecycleEventKind::Admitted,
            Some(Lifecycle::Draft),
            Lifecycle::Admitted,
            reviewer_id.clone(),
            None,
            evidence_digest,
            None,
            None,
            None,
        );
        self.lifecycle_events.push(event);
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }

    pub(crate) fn admit_factor_verified(
        &mut self,
        admission: VerifiedAdmission,
        now_unix_ms: u64,
    ) -> Result<RegistryReceipt, Error> {
        if !admission.is_live_at(now_unix_ms) {
            return Err(Error::InvalidTransition);
        }
        let Some(factor) = self.factors.get(admission.factor_id()) else {
            return Err(Error::FactorNotFound(admission.factor_id().to_string()));
        };
        if factor.content_digest != admission.factor_content_digest() {
            return Err(Error::FactorConflict(admission.factor_id().to_string()));
        }
        if factor.lifecycle == Lifecycle::Admitted
            && self.lifecycle_events.iter().any(|event| {
                event.kind == LifecycleEventKind::Admitted
                    && event.factor_id == *admission.factor_id()
                    && event.admission_grant_id.as_ref() == Some(admission.grant_id())
            })
        {
            return Ok(self.receipt(MutationDisposition::Unchanged));
        }
        if factor.source != FactorSource::GovernedInternal
            || factor.lifecycle != Lifecycle::Draft
            || &factor.proposer_id == admission.reviewer_id()
        {
            return Err(Error::InvalidTransition);
        }
        let next_revision = self.next_revision()?;
        let factor_id = admission.factor_id().clone();
        let Some(factor) = self.factors.get_mut(&factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        factor.lifecycle = Lifecycle::Admitted;
        let event = lifecycle_event(
            next_revision,
            factor_id,
            LifecycleEventKind::Admitted,
            Some(Lifecycle::Draft),
            Lifecycle::Admitted,
            admission.reviewer_id().clone(),
            Some(admission.grant_id().clone()),
            admission.evidence_digest(),
            Some(admission.reviewed_scope_digest()),
            None,
            None,
        );
        self.lifecycle_events.push(event);
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }

    #[cfg(test)]
    pub(crate) fn register_realization(
        &mut self,
        realization: PromptRealization,
    ) -> Result<RegistryReceipt, Error> {
        for (name, value) in [
            ("model", realization.model_digest),
            ("tokenizer", realization.tokenizer_digest),
            ("realization content", realization.content_digest),
        ] {
            if value.is_zero() {
                return Err(Error::EmptyDigest(name));
            }
        }
        let Some(factor) = self.factors.get(&realization.factor_id) else {
            return Err(Error::FactorNotFound(realization.factor_id.to_string()));
        };
        if factor.lifecycle != Lifecycle::Admitted {
            return Err(Error::FactorNotAdmitted(realization.factor_id.to_string()));
        }
        if !realization.active {
            return Err(Error::InvalidTransition);
        }
        if let Some(existing) = self.realizations.get(&realization.realization_id) {
            if existing == &realization {
                return Ok(self.receipt(MutationDisposition::Unchanged));
            }
            return Err(Error::RealizationConflict(
                realization.realization_id.to_string(),
            ));
        }
        self.ensure_capacity(/*additional*/ 1)?;
        let next_revision = self.next_revision()?;
        self.realizations
            .insert(realization.realization_id.clone(), realization);
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Inserted))
    }

    #[cfg(test)]
    pub(crate) fn retire_factor(&mut self, factor_id: &StableId) -> Result<RegistryReceipt, Error> {
        let Some(factor) = self.factors.get(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        if factor.lifecycle != Lifecycle::Admitted {
            return Err(Error::InvalidTransition);
        }
        let actor_id = factor.proposer_id.clone();
        let evidence_digest = factor.content_digest;
        let next_revision = self.next_revision()?;
        let Some(factor) = self.factors.get_mut(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        factor.lifecycle = Lifecycle::Retired;
        self.disable_realizations(factor_id);
        let event = lifecycle_event(
            next_revision,
            factor_id.clone(),
            LifecycleEventKind::Retired,
            Some(Lifecycle::Admitted),
            Lifecycle::Retired,
            actor_id,
            None,
            evidence_digest,
            None,
            None,
            None,
        );
        self.lifecycle_events.push(event);
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }

    #[cfg(test)]
    pub(crate) fn revoke_factor(&mut self, factor_id: &StableId) -> Result<RegistryReceipt, Error> {
        let Some(factor) = self.factors.get(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        if factor.lifecycle == Lifecycle::Revoked {
            return Err(Error::InvalidTransition);
        }
        let from = factor.lifecycle;
        let actor_id = factor.proposer_id.clone();
        let evidence_digest = factor.content_digest;
        let next_revision = self.next_revision()?;
        let Some(factor) = self.factors.get_mut(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        factor.lifecycle = Lifecycle::Revoked;
        self.disable_realizations(factor_id);
        let event = lifecycle_event(
            next_revision,
            factor_id.clone(),
            LifecycleEventKind::Revoked,
            Some(from),
            Lifecycle::Revoked,
            actor_id,
            None,
            evidence_digest,
            None,
            None,
            None,
        );
        self.lifecycle_events.push(event);
        self.commit_revision(next_revision, /*revocation*/ true);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }

    pub(crate) fn retire_factor_governed(
        &mut self,
        factor_id: &StableId,
        actor_id: &StableId,
        reason_digest: Digest32,
    ) -> Result<RegistryReceipt, Error> {
        if reason_digest.is_zero() {
            return Err(Error::EmptyDigest("retirement reason"));
        }
        let Some(factor) = self.factors.get(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        if factor.lifecycle != Lifecycle::Admitted {
            return Err(Error::InvalidTransition);
        }
        let evidence_digest = factor.content_digest;
        let next_revision = self.next_revision()?;
        let Some(factor) = self.factors.get_mut(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        factor.lifecycle = Lifecycle::Retired;
        self.disable_realizations(factor_id);
        self.lifecycle_events.push(lifecycle_event(
            next_revision,
            factor_id.clone(),
            LifecycleEventKind::Retired,
            Some(Lifecycle::Admitted),
            Lifecycle::Retired,
            actor_id.clone(),
            None,
            evidence_digest,
            None,
            Some(reason_digest),
            None,
        ));
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }

    pub(crate) fn revoke_factor_governed(
        &mut self,
        factor_id: &StableId,
        actor_id: &StableId,
        reason_digest: Digest32,
        cutoff_unix_ms: u64,
    ) -> Result<RegistryReceipt, Error> {
        if reason_digest.is_zero() {
            return Err(Error::EmptyDigest("revocation reason"));
        }
        if cutoff_unix_ms == 0 {
            return Err(Error::InvalidTransition);
        }
        let Some(factor) = self.factors.get(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        if factor.lifecycle == Lifecycle::Revoked {
            return Err(Error::InvalidTransition);
        }
        let from = factor.lifecycle;
        let evidence_digest = factor.content_digest;
        let next_revision = self.next_revision()?;
        let Some(factor) = self.factors.get_mut(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        factor.lifecycle = Lifecycle::Revoked;
        self.disable_realizations(factor_id);
        self.lifecycle_events.push(lifecycle_event(
            next_revision,
            factor_id.clone(),
            LifecycleEventKind::Revoked,
            Some(from),
            Lifecycle::Revoked,
            actor_id.clone(),
            None,
            evidence_digest,
            None,
            Some(reason_digest),
            Some(cutoff_unix_ms),
        ));
        self.commit_revision(next_revision, /*revocation*/ true);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }

    pub fn factor(&self, factor_id: &StableId) -> Option<&PromptFactor> {
        self.factors.get(factor_id)
    }

    pub fn realization(&self, realization_id: &StableId) -> Option<&PromptRealization> {
        self.realizations.get(realization_id)
    }

    pub fn realization_binding(
        &self,
        realization_id: &StableId,
    ) -> Option<&PromptRealizationBindingV2> {
        self.realization_bindings.get(realization_id)
    }

    pub fn lifecycle_events(&self) -> &[LifecycleEvent] {
        &self.lifecycle_events
    }

    pub fn admission_event_digest(&self, factor_id: &StableId) -> Option<Digest32> {
        self.lifecycle_events
            .iter()
            .rev()
            .find(|event| {
                event.factor_id == *factor_id && event.kind == LifecycleEventKind::Admitted
            })
            .map(|event| event.event_digest)
    }

    #[must_use]
    pub const fn revision(&self) -> Revision {
        self.revision
    }

    #[must_use]
    pub const fn lifecycle_frontier(&self) -> u64 {
        self.lifecycle_frontier
    }

    #[must_use]
    pub const fn revocation_frontier(&self) -> u64 {
        self.revocation_frontier
    }

    pub fn snapshot_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.prompt-registry.snapshot.v1");
        bytes.extend_from_slice(&self.revision.get().to_be_bytes());
        bytes.extend_from_slice(&self.lifecycle_frontier.to_be_bytes());
        bytes.extend_from_slice(&self.revocation_frontier.to_be_bytes());
        for factor in self.factors.values() {
            push_id(&mut bytes, &factor.factor_id);
            push_id(&mut bytes, &factor.proposer_id);
            push_id(&mut bytes, &factor.semantic_version);
            bytes.extend_from_slice(factor.content_digest.as_array());
            bytes.push(match factor.source {
                FactorSource::GovernedInternal => 0,
                FactorSource::ExternalUntrusted => 1,
            });
            bytes.push(lifecycle_code(factor.lifecycle));
        }
        for realization in self.realizations.values() {
            push_id(&mut bytes, &realization.realization_id);
            push_id(&mut bytes, &realization.factor_id);
            bytes.extend_from_slice(realization.model_digest.as_array());
            bytes.extend_from_slice(realization.tokenizer_digest.as_array());
            bytes.extend_from_slice(realization.content_digest.as_array());
            bytes.push(u8::from(realization.active));
        }
        for binding in self.realization_bindings.values() {
            bytes.extend_from_slice(binding.digest().as_array());
        }
        for (realization_id, payload) in &self.realization_payloads {
            push_id(&mut bytes, realization_id);
            bytes.extend_from_slice(Digest32::of_bytes(payload).as_array());
        }
        for (successor, predecessor) in &self.realization_supersessions {
            push_id(&mut bytes, successor);
            push_id(&mut bytes, predecessor);
        }
        for event in &self.lifecycle_events {
            bytes.extend_from_slice(event.event_digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }

    fn disable_realizations(&mut self, factor_id: &StableId) {
        for realization in self.realizations.values_mut() {
            if &realization.factor_id == factor_id {
                realization.active = false;
            }
        }
    }

    fn ensure_capacity(&self, additional: usize) -> Result<(), Error> {
        let current = self.factors.len().saturating_add(self.realizations.len());
        if current.saturating_add(additional) > self.maximum_records {
            return Err(Error::CapacityExceeded);
        }
        Ok(())
    }

    fn next_revision(&self) -> Result<Revision, Error> {
        self.revision.next().map_err(|_| Error::RevisionOverflow)
    }

    fn commit_revision(&mut self, revision: Revision, revocation: bool) {
        self.revision = revision;
        self.lifecycle_frontier = revision.get();
        if revocation {
            self.revocation_frontier = revision.get();
        }
    }

    fn receipt(&self, disposition: MutationDisposition) -> RegistryReceipt {
        RegistryReceipt {
            revision: self.revision,
            disposition,
            registry_digest: self.snapshot_digest(),
            authority: AuthorityPosture::DENY_ALL,
        }
    }
}

fn lifecycle_event(
    revision: Revision,
    factor_id: StableId,
    kind: LifecycleEventKind,
    from: Option<Lifecycle>,
    to: Lifecycle,
    actor_id: StableId,
    admission_grant_id: Option<StableId>,
    evidence_digest: Digest32,
    scope_digest: Option<Digest32>,
    reason_digest: Option<Digest32>,
    cutoff_unix_ms: Option<u64>,
) -> LifecycleEvent {
    let mut event = LifecycleEvent {
        revision,
        factor_id,
        kind,
        from,
        to,
        actor_id,
        admission_grant_id,
        evidence_digest,
        scope_digest,
        reason_digest,
        cutoff_unix_ms,
        event_digest: Digest32::ZERO,
    };
    event.event_digest = event.compute_digest();
    event
}

fn push_optional_id(bytes: &mut Vec<u8>, value: Option<&StableId>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_id(bytes, value);
        }
        None => bytes.push(0),
    }
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
}

const fn lifecycle_event_kind_code(kind: LifecycleEventKind) -> u8 {
    match kind {
        LifecycleEventKind::Registered => 0,
        LifecycleEventKind::Admitted => 1,
        LifecycleEventKind::Retired => 2,
        LifecycleEventKind::Revoked => 3,
        LifecycleEventKind::Imported => 4,
    }
}

fn lifecycle_code(lifecycle: Lifecycle) -> u8 {
    match lifecycle {
        Lifecycle::Draft => 0,
        Lifecycle::Admitted => 1,
        Lifecycle::Retired => 2,
        Lifecycle::Revoked => 3,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
