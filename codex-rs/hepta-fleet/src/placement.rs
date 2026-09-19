use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::FleetResourceAxisV1;
use crate::FleetResourceVectorV1;
use crate::LocalAllocationCandidateV1;
use crate::LocalAllocationError;
use crate::LocalHostCapacityCandidateV1;
use crate::MAX_LOCAL_ALLOCATION_WEIGHT;
use crate::calculate_local_allocation_v1;

pub const FLEET_PLACEMENT_SCHEMA_VERSION: u32 = 1;
pub const FLEET_CAPACITY_OBSERVATION_SCHEMA_VERSION: u32 = 1;
pub const MAX_FLEET_LEASE_TTL_MS: u64 = 300_000;
const MAX_IDENTIFIER_BYTES: usize = 128;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetHostCapacityObservationV1 {
    pub schema_version: u32,
    pub host_id: String,
    pub failure_domain_id: String,
    pub host_generation: u64,
    pub authority_epoch: u64,
    pub observed_at_unix_ms: u64,
    pub valid_until_unix_ms: u64,
    pub capacity: FleetResourceVectorV1,
}

impl FleetHostCapacityObservationV1 {
    pub fn new(
        host_id: String,
        failure_domain_id: String,
        host_generation: u64,
        authority_epoch: u64,
        observed_at_unix_ms: u64,
        valid_until_unix_ms: u64,
        capacity: FleetResourceVectorV1,
    ) -> Result<Self, FleetPlacementError> {
        let observation = Self {
            schema_version: FLEET_CAPACITY_OBSERVATION_SCHEMA_VERSION,
            host_id,
            failure_domain_id,
            host_generation,
            authority_epoch,
            observed_at_unix_ms,
            valid_until_unix_ms,
            capacity,
        };
        observation.validate()?;
        Ok(observation)
    }

    pub fn signing_bytes(&self, signer_id: &str) -> Result<Vec<u8>, FleetPlacementError> {
        self.validate()?;
        validate_identifier(signer_id, "capacity signer")?;
        let mut bytes = b"hepta.runtime-fleet.capacity-observation.v1\0".to_vec();
        push_text(&mut bytes, signer_id)?;
        bytes.extend(
            serde_json::to_vec(self)
                .map_err(|error| FleetPlacementError::Encoding(error.to_string()))?,
        );
        Ok(bytes)
    }

