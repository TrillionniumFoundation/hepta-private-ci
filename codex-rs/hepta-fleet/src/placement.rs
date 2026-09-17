use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::FleetAllocationStore;
use crate::FleetAllocationStoreError;
use crate::FleetResourceAxisV1;
use crate::FleetResourceVectorV1;
use crate::LocalAllocationCandidateV1;
use crate::LocalAllocationError;
use crate::LocalHostCapacityCandidateV1;
use crate::MAX_LOCAL_ALLOCATION_CANDIDATES;
use crate::MAX_LOCAL_ALLOCATION_WEIGHT;
use crate::calculate_local_allocation_v1;
use crate::lease_ledger::AllocationGrant;
use crate::lease_ledger::Error as LeaseError;
use crate::lease_ledger::HostObservation;
use crate::lease_ledger::LeaseLedger;

pub const FLEET_PLACEMENT_POLICY_VERSION: u32 = 1;
const CAPACITY_DESTINATION: &str = "runtime.fleet.capacity";
const PLACEMENT_DESTINATION: &str = "runtime.fleet.allocation";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetPlacementRequestV1 {
    pub allocation_id: String,
    pub request_id: String,
    pub agent_id: AgentId,
    pub weight: u32,
    pub minimum: FleetResourceVectorV1,
    pub desired: FleetResourceVectorV1,
    /// Digest of the upstream request semantics before placement.
    pub request_semantic_digest: String,
}

#[derive(Clone, Debug)]
pub struct FleetPlacementPlanV1 {
    source_generation: u64,
    authority_epoch: u64,
    expires_at_ms: u64,
    request_sha256: [u8; 32],
    payload_sha256: [u8; 32],
    grants: Vec<AllocationGrant>,
}

impl FleetPlacementPlanV1 {
    pub const fn source_generation(&self) -> u64 {
        self.source_generation
    }

    pub const fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    pub const fn expires_at_ms(&self) -> u64 {
        self.expires_at_ms
    }

    pub fn grants(&self) -> &[AllocationGrant] {
        &self.grants
    }

