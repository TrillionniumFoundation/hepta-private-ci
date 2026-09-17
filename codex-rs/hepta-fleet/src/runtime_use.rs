use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::FleetAllocationStore;
use crate::FleetAllocationStoreError;
use crate::FleetResourceVectorV1;
use crate::ResourceBudget;
use crate::lease_ledger::AllocationGrant;
use crate::lease_ledger::Error as LeaseError;
use crate::lease_ledger::FleetConsumptionObservationV1;
use crate::lease_ledger::FleetReconciliationOutcomeV1;

const CONSUMPTION_DESTINATION: &str = "runtime.fleet.consumption";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetAllocationGrantV1 {
    pub allocation_id: String,
    pub request_id: String,
    pub agent_id: AgentId,
    pub host_id: String,
    pub failure_domain_id: String,
    pub host_generation: u64,
    pub authority_epoch: u64,
    pub lease_generation: u64,
    pub expires_at_ms: u64,
    pub resources: FleetResourceVectorV1,
    pub semantic_digest: String,
}

#[derive(Debug, Eq, PartialEq)]
pub struct FleetAllocationUseV1 {
    store_generation: u64,
    allocation_id: String,
    agent_id: AgentId,
    host_id: String,
    lease_generation: u64,
    expires_at_ms: u64,
    resources: FleetResourceVectorV1,
}

impl FleetAllocationUseV1 {
    pub const fn store_generation(&self) -> u64 {
        self.store_generation
    }

    pub fn allocation_id(&self) -> &str {
        &self.allocation_id
    }

    pub fn agent_id(&self) -> &AgentId {
        &self.agent_id
    }

    pub fn host_id(&self) -> &str {
        &self.host_id
    }

    pub const fn lease_generation(&self) -> u64 {
        self.lease_generation
    }

    pub const fn expires_at_ms(&self) -> u64 {
        self.expires_at_ms
    }

