//! Governed prompt-factor and realization registry.
//!
//! The registry stores bounded identities and content digests, never executable
//! instructions or ambient authority. External untrusted material cannot admit
//! itself, and revocation is terminal and cascades to realizations.

#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistry {
    factors: BTreeMap<StableId, PromptFactor>,
    realizations: BTreeMap<StableId, PromptRealization>,
    revision: Revision,
    maximum_records: usize,
}

impl PromptRegistry {
    pub fn new(maximum_records: usize) -> Result<Self, Error> {
        if maximum_records == 0 {
            return Err(Error::ZeroCapacity);
        }
        let Ok(revision) = Revision::new(1) else {
            return Err(Error::RevisionOverflow);
        };
        Ok(Self {
            factors: BTreeMap::new(),
            realizations: BTreeMap::new(),
            revision,
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
        self.ensure_capacity(1)?;
        self.revision = self.revision.next().map_err(|_| Error::RevisionOverflow)?;
        self.factors.insert(factor.factor_id.clone(), factor);
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
        {
            let Some(factor) = self.factors.get_mut(factor_id) else {
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
            self.revision = self.revision.next().map_err(|_| Error::RevisionOverflow)?;
            factor.lifecycle = Lifecycle::Admitted;
        }
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
        self.ensure_capacity(1)?;
        self.revision = self.revision.next().map_err(|_| Error::RevisionOverflow)?;
        self.realizations
            .insert(realization.realization_id.clone(), realization);
        Ok(self.receipt(MutationDisposition::Inserted))
    }

    pub fn retire_factor(&mut self, factor_id: &StableId) -> Result<RegistryReceipt, Error> {
        {
            let Some(factor) = self.factors.get_mut(factor_id) else {
                return Err(Error::FactorNotFound(factor_id.to_string()));
            };
            if factor.lifecycle != Lifecycle::Admitted {
                return Err(Error::InvalidTransition);
            }
            self.revision = self.revision.next().map_err(|_| Error::RevisionOverflow)?;
            factor.lifecycle = Lifecycle::Retired;
        }
        self.disable_realizations(factor_id);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }

    pub fn revoke_factor(&mut self, factor_id: &StableId) -> Result<RegistryReceipt, Error> {
        {
            let Some(factor) = self.factors.get_mut(factor_id) else {
                return Err(Error::FactorNotFound(factor_id.to_string()));
            };
            if factor.lifecycle == Lifecycle::Revoked {
                return Err(Error::InvalidTransition);
            }
            self.revision = self.revision.next().map_err(|_| Error::RevisionOverflow)?;
            factor.lifecycle = Lifecycle::Revoked;
        }
        self.disable_realizations(factor_id);
        Ok(self.receipt(MutationDisposition::Transitioned))
    }

    pub fn factor(&self, factor_id: &StableId) -> Option<&PromptFactor> {
        self.factors.get(factor_id)
    }

    pub fn realization(&self, realization_id: &StableId) -> Option<&PromptRealization> {
        self.realizations.get(realization_id)
    }

    pub fn snapshot_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.prompt-registry.snapshot.v1");
        bytes.extend_from_slice(&self.revision.get().to_be_bytes());
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

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
