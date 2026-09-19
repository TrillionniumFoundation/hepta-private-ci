use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::FleetResourceAxisV1;
use crate::FleetResourceVectorV1;
use crate::LocalAllocationCandidateV1;
use crate::LocalAllocationError;
use crate::LocalHostCapacityCandidateV1;
use crate::MAX_LOCAL_ALLOCATION_CANDIDATES;
use crate::calculate_local_allocation_v1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetPlacementRequestV1 {
    pub allocation_id: String,
    pub request_id: String,
    pub agent_id: AgentId,
    pub caller_supplied_weight: u32,
    pub minimum: FleetResourceVectorV1,
    pub desired: FleetResourceVectorV1,
    pub allowed_failure_domains: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetPlacementAssignmentV1 {
    pub allocation_id: String,
    pub request_id: String,
    pub agent_id: AgentId,
    pub host_id: String,
    pub failure_domain_id: String,
    pub resources: FleetResourceVectorV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetPlacementPlanV1 {
    pub plan_sha256: Sha256Digest,
    pub assignments: Vec<FleetPlacementAssignmentV1>,
}

pub fn place_and_allocate_v1(
    host_candidates: &[LocalHostCapacityCandidateV1],
    placement_requests: &[FleetPlacementRequestV1],
) -> Result<FleetPlacementPlanV1, LocalAllocationError> {
    if placement_requests.is_empty() {
        return Err(LocalAllocationError::EmptyCandidates);
    }
    if placement_requests.len() > MAX_LOCAL_ALLOCATION_CANDIDATES {
        return Err(LocalAllocationError::CandidateLimitExceeded);
    }

    let mut hosts = host_candidates.to_vec();
    hosts.sort();
    let host_by_id: BTreeMap<_, _> = hosts
        .iter()
        .map(|host| (host.host_id.clone(), host.clone()))
        .collect();
    if host_by_id.len() != hosts.len() {
        let duplicate = hosts
            .windows(2)
            .find(|pair| pair[0].host_id == pair[1].host_id)
            .map(|pair| pair[0].host_id.clone())
            .unwrap_or_else(|| "unknown".to_string());
        return Err(LocalAllocationError::DuplicateHost(duplicate));
    }

    let mut requests = placement_requests.to_vec();
    requests.sort_by(|left, right| {
        left.request_id
            .cmp(&right.request_id)
            .then_with(|| left.allocation_id.cmp(&right.allocation_id))
            .then_with(|| left.agent_id.cmp(&right.agent_id))
    });
    let mut request_ids = BTreeSet::new();
    let mut allocation_ids = BTreeSet::new();
    let mut agent_ids = BTreeSet::new();
    for request in &requests {
        validate_identifier(&request.allocation_id, "allocation_id")?;
        validate_identifier(&request.request_id, "request_id")?;
        for domain in &request.allowed_failure_domains {
            validate_identifier(domain, "failure_domain_id")?;
        }
        if !request_ids.insert(request.request_id.clone()) {
            return Err(LocalAllocationError::DuplicateRequest(request.request_id.clone()));
        }
        if !allocation_ids.insert(request.allocation_id.clone()) {
            return Err(LocalAllocationError::InvalidIdentifier("allocation_id"));
        }
        if !agent_ids.insert(request.agent_id.clone()) {
            return Err(LocalAllocationError::DuplicateAgent(request.agent_id.to_string()));
        }
        if request.minimum.is_zero() && request.desired.is_zero() {
            return Err(LocalAllocationError::EmptyDesiredResources(
                request.request_id.clone(),
            ));
        }
        for axis in FleetResourceAxisV1::ALL {
            if axis.read(request.minimum) > axis.read(request.desired) {
                return Err(LocalAllocationError::MinimumExceedsDesired {
                    request_id: request.request_id.clone(),
                    axis,
                });
            }
        }
    }

    let mut reserved: BTreeMap<String, FleetResourceVectorV1> = hosts
        .iter()
        .map(|host| (host.host_id.clone(), FleetResourceVectorV1::default()))
        .collect();
    let mut bound = Vec::with_capacity(requests.len());
    for request in &requests {
        let mut best: Option<(&LocalHostCapacityCandidateV1, u128)> = None;
        for host in &hosts {
            if !request.allowed_failure_domains.is_empty()
                && !request
                    .allowed_failure_domains
                    .iter()
                    .any(|domain| domain == &host.failure_domain_id)
            {
                continue;
            }
            let used = reserved
                .get(&host.host_id)
                .copied()
                .ok_or(LocalAllocationError::ArithmeticInvariant(
                    "placement reservation",
                ))?;
            let Some(after) = used.checked_add(request.minimum) else {
                return Err(LocalAllocationError::ArithmeticInvariant(
                    "placement minimum sum",
                ));
            };
            if !after.fits_within(host.caller_supplied_allocatable) {
                continue;
            }
            let score = normalized_load(after, host.caller_supplied_allocatable)?;
            match best {
                None => best = Some((host, score)),
                Some((current, current_score))
                    if score < current_score
                        || (score == current_score && host.host_id < current.host_id) =>
                {
                    best = Some((host, score));
                }
                Some(_) => {}
            }
        }
        let Some((host, _)) = best else {
            return Err(LocalAllocationError::NoEligibleHost(
                request.request_id.clone(),
            ));
        };
        let next = reserved
            .get(&host.host_id)
            .copied()
            .and_then(|value| value.checked_add(request.minimum))
            .ok_or(LocalAllocationError::ArithmeticInvariant(
                "placement reservation update",
            ))?;
        reserved.insert(host.host_id.clone(), next);
        bound.push(LocalAllocationCandidateV1 {
            request_id: request.request_id.clone(),
            agent_id: request.agent_id.clone(),
            host_id: host.host_id.clone(),
            caller_supplied_weight: request.caller_supplied_weight,
            caller_supplied_minimum: request.minimum,
            caller_supplied_desired: request.desired,
        });
    }

    let calculation = calculate_local_allocation_v1(&hosts, &bound)?;
    let by_request: BTreeMap<_, _> = requests
        .iter()
        .map(|request| (request.request_id.as_str(), request))
        .collect();
    let assignments = calculation
        .shares()
        .iter()
        .map(|share| {
            let request = by_request.get(share.request_id.as_str()).ok_or(
                LocalAllocationError::ArithmeticInvariant("placement output binding"),
            )?;
            Ok(FleetPlacementAssignmentV1 {
                allocation_id: request.allocation_id.clone(),
                request_id: share.request_id.clone(),
                agent_id: share.agent_id.clone(),
                host_id: share.host_id.clone(),
                failure_domain_id: share.failure_domain_id.clone(),
                resources: share.resources,
            })
        })
        .collect::<Result<Vec<_>, LocalAllocationError>>()?;
    let plan_sha256 = Sha256Digest::for_bytes(
        &serde_json::to_vec(&assignments)
            .map_err(|_| LocalAllocationError::ArithmeticInvariant("placement digest"))?,
    );
    Ok(FleetPlacementPlanV1 {
        plan_sha256,
        assignments,
    })
}

fn normalized_load(
    used: FleetResourceVectorV1,
    capacity: FleetResourceVectorV1,
) -> Result<u128, LocalAllocationError> {
    FleetResourceAxisV1::ALL.iter().try_fold(0_u128, |sum, axis| {
        let numerator = u128::from(axis.read(used));
        let denominator = u128::from(axis.read(capacity).max(1));
        let scaled = numerator
            .checked_mul(1_000_000)
            .ok_or(LocalAllocationError::ArithmeticInvariant(
                "placement load scale",
            ))?
            / denominator;
        sum.checked_add(scaled)
            .ok_or(LocalAllocationError::ArithmeticInvariant(
                "placement load sum",
            ))
    })
}

fn validate_identifier(value: &str, label: &'static str) -> Result<(), LocalAllocationError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        return Err(LocalAllocationError::InvalidIdentifier(label));
    }
    Ok(())
}
