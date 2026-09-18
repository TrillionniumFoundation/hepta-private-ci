//! Capability-neutral, authority-free snapshots for the existing plan composer.
//!
//! Missing optional capabilities are encoded as absent, not fake artifacts.
//! V1 Lane F snapshots and pipeline receipts keep their original meanings.
//! This entrypoint does not load code, invoke providers or authorize deployment.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::IntelligencePlanReceipt;
use crate::PlanCandidate;
use crate::PlanningRequest;
use crate::compose;
use crate::push_id;

const MAX_CAPABILITIES: usize = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CapabilityNecessityV2 {
    Required,
    Optional,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CapabilityRequirementV2 {
    pub capability_id: StableId,
    pub owner_id: StableId,
    pub contract_digest: Digest32,
    pub necessity: CapabilityNecessityV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CapabilityBindingV2 {
    pub capability_id: StableId,
    pub owner_id: StableId,
    pub contract_digest: Digest32,
    pub implementation_digest: Digest32,
    pub generation: Generation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CapabilitySnapshotRequestV2 {
    pub objective_digest: Digest32,
    pub authority_epoch: u64,
    pub body_generation: Generation,
    pub configuration_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub requirements: Vec<CapabilityRequirementV2>,
    pub bindings: Vec<CapabilityBindingV2>,
}

/// An immutable input to the existing composer, not an authority capability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CapabilitySnapshotV2 {
    objective_digest: Digest32,
    authority_epoch: u64,
    body_generation: Generation,
    snapshot_digest: Digest32,
    absent_optional: Vec<StableId>,
    bindings: BTreeMap<StableId, CapabilityBindingV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CapabilitySnapshotErrorV2 {
    InvalidCoreIdentity,
    CapacityExceeded,
    InvalidRequirement,
    DuplicateRequirement(StableId),
    DuplicateBinding(StableId),
    UnknownCapability(StableId),
    MissingRequiredCapability(StableId),
    BindingMismatch(StableId),
}

impl fmt::Display for CapabilitySnapshotErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CapabilitySnapshotErrorV2 {}

impl CapabilitySnapshotV2 {
    pub fn admit(
        mut request: CapabilitySnapshotRequestV2,
    ) -> Result<Self, CapabilitySnapshotErrorV2> {
        if request.authority_epoch == 0
            || request.objective_digest.is_zero()
            || request.configuration_digest.is_zero()
            || request.revocation_frontier_digest.is_zero()
        {
            return Err(CapabilitySnapshotErrorV2::InvalidCoreIdentity);
        }
        if request.requirements.len() > MAX_CAPABILITIES
            || request.bindings.len() > MAX_CAPABILITIES
        {
            return Err(CapabilitySnapshotErrorV2::CapacityExceeded);
        }
        request
            .requirements
            .sort_by(|a, b| a.capability_id.cmp(&b.capability_id));
        let mut requirements = BTreeMap::new();
        for requirement in &request.requirements {
            if requirement.contract_digest.is_zero() {
                return Err(CapabilitySnapshotErrorV2::InvalidRequirement);
            }
            if requirements
                .insert(&requirement.capability_id, requirement)
                .is_some()
            {
                return Err(CapabilitySnapshotErrorV2::DuplicateRequirement(
                    requirement.capability_id.clone(),
                ));
            }
        }
        let mut bindings = BTreeMap::new();
        for binding in &request.bindings {
            let requirement = requirements.get(&binding.capability_id).ok_or_else(|| {
                CapabilitySnapshotErrorV2::UnknownCapability(binding.capability_id.clone())
            })?;
            if binding.owner_id != requirement.owner_id
                || binding.contract_digest != requirement.contract_digest
                || binding.implementation_digest.is_zero()
            {
                return Err(CapabilitySnapshotErrorV2::BindingMismatch(
                    binding.capability_id.clone(),
                ));
            }
            if bindings.insert(&binding.capability_id, binding).is_some() {
                return Err(CapabilitySnapshotErrorV2::DuplicateBinding(
                    binding.capability_id.clone(),
                ));
            }
        }
        let mut bytes = b"hepta.intelligence.capability-snapshot.v2\0".to_vec();
        for digest in [
            request.objective_digest,
            request.configuration_digest,
            request.revocation_frontier_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&request.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&request.body_generation.get().to_be_bytes());
        let count = u32::try_from(requirements.len())
            .map_err(|_| CapabilitySnapshotErrorV2::CapacityExceeded)?;
        bytes.extend_from_slice(&count.to_be_bytes());
        let mut absent_optional = Vec::new();
        for requirement in &request.requirements {
            push_id(&mut bytes, &requirement.capability_id);
            push_id(&mut bytes, &requirement.owner_id);
            bytes.extend_from_slice(requirement.contract_digest.as_array());
            bytes.push(match requirement.necessity {
                CapabilityNecessityV2::Required => 1,
                CapabilityNecessityV2::Optional => 0,
            });
            if let Some(binding) = bindings.get(&requirement.capability_id) {
                bytes.push(1);
                bytes.extend_from_slice(binding.implementation_digest.as_array());
                bytes.extend_from_slice(&binding.generation.get().to_be_bytes());
            } else {
                if requirement.necessity == CapabilityNecessityV2::Required {
                    return Err(CapabilitySnapshotErrorV2::MissingRequiredCapability(
                        requirement.capability_id.clone(),
                    ));
                }
                bytes.push(0);
                absent_optional.push(requirement.capability_id.clone());
            }
        }
        Ok(Self {
            objective_digest: request.objective_digest,
            authority_epoch: request.authority_epoch,
            body_generation: request.body_generation,
            snapshot_digest: Digest32::of_bytes(&bytes),
            absent_optional,
            bindings: request
                .bindings
                .into_iter()
                .map(|item| (item.capability_id.clone(), item))
                .collect(),
        })
    }

    #[must_use]
    pub fn bound_owner(&self, capability: &str) -> Option<&str> {
        self.bindings
            .iter()
            .find(|(id, _)| id.as_str() == capability)
            .map(|(_, binding)| binding.owner_id.as_str())
    }

    #[must_use]
    pub fn bound_implementation_digest(&self, capability: &str) -> Option<Digest32> {
        self.bindings
            .iter()
            .find(|(id, _)| id.as_str() == capability)
            .map(|(_, binding)| binding.implementation_digest)
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub const fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    #[must_use]
    pub const fn body_generation(&self) -> Generation {
        self.body_generation
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.snapshot_digest
    }

    #[must_use]
    pub fn absent_optional(&self) -> &[StableId] {
        &self.absent_optional
    }

    /// Use the admitted snapshot in the existing bounded, non-executing composer.
    /// It remains the caller's job to authenticate owner facts and check freshness.
    pub fn compose_plan(
        &self,
        plan_id: StableId,
        context_digest: Digest32,
        candidates: Vec<PlanCandidate>,
    ) -> Result<IntelligencePlanReceipt, crate::Error> {
        compose(PlanningRequest {
            plan_id,
            objective_digest: self.objective_digest,
            context_digest,
            snapshot_digest: self.snapshot_digest,
            candidates,
        })
    }
}

#[cfg(test)]
#[path = "capability_snapshot_tests.rs"]
mod tests;