    pub fn payload_sha256_hex(&self) -> String {
        hex_digest(self.payload_sha256)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetPlacementCommitV1 {
    pub source_generation: u64,
    pub committed_generation: u64,
    pub payload_sha256: String,
    pub allocation_ids: Vec<String>,
}

#[derive(Debug, Error)]
pub enum FleetPlacementError {
    #[error("invalid fleet placement input: {0}")]
    Invalid(String),
    #[error("no eligible host can satisfy minimum resources for request {0}")]
    NoEligibleHost(String),
    #[error("allocation identity already exists: {0}")]
    AllocationExists(String),
    #[error("fleet placement arithmetic overflow")]
    ArithmeticOverflow,
    #[error(transparent)]
    Allocation(#[from] LocalAllocationError),
    #[error(transparent)]
    Lease(#[from] LeaseError),
    #[error(transparent)]
    Store(#[from] FleetAllocationStoreError),
    #[error(transparent)]
    Authority(#[from] FinalUseError),
}

/// Build the exact final-use binding required to admit a host-capacity observation.
/// The authority authenticates permission to publish this exact observation; the
/// trusted host observer remains responsible for the physical measurement itself.
pub fn capacity_observation_binding(
    observer_id: &str,
    expected_generation: u64,
    observation: &HostObservation,
) -> Result<FinalUseBinding, FleetPlacementError> {
    let payload_sha256 = digest_json(
        b"hepta.runtime-fleet.capacity-observation.v1\0",
        observation,
    )?;
    let request_sha256 = digest_parts(
        b"hepta.runtime-fleet.capacity-request.v1\0",
        &[
            &expected_generation.to_be_bytes(),
            observation.host_id.as_bytes(),
            &observation.generation.to_be_bytes(),
        ],
    );
    let scope_sha256 = digest_parts(
        b"hepta.runtime-fleet.capacity-scope.v1\0",
        &[
            observation.host_id.as_bytes(),
            observation.failure_domain_id.as_bytes(),
        ],
    );
    Ok(FinalUseBinding {
        subject_id: observer_id.to_string(),
        destination_id: CAPACITY_DESTINATION.to_string(),
        request_sha256,
        scope_sha256,
        payload_sha256,
    })
}

/// Final-authority-gated admission of one exact host observation into durable
/// Fleet state. A claimed nonce is never refunded after a stale/indeterminate
/// durable commit; the caller must reconcile before requesting new authority.
pub fn admit_host_with_authority(
    store: &FleetAllocationStore,
    authority: &FinalUseAuthority,
    signed: &SignedFinalUseGrant,
    observer_id: &str,
    expected_generation: u64,
    now_ms: u64,
    observation: HostObservation,
) -> Result<u64, FleetPlacementError> {
    let binding = capacity_observation_binding(observer_id, expected_generation, &observation)?;
    let token = authority.claim(signed, &binding)?;
    let result = authority.with_verified_use(token, &binding, || {
        store.admit_host(expected_generation, now_ms, observation)
    })?;
    result.map_err(Into::into)
}

/// Calculate deterministic placement and weighted allocation from the current
/// durable Fleet generation. This operation is authority-free and has no effect;
/// the returned plan must be independently authorized before commit.
pub fn plan_placement_v1(
    store: &FleetAllocationStore,
    now_ms: u64,
    authority_epoch: u64,
    expires_at_ms: u64,
    requests: &[FleetPlacementRequestV1],
) -> Result<FleetPlacementPlanV1, FleetPlacementError> {
    if authority_epoch == 0 || expires_at_ms <= now_ms {
        return Err(FleetPlacementError::Invalid(
            "authority epoch and lease expiry must be current".into(),
        ));
    }
    if requests.is_empty() || requests.len() > MAX_LOCAL_ALLOCATION_CANDIDATES {
        return Err(FleetPlacementError::Invalid(
            "placement request count is outside the pilot bound".into(),
        ));
    }
    let snapshot = store.load(now_ms)?;
    plan_from_ledger(
        snapshot.generation(),
        snapshot.ledger(),
        now_ms,
        authority_epoch,
        expires_at_ms,
        requests,
    )
}

/// Build the exact final-use binding for a previously calculated plan.
pub fn placement_authority_binding(
    actor_id: &str,
    plan: &FleetPlacementPlanV1,
) -> FinalUseBinding {
    let scope_sha256 = digest_parts(
        b"hepta.runtime-fleet.placement-scope.v1\0",
        &[
            &FLEET_PLACEMENT_POLICY_VERSION.to_be_bytes(),
            &plan.source_generation.to_be_bytes(),
            &plan.authority_epoch.to_be_bytes(),
            &plan.expires_at_ms.to_be_bytes(),
        ],
    );
    FinalUseBinding {
        subject_id: actor_id.to_string(),
        destination_id: PLACEMENT_DESTINATION.to_string(),
        request_sha256: plan.request_sha256,
        scope_sha256,
        payload_sha256: plan.payload_sha256,
    }
}

/// Revalidate final-use authority immediately before one atomic durable commit.
/// All grants are applied to a cloned ledger first; either the complete generation
/// is published or none of the plan becomes visible. Store publication may still
/// be reported as indeterminate after the create-only generation is linked but
/// before the directory fsync is observed; callers must reconcile that generation.
pub fn commit_placement_with_authority(
    store: &FleetAllocationStore,
    authority: &FinalUseAuthority,
    signed: &SignedFinalUseGrant,
    actor_id: &str,
    now_ms: u64,
    plan: FleetPlacementPlanV1,
) -> Result<FleetPlacementCommitV1, FleetPlacementError> {
    if plan.expires_at_ms <= now_ms {
        return Err(FleetPlacementError::Invalid(
            "placement plan lease expired before commit".into(),
        ));
    }
    let current = store.load(now_ms)?;
    if current.generation() != plan.source_generation {
        return Err(FleetAllocationStoreError::StaleGeneration {
            expected: plan.source_generation,
            current: current.generation(),
        }
        .into());
    }
    let mut next = current.ledger().clone();
    for grant in &plan.grants {
        next.issue(now_ms, grant.clone())?;
    }
    let binding = placement_authority_binding(actor_id, &plan);
    let token = authority.claim(signed, &binding)?;
    let commit = authority.with_verified_use(token, &binding, || {
        store.commit_ledger(plan.source_generation, now_ms, next)
    })?;
    let committed_generation = commit?;
    Ok(FleetPlacementCommitV1 {
        source_generation: plan.source_generation,
        committed_generation,
        payload_sha256: hex_digest(plan.payload_sha256),
        allocation_ids: plan
            .grants
            .iter()
            .map(|grant| grant.allocation_id.clone())
            .collect(),
    })
}

fn plan_from_ledger(
    source_generation: u64,
    ledger: &LeaseLedger,
    now_ms: u64,
    authority_epoch: u64,
    expires_at_ms: u64,
    requests: &[FleetPlacementRequestV1],
) -> Result<FleetPlacementPlanV1, FleetPlacementError> {
    let mut ordered = requests.to_vec();
    ordered.sort_by(|left, right| {
        left.request_id
            .cmp(&right.request_id)
            .then_with(|| left.agent_id.cmp(&right.agent_id))
            .then_with(|| left.allocation_id.cmp(&right.allocation_id))
    });
    validate_requests(ledger, &ordered)?;
    let request_sha256 = digest_json(b"hepta.runtime-fleet.placement-requests.v1\0", &ordered)?;

    let mut available = BTreeMap::new();
    let mut observations = BTreeMap::new();
    for (host_id, host) in ledger.hosts() {
        if now_ms < host.observed_at_ms
            || now_ms >= host.valid_until_ms
            || expires_at_ms > host.valid_until_ms
        {
            continue;
        }
        let committed = committed_resources(ledger, host_id, now_ms)?;
        let remaining = host
            .capacity
            .checked_sub(committed)
            .ok_or(FleetPlacementError::ArithmeticOverflow)?;
        if !remaining.is_zero() {
            available.insert(host_id.clone(), remaining);
            observations.insert(host_id.clone(), host.clone());
        }
    }
    if available.is_empty() {
        return Err(FleetPlacementError::NoEligibleHost(
            ordered[0].request_id.clone(),
        ));
    }

    let initial_available = available.clone();
    let mut assigned = BTreeMap::new();
    for request in &ordered {
        let selected = available
            .iter()
            .filter_map(|(host_id, remaining)| {
                if request.minimum.fits(*remaining) {
                    remaining
                        .checked_sub(request.minimum)
                        .map(|slack| (slack, host_id.clone()))
                } else {
                    None
                }
            })
            .min();
        let Some((_, host_id)) = selected else {
            return Err(FleetPlacementError::NoEligibleHost(
                request.request_id.clone(),
            ));
        };
        let remaining = available
            .get(&host_id)
            .copied()
            .ok_or(FleetPlacementError::ArithmeticOverflow)?
            .checked_sub(request.minimum)
            .ok_or(FleetPlacementError::ArithmeticOverflow)?;
        available.insert(host_id.clone(), remaining);
        assigned.insert(request.request_id.clone(), host_id);
    }

    let mut host_candidates = Vec::new();
    for (host_id, capacity) in &initial_available {
        if assigned.values().any(|assigned_host| assigned_host == host_id) {
            let observation = observations
                .get(host_id)
                .ok_or(FleetPlacementError::ArithmeticOverflow)?;
            host_candidates.push(LocalHostCapacityCandidateV1 {
                host_id: host_id.clone(),
                failure_domain_id: observation.failure_domain_id.clone(),
                caller_supplied_allocatable: *capacity,
            });
        }
    }
    let candidates: Vec<_> = ordered
        .iter()
        .map(|request| LocalAllocationCandidateV1 {
            request_id: request.request_id.clone(),
            agent_id: request.agent_id.clone(),
            host_id: assigned
                .get(&request.request_id)
                .expect("validated placement must bind every request")
                .clone(),
            caller_supplied_weight: request.weight,
            caller_supplied_minimum: request.minimum,
            caller_supplied_desired: request.desired,
        })
        .collect();
    let calculation = calculate_local_allocation_v1(&host_candidates, &candidates)?;
    let requests_by_id: BTreeMap<_, _> = ordered
        .iter()
        .map(|request| (request.request_id.as_str(), request))
        .collect();
    let mut grants = Vec::with_capacity(calculation.shares().len());
    for share in calculation.shares() {
        if share.resources.is_zero() {
            return Err(FleetPlacementError::NoEligibleHost(
                share.request_id.clone(),
            ));
        }
        let request = requests_by_id
            .get(share.request_id.as_str())
            .copied()
            .ok_or_else(|| FleetPlacementError::Invalid("allocation share lost its request".into()))?;
        let host = observations
            .get(&share.host_id)
            .ok_or_else(|| FleetPlacementError::Invalid("allocation share lost its host".into()))?;
        let semantic_digest = grant_semantic_digest(
            request,
            host,
            authority_epoch,
            expires_at_ms,
            share.resources,
        );
        grants.push(AllocationGrant {
            allocation_id: request.allocation_id.clone(),
            request_id: request.request_id.clone(),
            principal_id: request.agent_id.as_str().to_string(),
            host_id: share.host_id.clone(),
            failure_domain_id: share.failure_domain_id.clone(),
            host_generation: host.generation,
            authority_epoch,
            lease_generation: 1,
            expires_at_ms,
            resources: share.resources,
            semantic_digest,
            revoked: false,
        });
    }
    grants.sort_by(|left, right| left.allocation_id.cmp(&right.allocation_id));
    let payload_sha256 = digest_json(b"hepta.runtime-fleet.placement-plan.v1\0", &grants)?;
    Ok(FleetPlacementPlanV1 {
        source_generation,
        authority_epoch,
        expires_at_ms,
        request_sha256,
        payload_sha256,
        grants,
    })
}

fn validate_requests(
    ledger: &LeaseLedger,
    requests: &[FleetPlacementRequestV1],
) -> Result<(), FleetPlacementError> {
    let mut allocation_ids = BTreeSet::new();
    let mut request_ids = BTreeSet::new();
    for request in requests {
        if !allocation_ids.insert(request.allocation_id.as_str()) {
            return Err(FleetPlacementError::Invalid(
                "duplicate allocation identity".into(),
            ));
        }
        if !request_ids.insert(request.request_id.as_str()) {
            return Err(FleetPlacementError::Invalid(
                "duplicate placement request identity".into(),
            ));
        }
        if ledger.grants().contains_key(&request.allocation_id) {
            return Err(FleetPlacementError::AllocationExists(
                request.allocation_id.clone(),
            ));
        }
        if !(1..=MAX_LOCAL_ALLOCATION_WEIGHT).contains(&request.weight)
            || !valid_digest(&request.request_semantic_digest)
            || request.desired.is_zero()
        {
            return Err(FleetPlacementError::Invalid(format!(
                "invalid placement request {}",
                request.request_id
            )));
        }
        for axis in FleetResourceAxisV1::ALL {
            if axis.read(request.minimum) > axis.read(request.desired) {
                return Err(FleetPlacementError::Invalid(format!(
                    "minimum exceeds desired resources for {}",
                    request.request_id
                )));
            }
        }
    }
    Ok(())
}

fn committed_resources(
    ledger: &LeaseLedger,
    host_id: &str,
    now_ms: u64,
) -> Result<FleetResourceVectorV1, FleetPlacementError> {
    ledger
        .grants()
        .values()
        .filter(|grant| {
            grant.host_id == host_id && !grant.revoked && grant.expires_at_ms > now_ms
        })
        .try_fold(FleetResourceVectorV1::default(), |sum, grant| {
            sum.checked_add(grant.resources)
                .ok_or(FleetPlacementError::ArithmeticOverflow)
        })
}

fn grant_semantic_digest(
    request: &FleetPlacementRequestV1,
    host: &HostObservation,
    authority_epoch: u64,
    expires_at_ms: u64,
    resources: FleetResourceVectorV1,
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"hepta.runtime-fleet.allocation-grant.v1\0");
    push_text(&mut hasher, &request.allocation_id);
    push_text(&mut hasher, &request.request_id);
    push_text(&mut hasher, request.agent_id.as_str());
    push_text(&mut hasher, &request.request_semantic_digest);
    push_text(&mut hasher, &host.host_id);
    push_text(&mut hasher, &host.failure_domain_id);
    hasher.update(host.generation.to_be_bytes());
    hasher.update(authority_epoch.to_be_bytes());
    hasher.update(expires_at_ms.to_be_bytes());
    push_vector(&mut hasher, resources);
    let digest: [u8; 32] = hasher.finalize().into();
    hex_digest(digest)
}

fn digest_json<T: Serialize>(domain: &[u8], value: &T) -> Result<[u8; 32], FleetPlacementError> {
    let encoded = serde_json::to_vec(value)
        .map_err(|error| FleetPlacementError::Invalid(format!("canonical encoding failed: {error}")))?;
    Ok(digest_parts(domain, &[&encoded]))
}

fn digest_parts(domain: &[u8], parts: &[&[u8]]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(domain);
    for part in parts {
        hasher.update((*part).len().to_be_bytes());
        hasher.update(part);
    }
    hasher.finalize().into()
}

fn push_text(hasher: &mut Sha256, value: &str) {
    hasher.update((value.len() as u64).to_be_bytes());
    hasher.update(value.as_bytes());
}

fn push_vector(hasher: &mut Sha256, vector: FleetResourceVectorV1) {
    hasher.update(vector.concurrent_turns.to_be_bytes());
    hasher.update(vector.memory_mib.to_be_bytes());
    hasher.update(vector.tool_processes.to_be_bytes());
    hasher.update(vector.turn_queue_slots.to_be_bytes());
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && !value.bytes().all(|byte| byte == b'0')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn hex_digest(digest: [u8; 32]) -> String {
    use std::fmt::Write as _;

    let mut output = String::with_capacity(64);
    for byte in digest {
        write!(&mut output, "{byte:02x}").expect("writing to String cannot fail");
    }
    output
}

#[cfg(test)]
#[path = "placement_tests.rs"]
mod tests;