    pub const fn resources(&self) -> FleetResourceVectorV1 {
        self.resources
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetReconciliationCommitV1 {
    pub source_generation: u64,
    pub committed_generation: u64,
    pub outcome: FleetReconciliationOutcomeV1,
}

#[derive(Debug, Error)]
pub enum FleetRuntimeUseError {
    #[error("fleet allocation is missing or inactive")]
    MissingAllocation,
    #[error("fleet allocation principal, host or budget does not match the runtime")]
    ScopeMismatch,
    #[error("fleet allocation principal is not a canonical AgentId")]
    InvalidAgentPrincipal,
    #[error(transparent)]
    Store(#[from] FleetAllocationStoreError),
    #[error(transparent)]
    Lease(#[from] LeaseError),
    #[error(transparent)]
    Authority(#[from] FinalUseError),
    #[error("fleet reconciliation encoding failed: {0}")]
    Encoding(String),
}

pub fn read_active_grants_v1(
    store: &FleetAllocationStore,
    now_ms: u64,
) -> Result<Vec<FleetAllocationGrantV1>, FleetRuntimeUseError> {
    let snapshot = store.load(now_ms)?;
    snapshot
        .ledger()
        .grants()
        .values()
        .filter(|grant| !grant.revoked && grant.expires_at_ms > now_ms)
        .map(grant_view)
        .collect()
}

/// Consume one durable grant at the runtime boundary. Host identity and Agent
/// identity are explicit inputs; callers cannot treat a grant for another host
/// or principal as a successful placement.
pub fn admit_runtime_use_v1(
    store: &FleetAllocationStore,
    now_ms: u64,
    local_host_id: &str,
    allocation_id: &str,
    agent_id: &AgentId,
    requested_budget: &ResourceBudget,
) -> Result<FleetAllocationUseV1, FleetRuntimeUseError> {
    let snapshot = store.load(now_ms)?;
    let grant = snapshot
        .grant(allocation_id)
        .filter(|grant| !grant.revoked && grant.expires_at_ms > now_ms)
        .ok_or(FleetRuntimeUseError::MissingAllocation)?;
    if grant.host_id != local_host_id || grant.principal_id != agent_id.as_str() {
        return Err(FleetRuntimeUseError::ScopeMismatch);
    }
    let requested = FleetResourceVectorV1::from_agent_budget(requested_budget);
    if !requested.fits(grant.resources) {
        return Err(FleetRuntimeUseError::ScopeMismatch);
    }
    Ok(FleetAllocationUseV1 {
        store_generation: snapshot.generation(),
        allocation_id: grant.allocation_id.clone(),
        agent_id: agent_id.clone(),
        host_id: grant.host_id.clone(),
        lease_generation: grant.lease_generation,
        expires_at_ms: grant.expires_at_ms,
        resources: grant.resources,
    })
}

pub fn consumption_observation_binding(
    observer_id: &str,
    expected_generation: u64,
    observation: &FleetConsumptionObservationV1,
) -> Result<FinalUseBinding, FleetRuntimeUseError> {
    let payload = serde_json::to_vec(observation)
        .map_err(|error| FleetRuntimeUseError::Encoding(error.to_string()))?;
    let payload_sha256 = digest_parts(
        b"hepta.runtime-fleet.consumption-observation.v1\0",
        &[&payload],
    );
    let request_sha256 = digest_parts(
        b"hepta.runtime-fleet.consumption-request.v1\0",
        &[
            &expected_generation.to_be_bytes(),
            observation.allocation_id.as_bytes(),
            &observation.lease_generation.to_be_bytes(),
        ],
    );
    let scope_sha256 = digest_parts(
        b"hepta.runtime-fleet.consumption-scope.v1\0",
        &[
            observation.allocation_id.as_bytes(),
            &observation.authority_epoch.to_be_bytes(),
            observation.semantic_digest.as_bytes(),
        ],
    );
    Ok(FinalUseBinding {
        subject_id: observer_id.to_string(),
        destination_id: CONSUMPTION_DESTINATION.to_string(),
        request_sha256,
        scope_sha256,
        payload_sha256,
    })
}

pub fn reconcile_consumption_with_authority(
    store: &FleetAllocationStore,
    authority: &FinalUseAuthority,
    signed: &SignedFinalUseGrant,
    observer_id: &str,
    expected_generation: u64,
    now_ms: u64,
    observation: FleetConsumptionObservationV1,
) -> Result<FleetReconciliationCommitV1, FleetRuntimeUseError> {
    let snapshot = store.load(now_ms)?;
    if snapshot.generation() != expected_generation {
        return Err(FleetAllocationStoreError::StaleGeneration {
            expected: expected_generation,
            current: snapshot.generation(),
        }
        .into());
    }
    let mut next = snapshot.ledger().clone();
    let outcome = next.reconcile_consumption(now_ms, observation.clone())?;
    let binding = consumption_observation_binding(observer_id, expected_generation, &observation)?;
    let token = authority.claim(signed, &binding)?;
    let committed_generation = if outcome == FleetReconciliationOutcomeV1::Unchanged {
        authority.with_verified_use(token, &binding, || expected_generation)?
    } else {
        let commit = authority.with_verified_use(token, &binding, || {
            store.commit_ledger(expected_generation, now_ms, next)
        })?;
        commit?
    };
    Ok(FleetReconciliationCommitV1 {
        source_generation: expected_generation,
        committed_generation,
        outcome,
    })
}

fn grant_view(grant: &AllocationGrant) -> Result<FleetAllocationGrantV1, FleetRuntimeUseError> {
    let agent_id = AgentId::parse(grant.principal_id.clone())
        .map_err(|_| FleetRuntimeUseError::InvalidAgentPrincipal)?;
    Ok(FleetAllocationGrantV1 {
        allocation_id: grant.allocation_id.clone(),
        request_id: grant.request_id.clone(),
        agent_id,
        host_id: grant.host_id.clone(),
        failure_domain_id: grant.failure_domain_id.clone(),
        host_generation: grant.host_generation,
        authority_epoch: grant.authority_epoch,
        lease_generation: grant.lease_generation,
        expires_at_ms: grant.expires_at_ms,
        resources: grant.resources,
        semantic_digest: grant.semantic_digest.clone(),
    })
}

fn digest_parts(domain: &[u8], parts: &[&[u8]]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(domain);
    for part in parts {
        hasher.update((part.len() as u64).to_be_bytes());
        hasher.update(part);
    }
    hasher.finalize().into()
}

#[cfg(test)]
#[path = "runtime_use_tests.rs"]
mod tests;
