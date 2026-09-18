//! Governed in-memory domain engine for prompt factors and realizations.

use std::collections::BTreeMap;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::model::AdmissionRequest;
use crate::model::Error;
use crate::model::FactorAdmissionRecord;
use crate::model::LifecycleEvent;
use crate::model::MutationDisposition;
use crate::model::PromptFactor;
use crate::model::PromptRealization;
use crate::model::RegistryReceipt;
use crate::v2::PromptRealizationBindingV2;

pub(crate) const MAX_RECORDS: usize = 16_384;
pub(crate) const MAX_LIFECYCLE_EVENTS: usize = MAX_RECORDS * 4;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistry {
    pub(crate) factors: BTreeMap<StableId, PromptFactor>,
    pub(crate) realizations: BTreeMap<StableId, PromptRealization>,
    pub(crate) realization_bindings: BTreeMap<StableId, PromptRealizationBindingV2>,
    pub(crate) realization_payloads: BTreeMap<StableId, Vec<u8>>,
    pub(crate) realization_revisions: BTreeMap<StableId, Revision>,
    pub(crate) admissions: BTreeMap<StableId, FactorAdmissionRecord>,
    pub(crate) lifecycle_history: Vec<LifecycleEvent>,
    pub(crate) revision: Revision,
    pub(crate) lifecycle_frontier: u64,
    pub(crate) revocation_frontier: u64,
    pub(crate) maximum_records: usize,
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
            realization_payloads: BTreeMap::new(),
            realization_revisions: BTreeMap::new(),
            admissions: BTreeMap::new(),
            lifecycle_history: Vec::new(),
            revision,
            lifecycle_frontier: 0,
            revocation_frontier: 0,
            maximum_records: maximum_records.min(MAX_RECORDS),
        })
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

    pub fn realization_payload(&self, realization_id: &StableId) -> Option<&[u8]> {
        self.realization_payloads
            .get(realization_id)
            .map(Vec::as_slice)
    }

    pub fn realization_revision(&self, realization_id: &StableId) -> Option<Revision> {
        self.realization_revisions.get(realization_id).copied()
    }

    pub fn admission(&self, factor_id: &StableId) -> Option<&FactorAdmissionRecord> {
        self.admissions.get(factor_id)
    }

    pub fn lifecycle_history(&self) -> &[LifecycleEvent] {
        &self.lifecycle_history
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

    pub(crate) fn validate_admission_request(
        &self,
        request: &AdmissionRequest,
    ) -> Result<(), Error> {
        if request.evidence_digest.is_zero() {
            return Err(Error::EmptyDigest("admission evidence"));
        }
        if request.reviewed_scope_digest.is_zero() {
            return Err(Error::EmptyDigest("reviewed scope"));
        }
        Ok(())
    }

    pub(crate) fn disable_realizations(&mut self, factor_id: &StableId) {
        for realization in self.realizations.values_mut() {
            if &realization.factor_id == factor_id {
                realization.active = false;
            }
        }
    }

    pub(crate) fn ensure_capacity(&self, additional: usize) -> Result<(), Error> {
        let current = self.factors.len().saturating_add(self.realizations.len());
        if current.saturating_add(additional) > self.maximum_records {
            return Err(Error::CapacityExceeded);
        }
        Ok(())
    }

    pub(crate) fn ensure_lifecycle_capacity(&self, additional: usize) -> Result<(), Error> {
        if self.lifecycle_history.len().saturating_add(additional) > MAX_LIFECYCLE_EVENTS {
            return Err(Error::LifecycleHistoryCapacityExceeded);
        }
        Ok(())
    }

    pub(crate) fn next_revision(&self) -> Result<Revision, Error> {
        self.revision.next().map_err(|_| Error::RevisionOverflow)
    }

    pub(crate) fn commit_revision(&mut self, revision: Revision, revocation: bool) {
        self.revision = revision;
        self.lifecycle_frontier = revision.get();
        if revocation {
            self.revocation_frontier = revision.get();
        }
    }

    pub(crate) fn receipt(&self, disposition: MutationDisposition) -> RegistryReceipt {
        RegistryReceipt {
            revision: self.revision,
            disposition,
            registry_digest: self.snapshot_digest(),
            authority: AuthorityPosture::DENY_ALL,
        }
    }
}