    pub fn validate(&self) -> Result<(), FleetPlacementError> {
        if self.schema_version != FLEET_CAPACITY_OBSERVATION_SCHEMA_VERSION {
            return Err(FleetPlacementError::InvalidObservation(
                "unsupported capacity observation schema".to_string(),
            ));
        }
        validate_identifier(&self.host_id, "host_id")?;
        validate_identifier(&self.failure_domain_id, "failure_domain_id")?;
        if self.host_generation == 0
            || self.authority_epoch == 0
            || self.observed_at_unix_ms >= self.valid_until_unix_ms
            || !self.capacity.all_axes_nonzero()
        {
            return Err(FleetPlacementError::InvalidObservation(
                "capacity observation has invalid generation, epoch, time, or capacity".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedFleetHostCapacityObservationV1 {
    pub signer_id: String,
    pub observation: FleetHostCapacityObservationV1,
    pub signature: Vec<u8>,
}

#[derive(Debug)]
pub struct VerifiedFleetHostCapacityObservationV1 {
    observation: FleetHostCapacityObservationV1,
}

impl VerifiedFleetHostCapacityObservationV1 {
    pub fn observation(&self) -> &FleetHostCapacityObservationV1 {
        &self.observation
    }

    pub fn into_observation(self) -> FleetHostCapacityObservationV1 {
        self.observation
    }
}

#[derive(Clone, Debug)]
pub struct FleetCapacityVerifierV1 {
    signer_id: String,
    key: VerifyingKey,
}

impl FleetCapacityVerifierV1 {
    pub fn new(signer_id: String, verifying_key: [u8; 32]) -> Result<Self, FleetPlacementError> {
        validate_identifier(&signer_id, "capacity signer")?;
        let key = VerifyingKey::from_bytes(&verifying_key)
            .map_err(|_| FleetPlacementError::InvalidCapacitySignature)?;
        if key.is_weak() {
            return Err(FleetPlacementError::InvalidCapacitySignature);
        }
        Ok(Self { signer_id, key })
    }

    pub fn verify(
        &self,
        signed: &SignedFleetHostCapacityObservationV1,
    ) -> Result<VerifiedFleetHostCapacityObservationV1, FleetPlacementError> {
        if signed.signer_id != self.signer_id {
            return Err(FleetPlacementError::InvalidCapacitySignature);
        }
        let input = signed.observation.signing_bytes(&signed.signer_id)?;
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| FleetPlacementError::InvalidCapacitySignature)?;
        self.key
            .verify_strict(&input, &signature)
            .map_err(|_| FleetPlacementError::InvalidCapacitySignature)?;
        Ok(VerifiedFleetHostCapacityObservationV1 {
            observation: signed.observation.clone(),
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetPlacementHostV1 {
    pub observation: FleetHostCapacityObservationV1,
    /// Capacity remaining after already committed durable grants are removed.
    pub available: FleetResourceVectorV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetPlacementRequestV1 {
    pub request_id: String,
    pub agent_id: AgentId,
    pub principal_id: String,
    pub weight: u32,
    pub minimum: FleetResourceVectorV1,
    pub desired: FleetResourceVectorV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetPlacementPolicyV1 {
    pub policy_id: String,
    pub revision: u64,
    pub content_sha256: Sha256Digest,
    pub authority_epoch: u64,
    pub lease_ttl_ms: u64,
}

impl FleetPlacementPolicyV1 {
    pub fn validate(&self) -> Result<(), FleetPlacementError> {
        validate_identifier(&self.policy_id, "policy_id")?;
        if self.revision == 0
            || self.authority_epoch == 0
            || self.lease_ttl_ms == 0
            || self.lease_ttl_ms > MAX_FLEET_LEASE_TTL_MS
        {
            return Err(FleetPlacementError::InvalidPolicy);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetPlacementShareV1 {
    pub request_id: String,
    pub agent_id: AgentId,
    pub principal_id: String,
    pub host_id: String,
    pub failure_domain_id: String,
    pub host_generation: u64,
    pub resources: FleetResourceVectorV1,
    pub expires_at_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetAllocationPlanV1 {
    pub schema_version: u32,
    pub principal_id: String,
    pub authority_epoch: u64,
    pub calculated_at_unix_ms: u64,
    pub policy: FleetPlacementPolicyV1,
    pub request_set_sha256: Sha256Digest,
    pub host_set_sha256: Sha256Digest,
    pub shares: Vec<FleetPlacementShareV1>,
    pub plan_sha256: Sha256Digest,
}

#[derive(Serialize)]
struct FleetAllocationPlanContent<'a> {
    schema_version: u32,
    principal_id: &'a str,
    authority_epoch: u64,
    calculated_at_unix_ms: u64,
    policy: &'a FleetPlacementPolicyV1,
    request_set_sha256: &'a Sha256Digest,
    host_set_sha256: &'a Sha256Digest,
    shares: &'a [FleetPlacementShareV1],
}

impl FleetAllocationPlanV1 {
    pub fn validate(&self) -> Result<(), FleetPlacementError> {
        if self.schema_version != FLEET_PLACEMENT_SCHEMA_VERSION
            || self.authority_epoch == 0
            || self.authority_epoch != self.policy.authority_epoch
            || self.shares.is_empty()
        {
            return Err(FleetPlacementError::InvalidPlan);
        }
        validate_identifier(&self.principal_id, "principal_id")?;
        self.policy.validate()?;
        let mut requests = BTreeSet::new();
        for share in &self.shares {
            validate_identifier(&share.request_id, "request_id")?;
            validate_identifier(&share.principal_id, "principal_id")?;
            validate_identifier(&share.host_id, "host_id")?;
            validate_identifier(&share.failure_domain_id, "failure_domain_id")?;
            if share.principal_id != self.principal_id
                || share.host_generation == 0
                || share.expires_at_unix_ms <= self.calculated_at_unix_ms
                || share.resources.is_zero()
                || !requests.insert(share.request_id.clone())
            {
                return Err(FleetPlacementError::InvalidPlan);
            }
        }
        let expected = digest_plan_content(
            self.schema_version,
            &self.principal_id,
            self.authority_epoch,
            self.calculated_at_unix_ms,
            &self.policy,
            &self.request_set_sha256,
            &self.host_set_sha256,
            &self.shares,
        )?;
        if expected != self.plan_sha256 {
            return Err(FleetPlacementError::PlanDigestMismatch);
        }
        Ok(())
    }

    pub fn final_use_binding(
        &self,
        destination_id: &str,
    ) -> Result<FinalUseBinding, FleetPlacementError> {
        self.validate()?;
        validate_identifier(destination_id, "destination_id")?;
        Ok(FinalUseBinding {
            subject_id: self.principal_id.clone(),
            destination_id: destination_id.to_string(),
            request_sha256: domain_digest(
                b"hepta.runtime-fleet.final-use.request.v1\0",
                self.request_set_sha256.as_str().as_bytes(),
            ),
            scope_sha256: domain_digest(
                b"hepta.runtime-fleet.final-use.scope.v1\0",
                self.host_set_sha256.as_str().as_bytes(),
            ),
            payload_sha256: domain_digest(
                b"hepta.runtime-fleet.final-use.payload.v1\0",
                self.plan_sha256.as_str().as_bytes(),
            ),
        })
    }
}

pub fn calculate_fleet_placement_v1(
    hosts: &[FleetPlacementHostV1],
    requests: &[FleetPlacementRequestV1],
    policy: &FleetPlacementPolicyV1,
    now_unix_ms: u64,
) -> Result<FleetAllocationPlanV1, FleetPlacementError> {
    policy.validate()?;
    if hosts.is_empty() {
        return Err(FleetPlacementError::EmptyHosts);
    }
    if requests.is_empty() {
        return Err(FleetPlacementError::EmptyRequests);
    }

    let mut hosts = hosts.to_vec();
    hosts.sort_by(|left, right| left.observation.host_id.cmp(&right.observation.host_id));
    let mut host_ids = BTreeSet::new();
    for host in &hosts {
        host.observation.validate()?;
        if !host_ids.insert(host.observation.host_id.clone()) {
            return Err(FleetPlacementError::DuplicateHost(
                host.observation.host_id.clone(),
            ));
        }
        if host.observation.authority_epoch != policy.authority_epoch
            || now_unix_ms < host.observation.observed_at_unix_ms
            || now_unix_ms >= host.observation.valid_until_unix_ms
            || !host.available.fits(host.observation.capacity)
        {
            return Err(FleetPlacementError::UnavailableHost(
                host.observation.host_id.clone(),
            ));
        }
    }

    let mut requests = requests.to_vec();
    requests.sort_by(|left, right| {
        left.request_id
            .cmp(&right.request_id)
            .then_with(|| left.agent_id.cmp(&right.agent_id))
    });
    let principal_id = requests
        .first()
        .map(|request| request.principal_id.clone())
        .ok_or(FleetPlacementError::EmptyRequests)?;
    validate_identifier(&principal_id, "principal_id")?;
    let mut request_ids = BTreeSet::new();
    for request in &requests {
        validate_request(request)?;
        if request.principal_id != principal_id {
            return Err(FleetPlacementError::MixedPrincipals);
        }
        if !request_ids.insert(request.request_id.clone()) {
            return Err(FleetPlacementError::DuplicateRequest(
                request.request_id.clone(),
            ));
        }
    }

    let mut reserved = vec![FleetResourceVectorV1::default(); hosts.len()];
    let mut assigned_host = BTreeMap::new();
    for request in &requests {
        let mut selected: Option<(usize, u64, &str)> = None;
        for (index, host) in hosts.iter().enumerate() {
            let Some(next_reserved) = reserved[index].checked_add(request.minimum) else {
                continue;
            };
            if !next_reserved.fits(host.available)
                || !has_serviceable_capacity(request.desired, host.available)
            {
                continue;
            }
            let Some(utilization) = next_reserved.dominant_utilization_ppm(host.available) else {
                continue;
            };
            let candidate = (index, utilization, host.observation.host_id.as_str());
            let replace = selected
                .as_ref()
                .is_none_or(|current| (utilization, candidate.2) < (current.1, current.2));
            if replace {
                selected = Some(candidate);
            }
        }
        let Some((index, _, _)) = selected else {
            return Err(FleetPlacementError::NoFeasibleHost(
                request.request_id.clone(),
            ));
        };
        reserved[index] = reserved[index]
            .checked_add(request.minimum)
            .ok_or(FleetPlacementError::ArithmeticInvariant)?;
        assigned_host.insert(request.request_id.clone(), index);
    }

    let local_hosts = hosts
        .iter()
        .map(|host| LocalHostCapacityCandidateV1 {
            host_id: host.observation.host_id.clone(),
            failure_domain_id: host.observation.failure_domain_id.clone(),
            caller_supplied_allocatable: host.available,
        })
        .collect::<Vec<_>>();
    let local_requests = requests
        .iter()
        .map(|request| {
            let index = assigned_host
                .get(&request.request_id)
                .copied()
                .ok_or(FleetPlacementError::ArithmeticInvariant)?;
            Ok(LocalAllocationCandidateV1 {
                request_id: request.request_id.clone(),
                agent_id: request.agent_id.clone(),
                host_id: hosts[index].observation.host_id.clone(),
                caller_supplied_weight: request.weight,
                caller_supplied_minimum: request.minimum,
                caller_supplied_desired: request.desired,
            })
        })
        .collect::<Result<Vec<_>, FleetPlacementError>>()?;
    let calculation = calculate_local_allocation_v1(&local_hosts, &local_requests)?;

    let requests_by_id = requests
        .iter()
        .map(|request| (request.request_id.as_str(), request))
        .collect::<BTreeMap<_, _>>();
    let hosts_by_id = hosts
        .iter()
        .map(|host| (host.observation.host_id.as_str(), host))
        .collect::<BTreeMap<_, _>>();
    let requested_expiry = now_unix_ms
        .checked_add(policy.lease_ttl_ms)
        .ok_or(FleetPlacementError::ArithmeticInvariant)?;
    let shares = calculation
        .shares()
        .iter()
        .map(|share| {
            let request = requests_by_id
                .get(share.request_id.as_str())
                .copied()
                .ok_or(FleetPlacementError::ArithmeticInvariant)?;
            let host = hosts_by_id
                .get(share.host_id.as_str())
                .copied()
                .ok_or(FleetPlacementError::ArithmeticInvariant)?;
            let expires_at_unix_ms = requested_expiry.min(host.observation.valid_until_unix_ms);
            if expires_at_unix_ms <= now_unix_ms {
                return Err(FleetPlacementError::UnavailableHost(
                    host.observation.host_id.clone(),
                ));
            }
            Ok(FleetPlacementShareV1 {
                request_id: share.request_id.clone(),
                agent_id: share.agent_id.clone(),
                principal_id: request.principal_id.clone(),
                host_id: share.host_id.clone(),
                failure_domain_id: share.failure_domain_id.clone(),
                host_generation: host.observation.host_generation,
                resources: share.resources,
                expires_at_unix_ms,
            })
        })
        .collect::<Result<Vec<_>, FleetPlacementError>>()?;

    let request_set_sha256 = digest_json(
        b"hepta.runtime-fleet.placement-requests.v1\0",
        &requests,
    )?;
    let host_set_sha256 = digest_json(b"hepta.runtime-fleet.placement-hosts.v1\0", &hosts)?;
    let plan_sha256 = digest_plan_content(
        FLEET_PLACEMENT_SCHEMA_VERSION,
        &principal_id,
        policy.authority_epoch,
        now_unix_ms,
        policy,
        &request_set_sha256,
        &host_set_sha256,
        &shares,
    )?;
    let plan = FleetAllocationPlanV1 {
        schema_version: FLEET_PLACEMENT_SCHEMA_VERSION,
        principal_id,
        authority_epoch: policy.authority_epoch,
        calculated_at_unix_ms: now_unix_ms,
        policy: policy.clone(),
        request_set_sha256,
        host_set_sha256,
        shares,
        plan_sha256,
    };
    plan.validate()?;
    Ok(plan)
}

fn has_serviceable_capacity(
    desired: FleetResourceVectorV1,
    available: FleetResourceVectorV1,
) -> bool {
    FleetResourceAxisV1::ALL
        .iter()
        .any(|axis| axis.read(desired) > 0 && axis.read(available) > 0)
}

fn validate_request(request: &FleetPlacementRequestV1) -> Result<(), FleetPlacementError> {
    validate_identifier(&request.request_id, "request_id")?;
    validate_identifier(&request.principal_id, "principal_id")?;
    if !(1..=MAX_LOCAL_ALLOCATION_WEIGHT).contains(&request.weight)
        || request.desired.is_zero()
    {
        return Err(FleetPlacementError::InvalidRequest(
            request.request_id.clone(),
        ));
    }
    for axis in FleetResourceAxisV1::ALL {
        if axis.read(request.minimum) > axis.read(request.desired) {
            return Err(FleetPlacementError::InvalidRequest(
                request.request_id.clone(),
            ));
        }
    }
    Ok(())
}

fn digest_plan_content(
    schema_version: u32,
    principal_id: &str,
    authority_epoch: u64,
    calculated_at_unix_ms: u64,
    policy: &FleetPlacementPolicyV1,
    request_set_sha256: &Sha256Digest,
    host_set_sha256: &Sha256Digest,
    shares: &[FleetPlacementShareV1],
) -> Result<Sha256Digest, FleetPlacementError> {
    digest_json(
        b"hepta.runtime-fleet.allocation-plan.v1\0",
        &FleetAllocationPlanContent {
            schema_version,
            principal_id,
            authority_epoch,
            calculated_at_unix_ms,
            policy,
            request_set_sha256,
            host_set_sha256,
            shares,
        },
    )
}

fn digest_json<T: Serialize>(
    domain: &[u8],
    value: &T,
) -> Result<Sha256Digest, FleetPlacementError> {
    let encoded =
        serde_json::to_vec(value).map_err(|error| FleetPlacementError::Encoding(error.to_string()))?;
    let mut bytes = Vec::with_capacity(domain.len() + encoded.len());
    bytes.extend_from_slice(domain);
    bytes.extend_from_slice(&encoded);
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn domain_digest(domain: &[u8], value: &[u8]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(domain);
    hasher.update(value);
    hasher.finalize().into()
}

fn validate_identifier(value: &str, label: &'static str) -> Result<(), FleetPlacementError> {
    if value.is_empty()
        || value.len() > MAX_IDENTIFIER_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
    {
        return Err(FleetPlacementError::InvalidIdentifier(label));
    }
    Ok(())
}

fn push_text(output: &mut Vec<u8>, value: &str) -> Result<(), FleetPlacementError> {
    let length =
        u32::try_from(value.len()).map_err(|_| FleetPlacementError::ArithmeticInvariant)?;
    output.extend_from_slice(&length.to_be_bytes());
    output.extend_from_slice(value.as_bytes());
    Ok(())
}

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum FleetPlacementError {
    #[error("fleet placement requires at least one host")]
    EmptyHosts,
    #[error("fleet placement requires at least one request")]
    EmptyRequests,
    #[error("invalid fleet placement identifier: {0}")]
    InvalidIdentifier(&'static str),
    #[error("invalid capacity observation: {0}")]
    InvalidObservation(String),
    #[error("capacity observation signature is invalid")]
    InvalidCapacitySignature,
    #[error("duplicate fleet host: {0}")]
    DuplicateHost(String),
    #[error("duplicate fleet request: {0}")]
    DuplicateRequest(String),
    #[error("fleet placement batch contains multiple principals")]
    MixedPrincipals,
    #[error("fleet placement policy is invalid")]
    InvalidPolicy,
    #[error("fleet host is unavailable: {0}")]
    UnavailableHost(String),
    #[error("fleet request is invalid: {0}")]
    InvalidRequest(String),
    #[error("no feasible host for fleet request: {0}")]
    NoFeasibleHost(String),
    #[error("fleet allocation plan is invalid")]
    InvalidPlan,
    #[error("fleet allocation plan digest mismatch")]
    PlanDigestMismatch,
    #[error("fleet placement arithmetic invariant failed")]
    ArithmeticInvariant,
    #[error("fleet placement encoding failed: {0}")]
    Encoding(String),
    #[error(transparent)]
    LocalAllocation(#[from] LocalAllocationError),
}
