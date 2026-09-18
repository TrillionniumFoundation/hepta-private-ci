use std::collections::BTreeMap;

use codex_hepta_contracts::AgentId;
use thiserror::Error;

use crate::FleetResourceArithmeticError;
use crate::FleetResourceVectorV1;
use crate::LocalAllocationCalculationV1;
use crate::LocalAllocationCandidateV1;
use crate::LocalAllocationError;
use crate::LocalHostCapacityCandidateV1;
use crate::calculate_local_allocation_v1;
use crate::capacity::ObservedFleetCapacityV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetPlacementHostV1 {
    pub observation: ObservedFleetCapacityV1,
    /// Capacity still available after already-committed durable grants.
    pub available: FleetResourceVectorV1,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct FleetPlacementRequestV1 {
    pub request_id: String,
    pub agent_id: AgentId,
    pub weight: u32,
    pub minimum: FleetResourceVectorV1,
    pub desired: FleetResourceVectorV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetPlacementAssignmentV1 {
    pub request_id: String,
    pub agent_id: AgentId,
    pub host_id: String,
    pub failure_domain_id: String,
    pub resources: FleetResourceVectorV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetPlacementPlanV1 {
    pub assignments: Vec<FleetPlacementAssignmentV1>,
    pub calculation: LocalAllocationCalculationV1,
}

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum FleetPlacementError {
    #[error("fleet placement requires at least one eligible host")]
    NoHosts,
    #[error("no host can satisfy minimum resources for request {0}")]
    NoEligibleHost(String),
    #[error("duplicate placement request {0}")]
    DuplicateRequest(String),
    #[error("invalid or internally inconsistent host observation {0}")]
    InvalidHostObservation(String),
    #[error("placement resource arithmetic failed")]
    ResourceArithmetic,
    #[error(transparent)]
    Allocation(#[from] LocalAllocationError),
}

/// Deterministically selects a host before invoking the existing weighted
/// max-min allocator. The caller supplies authenticated/fresh observations;
/// this function is still pure and carries no grant authority.
pub fn calculate_fleet_placement_v1(
    hosts: &[FleetPlacementHostV1],
    requests: &[FleetPlacementRequestV1],
) -> Result<FleetPlacementPlanV1, FleetPlacementError> {
    if hosts.is_empty() {
        return Err(FleetPlacementError::NoHosts);
    }

    let mut ordered_hosts = hosts.to_vec();
    ordered_hosts.sort_by(|left, right| {
        left.observation
            .host_id
            .cmp(&right.observation.host_id)
            .then_with(|| {
                left.observation
                    .failure_domain_id
                    .cmp(&right.observation.failure_domain_id)
            })
    });
    for host in &ordered_hosts {
        if host
            .observation
            .validate(host.observation.observed_at_ms)
            .is_err()
        {
            return Err(FleetPlacementError::InvalidHostObservation(
                host.observation.host_id.clone(),
            ));
        }
        if !host.available.fits(host.observation.capacity) {
            return Err(FleetPlacementError::ResourceArithmetic);
        }
    }

    let mut ordered_requests = requests.to_vec();
    ordered_requests.sort();
    for pair in ordered_requests.windows(2) {
        if pair[0].request_id == pair[1].request_id {
            return Err(FleetPlacementError::DuplicateRequest(
                pair[0].request_id.clone(),
            ));
        }
    }

    // Place the most constrained requests first. Sorting by request ID alone
    // can reject an otherwise feasible plan when a flexible request consumes
    // the only host capable of satisfying a later request. This remains a
    // bounded deterministic heuristic rather than a claim of global optimum.
    let mut prioritized_requests = Vec::with_capacity(ordered_requests.len());
    for request in ordered_requests {
        let eligible_hosts = ordered_hosts
            .iter()
            .filter(|host| request.minimum.fits(host.available))
            .count();
        if eligible_hosts == 0 {
            return Err(FleetPlacementError::NoEligibleHost(request.request_id));
        }
        prioritized_requests.push((eligible_hosts, request));
    }
    prioritized_requests.sort_by(|left, right| {
        left.0
            .cmp(&right.0)
            .then_with(|| left.1.request_id.cmp(&right.1.request_id))
            .then_with(|| left.1.agent_id.cmp(&right.1.agent_id))
    });

    let mut residual: Vec<_> = ordered_hosts.iter().map(|host| host.available).collect();
    let mut host_counts = vec![0_u64; ordered_hosts.len()];
    let mut domain_counts: BTreeMap<&str, u64> = BTreeMap::new();
    let mut bound = Vec::with_capacity(prioritized_requests.len());

    for (_, request) in &prioritized_requests {
        let mut eligible = Vec::new();
        for (index, host) in ordered_hosts.iter().enumerate() {
            if request.minimum.fits(residual[index]) {
                eligible.push((
                    *domain_counts
                        .get(host.observation.failure_domain_id.as_str())
                        .unwrap_or(&0),
                    host_counts[index],
                    host.observation.host_id.as_str(),
                    index,
                ));
            }
        }
        eligible.sort();
        let Some((_, _, _, selected)) = eligible.first().copied() else {
            return Err(FleetPlacementError::NoEligibleHost(
                request.request_id.clone(),
            ));
        };
        residual[selected] = residual[selected]
            .checked_sub(request.minimum)
            .map_err(map_resource_error)?;
        host_counts[selected] = host_counts[selected]
            .checked_add(1)
            .ok_or(FleetPlacementError::ResourceArithmetic)?;
        let domain = ordered_hosts[selected].observation.failure_domain_id.as_str();
        let count = domain_counts.entry(domain).or_default();
        *count = count
            .checked_add(1)
            .ok_or(FleetPlacementError::ResourceArithmetic)?;
        bound.push(LocalAllocationCandidateV1 {
            request_id: request.request_id.clone(),
            agent_id: request.agent_id.clone(),
            host_id: ordered_hosts[selected].observation.host_id.clone(),
            caller_supplied_weight: request.weight,
            caller_supplied_minimum: request.minimum,
            caller_supplied_desired: request.desired,
        });
    }

    let allocation_hosts: Vec<_> = ordered_hosts
        .iter()
        .map(|host| LocalHostCapacityCandidateV1 {
            host_id: host.observation.host_id.clone(),
            failure_domain_id: host.observation.failure_domain_id.clone(),
            caller_supplied_allocatable: host.available,
        })
        .collect();
    let calculation = calculate_local_allocation_v1(&allocation_hosts, &bound)?;
    let assignments = calculation
        .shares()
        .iter()
        .map(|share| FleetPlacementAssignmentV1 {
            request_id: share.request_id.clone(),
            agent_id: share.agent_id.clone(),
            host_id: share.host_id.clone(),
            failure_domain_id: share.failure_domain_id.clone(),
            resources: share.resources,
        })
        .collect();
    Ok(FleetPlacementPlanV1 {
        assignments,
        calculation,
    })
}

fn map_resource_error(_: FleetResourceArithmeticError) -> FleetPlacementError {
    FleetPlacementError::ResourceArithmetic
}

#[cfg(test)]
#[path = "placement_tests.rs"]
mod tests;
