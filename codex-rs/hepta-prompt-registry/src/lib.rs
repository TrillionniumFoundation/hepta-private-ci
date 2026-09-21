//! Governed prompt-factor and realization registry.
//!
//! The registry stores bounded identities and content digests, never executable
//! instructions or ambient authority. External untrusted material cannot admit
//! itself, and revocation is terminal and cascades to realizations.

#![forbid(unsafe_code)]

mod v2;

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

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

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PromptFactorRelationKind {
    Complements,
    Substitutes,
    Conflicts,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct PromptFactorRelation {
    pub relation_id: StableId,
    pub left_factor_id: StableId,
    pub right_factor_id: StableId,
    pub kind: PromptFactorRelationKind,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptFactorGraphNodeV1 {
    pub factor_id: StableId,
    pub semantic_version: StableId,
    pub content_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptFactorGraphSourceV1 {
    pub registry_revision: Revision,
    pub registry_snapshot_digest: Digest32,
    pub lifecycle_frontier: u64,
    pub revocation_frontier: u64,
    pub factors: Vec<PromptFactorGraphNodeV1>,
    pub relations: Vec<PromptFactorRelation>,
    pub source_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptFactorGraphSourceV1 {
    #[must_use]
    pub fn compute_source_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-factor-graph-source.v1".to_vec();
        bytes.extend_from_slice(&self.registry_revision.get().to_be_bytes());
        bytes.extend_from_slice(self.registry_snapshot_digest.as_array());
        bytes.extend_from_slice(&self.lifecycle_frontier.to_be_bytes());
        bytes.extend_from_slice(&self.revocation_frontier.to_be_bytes());
        bytes.extend_from_slice(
            &u64::try_from(self.factors.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for factor in &self.factors {
            push_id(&mut bytes, &factor.factor_id);
            push_id(&mut bytes, &factor.semantic_version);
            bytes.extend_from_slice(factor.content_digest.as_array());
        }
        bytes.extend_from_slice(
            &u64::try_from(self.relations.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for relation in &self.relations {
            push_relation(&mut bytes, relation);
        }
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), Error> {
        if self.registry_snapshot_digest.is_zero() || self.source_digest.is_zero() {
            return Err(Error::EmptyDigest("factor graph source"));
        }
        if self.revocation_frontier > self.lifecycle_frontier
            || self.lifecycle_frontier > self.registry_revision.get()
            || self.authority.grants_any()
        {
            return Err(Error::InvalidFactorGraphSource);
        }
        if self
            .factors
            .windows(2)
            .any(|pair| pair[0].factor_id >= pair[1].factor_id)
            || self
                .relations
                .windows(2)
                .any(|pair| pair[0].relation_id >= pair[1].relation_id)
        {
            return Err(Error::InvalidFactorGraphSource);
        }
        let factor_ids = self
            .factors
            .iter()
            .map(|factor| factor.factor_id.clone())
            .collect::<std::collections::BTreeSet<_>>();
        if self.factors.iter().any(|factor| factor.content_digest.is_zero())
            || self.relations.iter().any(|relation| {
                relation.evidence_digest.is_zero()
                    || relation.left_factor_id >= relation.right_factor_id
                    || !factor_ids.contains(&relation.left_factor_id)
                    || !factor_ids.contains(&relation.right_factor_id)
            })
        {
            return Err(Error::InvalidFactorGraphSource);
        }
        if self.source_digest != self.compute_source_digest() {
            return Err(Error::InvalidFactorGraphSource);
        }
        Ok(())
    }
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
    RelationConflict(String),
    FactorNotFound(String),
    FactorNotAdmitted(String),
    ExternalSelfAdmission,
    SelfReview,
    InvalidTransition,
    RevisionOverflow,
    InvalidRelation,
    InvalidFactorGraphSource,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistry {
    factors: BTreeMap<StableId, PromptFactor>,
    realizations: BTreeMap<StableId, PromptRealization>,
    realization_bindings: BTreeMap<StableId, PromptRealizationBindingV2>,
    relations: BTreeMap<StableId, PromptFactorRelation>,
    revision: Revision,
    lifecycle_frontier: u64,
    revocation_frontier: u64,
    maximum_records: usize,
}

impl PromptRegistry {
    pub fn new(maximum_records: usize) -> Result<Self, Error> {
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
            relations: BTreeMap::new(),
            revision,
            lifecycle_frontier: 0,
            revocation_frontier: 0,
            maximum_records: maximum_records.min(MAX_RECORDS),
        })
    }

    pub fn register_factor(&mut self, factor: PromptFactor) -> Result<RegistryReceipt, Error> {
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
        self.factors.insert(factor.factor_id.clone(), factor);
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Inserted))
    }

    pub fn admit_factor(
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
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }

    pub fn register_realization(
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

    pub fn register_factor_relation(
        &mut self,
        relation: PromptFactorRelation,
    ) -> Result<RegistryReceipt, Error> {
        if relation.evidence_digest.is_zero() {
            return Err(Error::EmptyDigest("factor relation evidence"));
        }
        if relation.left_factor_id >= relation.right_factor_id {
            return Err(Error::InvalidRelation);
        }
        for factor_id in [&relation.left_factor_id, &relation.right_factor_id] {
            let Some(factor) = self.factors.get(factor_id) else {
                return Err(Error::FactorNotFound(factor_id.to_string()));
            };
            if factor.source != FactorSource::GovernedInternal
                || factor.lifecycle != Lifecycle::Admitted
            {
                return Err(Error::FactorNotAdmitted(factor_id.to_string()));
            }
        }
        if let Some(existing) = self.relations.get(&relation.relation_id) {
            if existing == &relation {
                return Ok(self.receipt(MutationDisposition::Unchanged));
            }
            return Err(Error::RelationConflict(relation.relation_id.to_string()));
        }
        if self.relations.values().any(|existing| {
            existing.left_factor_id == relation.left_factor_id
                && existing.right_factor_id == relation.right_factor_id
                && existing.kind == relation.kind
        }) {
            return Err(Error::InvalidRelation);
        }
        self.ensure_capacity(/*additional*/ 1)?;
        let next_revision = self.next_revision()?;
        self.relations.insert(relation.relation_id.clone(), relation);
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Inserted))
    }

    #[must_use]
    pub fn factor_graph_source_v1(&self) -> PromptFactorGraphSourceV1 {
        let factors = self
            .factors
            .values()
            .filter(|factor| {
                factor.source == FactorSource::GovernedInternal
                    && factor.lifecycle == Lifecycle::Admitted
            })
            .map(|factor| PromptFactorGraphNodeV1 {
                factor_id: factor.factor_id.clone(),
                semantic_version: factor.semantic_version.clone(),
                content_digest: factor.content_digest,
            })
            .collect::<Vec<_>>();
        let live = factors
            .iter()
            .map(|factor| factor.factor_id.clone())
            .collect::<std::collections::BTreeSet<_>>();
        let relations = self
            .relations
            .values()
            .filter(|relation| {
                live.contains(&relation.left_factor_id) && live.contains(&relation.right_factor_id)
            })
            .cloned()
            .collect::<Vec<_>>();
        let mut source = PromptFactorGraphSourceV1 {
            registry_revision: self.revision,
            registry_snapshot_digest: self.snapshot_digest(),
            lifecycle_frontier: self.lifecycle_frontier,
            revocation_frontier: self.revocation_frontier,
            factors,
            relations,
            source_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        source.source_digest = source.compute_source_digest();
        source
    }

    pub fn retire_factor(&mut self, factor_id: &StableId) -> Result<RegistryReceipt, Error> {
        let Some(factor) = self.factors.get(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        if factor.lifecycle != Lifecycle::Admitted {
            return Err(Error::InvalidTransition);
        }
        let next_revision = self.next_revision()?;
        let Some(factor) = self.factors.get_mut(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        factor.lifecycle = Lifecycle::Retired;
        self.disable_realizations(factor_id);
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }

    pub fn revoke_factor(&mut self, factor_id: &StableId) -> Result<RegistryReceipt, Error> {
        let Some(factor) = self.factors.get(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        if factor.lifecycle == Lifecycle::Revoked {
            return Err(Error::InvalidTransition);
        }
        let next_revision = self.next_revision()?;
        let Some(factor) = self.factors.get_mut(factor_id) else {
            return Err(Error::FactorNotFound(factor_id.to_string()));
        };
        factor.lifecycle = Lifecycle::Revoked;
        self.disable_realizations(factor_id);
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
        for relation in self.relations.values() {
            push_relation(&mut bytes, relation);
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
        let current = self
            .factors
            .len()
            .saturating_add(self.realizations.len())
            .saturating_add(self.relations.len());
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

fn lifecycle_code(lifecycle: Lifecycle) -> u8 {
    match lifecycle {
        Lifecycle::Draft => 0,
        Lifecycle::Admitted => 1,
        Lifecycle::Retired => 2,
        Lifecycle::Revoked => 3,
    }
}

fn push_relation(bytes: &mut Vec<u8>, relation: &PromptFactorRelation) {
    push_id(bytes, &relation.relation_id);
    push_id(bytes, &relation.left_factor_id);
    push_id(bytes, &relation.right_factor_id);
    bytes.push(match relation.kind {
        PromptFactorRelationKind::Complements => 0,
        PromptFactorRelationKind::Substitutes => 1,
        PromptFactorRelationKind::Conflicts => 2,
    });
    bytes.extend_from_slice(relation.evidence_digest.as_array());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
