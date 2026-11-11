//! Bounded, scope-local cell inventory and four independent census quantities.
//!
//! This immutable projection neither creates workers nor schedules cells. The
//! caller supplies owner-observed active instances; counting them is not proof
//! of execution, authentication or permission to change a lifecycle. State and
//! immutable artifacts remain with their existing owners.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellCapabilityContractV1;
use crate::CellCapabilityErrorV1;

// An inventory input ceiling, not a claim about useful or executable capacity.
const MAX_POPULATION_ENTRIES_V1: usize = 4_096;

/// An immutable, capability-bound expert version. Distinct versions may share
/// base weights; the complete bundle includes adapters, heads and compatibility.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellExpertVersionV1 {
    pub version_id: StableId,
    pub type_id: StableId,
    pub capability_digest: Digest32,
    pub shared_base_digest: Digest32,
    pub parameter_bundle_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellInstanceDispositionV1 {
    Available,
    Quarantined,
    Retired,
}

/// A state slot is unique within its scope, even across different owner IDs.
/// The owner ID identifies responsibility; it is not a writer capability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellInstanceV1 {
    pub instance_id: StableId,
    pub scope_digest: Digest32,
    pub generation: Generation,
    pub type_id: StableId,
    pub expert_version_id: StableId,
    pub state_owner_id: StableId,
    pub state_slot_id: StableId,
    pub state_schema_digest: Digest32,
    pub reserved_state_bytes: u64,
    pub disposition: CellInstanceDispositionV1,
}

/// Exact instance/version identity observed by the existing runtime owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellActiveInstanceV1 {
    pub instance_id: StableId,
    pub scope_digest: Digest32,
    pub generation: Generation,
    pub expert_version_id: StableId,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellPopulationLimitsV1 {
    pub max_types: usize,
    pub max_expert_versions: usize,
    pub max_instances: usize,
    pub max_active_instances: usize,
    pub max_reserved_state_bytes: u64,
}

