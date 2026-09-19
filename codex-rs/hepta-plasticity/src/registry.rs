//! Bounded, conflict-detecting storage for internal proposal records.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::legacy::validate_legacy_v1_read;
use crate::parameter_v2::verify_parameter_proposal_v2;
use crate::topology_v3::verify_topology_proposal_v3;
use crate::types::*;

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct ProposalRegistrySlotV2 {
    pub selected_artifact_digest: Digest32,
    pub window_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProposalRegistry {
    legacy_v1: BTreeMap<StableId, PlasticityProposal>,
    parameter_v2: BTreeMap<ProposalRegistrySlotV2, ParameterProposalV2>,
    parameter_v2_ids: BTreeMap<StableId, ProposalRegistrySlotV2>,
    topology_v3: BTreeMap<StableId, TopologyProposalV3>,
    topology_v3_slots: BTreeMap<(Digest32, u64), StableId>,
    maximum_records: usize,
}

impl ProposalRegistry {
    pub fn new(maximum_records: usize) -> Self {
        Self {
            legacy_v1: BTreeMap::new(),
            parameter_v2: BTreeMap::new(),
            parameter_v2_ids: BTreeMap::new(),
            topology_v3: BTreeMap::new(),
            topology_v3_slots: BTreeMap::new(),
            maximum_records: maximum_records.min(MAX_PROPOSALS),
        }
    }

    /// Hydrate historical V1 records for structural reads without enabling V1 append.
    ///
    /// V1 proposal digests remain opaque; the caller owns record provenance.
    pub fn with_legacy_v1_history(
        maximum_records: usize,
        proposals: Vec<PlasticityProposal>,
    ) -> Result<Self, Error> {
        let mut registry = Self::new(maximum_records);
        for proposal in proposals {
            validate_legacy_v1_read(&proposal)?;
            if let Some(existing) = registry.legacy_v1.get(&proposal.proposal_id) {
                if existing == &proposal {
                    continue;
                }
                return Err(Error::ProposalConflict(proposal.proposal_id.to_string()));
            }
            if registry.record_count() >= registry.maximum_records {
                return Err(Error::RegistryCapacityExceeded);
            }
            registry
                .legacy_v1
                .insert(proposal.proposal_id.clone(), proposal);
        }
        Ok(registry)
    }

    /// V1 append is permanently disabled; use [`Self::append_v2`].
    pub fn append(&mut self, _proposal: PlasticityProposal) -> Result<AppendDisposition, Error> {
        Err(Error::LegacyWriteDisabled)
    }

    /// Retain a verified V2 record in its artifact/window slot.
    ///
    /// Registry insertion is not independent evaluation, selection or activation.
    pub fn append_v2(&mut self, proposal: ParameterProposalV2) -> Result<AppendDisposition, Error> {
        verify_parameter_proposal_v2(&proposal)?;
        let slot = ProposalRegistrySlotV2 {
            selected_artifact_digest: proposal.selected_artifact_digest,
            window_id: proposal.window.window_id.clone(),
        };
        if let Some(existing) = self.parameter_v2.get(&slot) {
            if existing == &proposal {
                return Ok(AppendDisposition::Unchanged);
            }
            return Err(Error::RegistrySlotConflict(format!(
                "{}:{}",
                slot.selected_artifact_digest, slot.window_id
            )));
        }
        if self.legacy_v1.contains_key(&proposal.proposal_id)
            || self.has_v2_proposal_id(&proposal.proposal_id)
        {
            return Err(Error::ProposalConflict(proposal.proposal_id.to_string()));
        }
        if self.record_count() >= self.maximum_records {
            return Err(Error::RegistryCapacityExceeded);
        }
        self.parameter_v2_ids
            .insert(proposal.proposal_id.clone(), slot.clone());
        self.parameter_v2.insert(slot, proposal);
        Ok(AppendDisposition::Inserted)
    }

    /// Retain a verified topology V3 record. One baseline topology/generation
    /// slot may have only one canonical proposal; competing bytes conflict.
    pub fn append_v3(&mut self, proposal: TopologyProposalV3) -> Result<AppendDisposition, Error> {
        verify_topology_proposal_v3(&proposal)?;
        let slot = (
            proposal.selected_topology_digest,
            proposal.baseline_generation.get(),
        );
        if let Some(existing_id) = self.topology_v3_slots.get(&slot) {
            let existing = self
                .topology_v3
                .get(existing_id)
                .expect("topology slot index must resolve");
            if existing == &proposal {
                return Ok(AppendDisposition::Unchanged);
            }
            return Err(Error::RegistrySlotConflict(format!(
                "{}:{}",
                proposal.selected_topology_digest,
                proposal.baseline_generation.get()
            )));
        }
        if self.legacy_v1.contains_key(&proposal.proposal_id)
            || self.has_v2_proposal_id(&proposal.proposal_id)
            || self.topology_v3.contains_key(&proposal.proposal_id)
        {
            return Err(Error::ProposalConflict(proposal.proposal_id.to_string()));
        }
        if self.record_count() >= self.maximum_records {
            return Err(Error::RegistryCapacityExceeded);
        }
        self.topology_v3_slots.insert(slot, proposal.proposal_id.clone());
        self.topology_v3.insert(proposal.proposal_id.clone(), proposal);
        Ok(AppendDisposition::Inserted)
    }

    pub fn get_v3(&self, proposal_id: &StableId) -> Option<&TopologyProposalV3> {
        self.topology_v3.get(proposal_id)
    }

    /// Return a structurally checked V1 record whose historical digest is opaque.
    pub fn get(&self, proposal_id: &StableId) -> Option<&PlasticityProposal> {
        self.legacy_v1.get(proposal_id)
    }

    pub fn get_v2(
        &self,
        selected_artifact_digest: Digest32,
        window_id: &StableId,
    ) -> Option<&ParameterProposalV2> {
        self.parameter_v2.get(&ProposalRegistrySlotV2 {
            selected_artifact_digest,
            window_id: window_id.clone(),
        })
    }

    pub fn get_v2_by_proposal_id(&self, proposal_id: &StableId) -> Option<&ParameterProposalV2> {
        let slot = self.parameter_v2_ids.get(proposal_id)?;
        self.parameter_v2.get(slot)
    }

    pub fn record_count(&self) -> usize {
        self.legacy_v1.len() + self.parameter_v2.len() + self.topology_v3.len()
    }

    fn has_v2_proposal_id(&self, proposal_id: &StableId) -> bool {
        self.parameter_v2_ids.contains_key(proposal_id)
    }
}
