use std::collections::{BTreeMap, BTreeSet};

use codex_hepta_contracts::AgentId;
use thiserror::Error;

use crate::{
    FleetResourceVectorV1, LocalAllocationCandidateV1, LocalAllocationCalculationV1,
    LocalAllocationError, LocalHostCapacityCandidateV1, calculate_local_allocation_v1,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlacementRequestV1 {
    pub request_id: String,
    pub agent_id: AgentId,
    pub eligible_host_ids: Vec<String>,
    pub weight: u32,
    pub minimum: FleetResourceVectorV1,
    pub desired: FleetResourceVectorV1,
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum PlacementError {
    #[error("placement request has no eligible host: {0}")]
    NoEligibleHost(String),
    #[error("placement request cannot satisfy minimum resources: {0}")]
    NoCapacity(String),
    #[error(transparent)]
    Allocation(#[from] LocalAllocationError),
}

pub fn place_and_allocate_v1(
    hosts: &[LocalHostCapacityCandidateV1],
    requests: &[PlacementRequestV1],
) -> Result<LocalAllocationCalculationV1, PlacementError> {
    let host_map: BTreeMap<_, _> = hosts.iter().map(|h| (h.host_id.as_str(), h)).collect();
    let mut remaining: BTreeMap<String, FleetResourceVectorV1> = hosts
        .iter()
        .map(|h| (h.host_id.clone(), h.caller_supplied_allocatable))
        .collect();

    let mut ordered: Vec<_> = requests.iter().collect();
    ordered.sort_by(|a, b| a.request_id.cmp(&b.request_id).then_with(|| a.agent_id.cmp(&b.agent_id)));

    let mut bound = Vec::with_capacity(ordered.len());
    for request in ordered {
        let eligible: BTreeSet<_> = request.eligible_host_ids.iter().map(String::as_str).collect();
        if eligible.is_empty() || !eligible.iter().any(|id| host_map.contains_key(id)) {
            return Err(PlacementError::NoEligibleHost(request.request_id.clone()));
        }

        let mut best: Option<(String, FleetResourceVectorV1)> = None;
        for host_id in eligible {
            let Some(current) = remaining.get(host_id).copied() else { continue };
            let Some(after) = current.checked_sub(request.minimum) else { continue };
            match &best {
                None => best = Some((host_id.to_string(), after)),
                Some((best_id, best_after)) => {
                    if after > *best_after || (after == *best_after && host_id < best_id.as_str()) {
                        best = Some((host_id.to_string(), after));
                    }
                }
            }
        }
        let Some((host_id, after)) = best else {
            return Err(PlacementError::NoCapacity(request.request_id.clone()));
        };
        remaining.insert(host_id.clone(), after);
        bound.push(LocalAllocationCandidateV1 {
            request_id: request.request_id.clone(),
            agent_id: request.agent_id.clone(),
            host_id,
            caller_supplied_weight: request.weight,
            caller_supplied_minimum: request.minimum,
            caller_supplied_desired: request.desired,
        });
    }

    calculate_local_allocation_v1(hosts, &bound).map_err(Into::into)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn agent(index: usize) -> AgentId {
        AgentId::parse(format!("00000000-0000-4000-8000-{index:012x}")).expect("agent")
    }

    fn vector(turns: u64) -> FleetResourceVectorV1 {
        FleetResourceVectorV1 { concurrent_turns: turns, ..Default::default() }
    }

    #[test]
    fn placement_is_deterministic_and_spreads_by_remaining_capacity() {
        let hosts = vec![
            LocalHostCapacityCandidateV1 { host_id: "a".into(), failure_domain_id: "rack-a".into(), caller_supplied_allocatable: vector(2) },
            LocalHostCapacityCandidateV1 { host_id: "b".into(), failure_domain_id: "rack-b".into(), caller_supplied_allocatable: vector(4) },
        ];
        let requests = vec![
            PlacementRequestV1 { request_id: "r2".into(), agent_id: agent(2), eligible_host_ids: vec!["a".into(), "b".into()], weight: 1, minimum: vector(1), desired: vector(2) },
            PlacementRequestV1 { request_id: "r1".into(), agent_id: agent(1), eligible_host_ids: vec!["a".into(), "b".into()], weight: 1, minimum: vector(1), desired: vector(2) },
        ];
        let result = place_and_allocate_v1(&hosts, &requests).expect("place");
        assert_eq!(result.shares()[0].host_id, "b");
        assert_eq!(result.shares()[1].host_id, "b");
    }
}