/// Counts retained declarations/versions/state slots, including inactive and
/// retired slots; only available instances may appear in the active subset.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellPopulationCensusV1 {
    pub scope_digest: Digest32,
    pub type_count: usize,
    pub expert_version_count: usize,
    pub instance_count: usize,
    pub active_instance_count: usize,
    pub reserved_state_bytes: u64,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellPopulationV1 {
    scope_digest: Digest32,
    limits: CellPopulationLimitsV1,
    capabilities: BTreeMap<StableId, CellCapabilityContractV1>,
    experts: BTreeMap<StableId, CellExpertVersionV1>,
    instances: BTreeMap<StableId, CellInstanceV1>,
    reserved_state_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellPopulationErrorV1 {
    InvalidLimits,
    EmptyDigest(&'static str),
    CapacityExceeded(&'static str),
    Capability(CellCapabilityErrorV1),
    DuplicateType(StableId),
    TypeAlias(StableId),
    DuplicateExpertVersion(StableId),
    ExpertVersionAlias(StableId),
    UnregisteredType(StableId),
    CapabilityMismatch(StableId),
    DuplicateInstance(StableId),
    UnregisteredExpertVersion(StableId),
    InstanceTypeMismatch(StableId),
    StateSchemaMismatch(StableId),
    StateSlotAlias(StableId),
    InvalidStateReservation(StableId),
    ScopeMismatch(StableId),
    UnregisteredActiveInstance(StableId),
    DuplicateActiveInstance(StableId),
    InstanceUnavailable(StableId),
    ActiveVersionMismatch(StableId),
}

impl std::fmt::Display for CellPopulationErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CellPopulationErrorV1 {}

impl CellPopulationV1 {
    /// Validate an entire inventory before retaining it. Type aliases cannot
    /// create extra capacity by changing a name, role label or generation.
    pub fn new(
        scope_digest: Digest32,
        limits: CellPopulationLimitsV1,
        capabilities: Vec<CellCapabilityContractV1>,
        experts: Vec<CellExpertVersionV1>,
        instances: Vec<CellInstanceV1>,
    ) -> Result<Self, CellPopulationErrorV1> {
        use CellPopulationErrorV1 as E;

        if scope_digest.is_zero() {
            return Err(E::EmptyDigest("scope"));
        }
        if [
            limits.max_types,
            limits.max_expert_versions,
            limits.max_instances,
            limits.max_active_instances,
        ]
        .into_iter()
        .any(|limit| !(1..=MAX_POPULATION_ENTRIES_V1).contains(&limit))
            || limits.max_active_instances > limits.max_instances
            || limits.max_reserved_state_bytes == 0
        {
            return Err(E::InvalidLimits);
        }
        for (name, actual, maximum) in [
            ("types", capabilities.len(), limits.max_types),
            ("expert versions", experts.len(), limits.max_expert_versions),
            ("instances", instances.len(), limits.max_instances),
        ] {
            if actual > maximum {
                return Err(E::CapacityExceeded(name));
            }
        }
        let mut by_type = BTreeMap::new();
        let mut capability_shapes = BTreeSet::new();
        for capability in capabilities {
            capability.digest().map_err(E::Capability)?;
            if by_type.contains_key(&capability.type_id) {
                return Err(E::DuplicateType(capability.type_id));
            }
            // A role and a schema revision are metadata, not additional types
            // when the actual schema/behavior contract remains identical.
            if !capability_shapes.insert((
                capability.input_schema_digest,
                capability.output_schema_digest,
                capability.state_schema_digest,
                capability.behavior_contract_digest,
            )) {
                return Err(E::TypeAlias(capability.type_id));
            }
            by_type.insert(capability.type_id.clone(), capability);
        }
        let mut by_expert = BTreeMap::new();
        let mut bundles = BTreeSet::new();
        for expert in experts {
            if by_expert.contains_key(&expert.version_id) {
                return Err(E::DuplicateExpertVersion(expert.version_id));
            }
            let capability = by_type
                .get(&expert.type_id)
                .ok_or_else(|| E::UnregisteredType(expert.type_id.clone()))?;
            if expert.capability_digest != capability.digest().map_err(E::Capability)? {
                return Err(E::CapabilityMismatch(expert.version_id));
            }
            for (name, digest) in [
                ("shared base", expert.shared_base_digest),
                ("parameter bundle", expert.parameter_bundle_digest),
            ] {
                if digest.is_zero() {
                    return Err(E::EmptyDigest(name));
                }
            }
            if !bundles.insert(expert.parameter_bundle_digest) {
                return Err(E::ExpertVersionAlias(expert.version_id));
            }
            by_expert.insert(expert.version_id.clone(), expert);
        }
        let mut by_instance = BTreeMap::new();
        let mut state_slots = BTreeSet::new();
        let mut reserved_state_bytes = 0u64;
        for instance in instances {
            if by_instance.contains_key(&instance.instance_id) {
                return Err(E::DuplicateInstance(instance.instance_id));
            }
            if instance.scope_digest != scope_digest {
                return Err(E::ScopeMismatch(instance.instance_id));
            }
            let expert = by_expert
                .get(&instance.expert_version_id)
                .ok_or_else(|| E::UnregisteredExpertVersion(instance.expert_version_id.clone()))?;
            let capability = by_type
                .get(&instance.type_id)
                .ok_or_else(|| E::UnregisteredType(instance.type_id.clone()))?;
            if instance.type_id != expert.type_id {
                return Err(E::InstanceTypeMismatch(instance.instance_id));
            }
            if instance.state_schema_digest != capability.state_schema_digest {
                return Err(E::StateSchemaMismatch(instance.instance_id));
            }
            if !state_slots.insert(instance.state_slot_id.clone()) {
                return Err(E::StateSlotAlias(instance.state_slot_id));
            }
            if instance.reserved_state_bytes == 0 {
                return Err(E::InvalidStateReservation(instance.instance_id));
            }
            reserved_state_bytes = reserved_state_bytes
                .checked_add(instance.reserved_state_bytes)
                .filter(|total| *total <= limits.max_reserved_state_bytes)
                .ok_or(E::CapacityExceeded("reserved state bytes"))?;
            by_instance.insert(instance.instance_id.clone(), instance);
        }
        Ok(Self {
            scope_digest,
            limits,
            capabilities: by_type,
            experts: by_expert,
            instances: by_instance,
            reserved_state_bytes,
        })
    }

    /// Validate the active subset against this immutable inventory. This is an
    /// observation, not an activation command or a learned scheduling decision.
    pub fn census(
        &self,
        active: &[CellActiveInstanceV1],
    ) -> Result<CellPopulationCensusV1, CellPopulationErrorV1> {
        use CellPopulationErrorV1 as E;

        if active.len() > self.limits.max_active_instances {
            return Err(E::CapacityExceeded("active instances"));
        }
        let mut seen = BTreeSet::new();
        for observation in active {
            let id = &observation.instance_id;
            if observation.scope_digest != self.scope_digest {
                return Err(E::ScopeMismatch(id.clone()));
            }
            if !seen.insert(id) {
                return Err(E::DuplicateActiveInstance(id.clone()));
            }
            let instance = self
                .instances
                .get(id)
                .ok_or_else(|| E::UnregisteredActiveInstance(id.clone()))?;
            if instance.generation != observation.generation
                || instance.expert_version_id != observation.expert_version_id
            {
                return Err(E::ActiveVersionMismatch(id.clone()));
            }
            if instance.disposition != CellInstanceDispositionV1::Available {
                return Err(E::InstanceUnavailable(id.clone()));
            }
        }
        Ok(CellPopulationCensusV1 {
            scope_digest: self.scope_digest,
            type_count: self.capabilities.len(),
            expert_version_count: self.experts.len(),
            instance_count: self.instances.len(),
            active_instance_count: seen.len(),
            reserved_state_bytes: self.reserved_state_bytes,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[cfg(test)]
#[path = "cell_population_tests.rs"]
mod tests;
