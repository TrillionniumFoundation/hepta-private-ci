use std::collections::BTreeMap;

use crate::LocalAllocationCandidateV1;
use crate::LocalAllocationError;
use crate::LocalHostCapacityCandidateV1;
use crate::LocalResourceAxisV1;
use crate::MAX_LOCAL_ALLOCATION_CANDIDATES;
use crate::MAX_LOCAL_ALLOCATION_WEIGHT;
use crate::MAX_LOCAL_HOST_CANDIDATES;

const MAX_LOCAL_IDENTIFIER_BYTES: usize = 128;

pub(super) fn validate_counts(
    hosts: usize,
    candidates: usize,
) -> Result<(), LocalAllocationError> {
    if hosts == 0 {
        return Err(LocalAllocationError::EmptyHosts);
    }
    if hosts > MAX_LOCAL_HOST_CANDIDATES {
        return Err(LocalAllocationError::HostLimitExceeded);
    }
    if candidates == 0 {
        return Err(LocalAllocationError::EmptyCandidates);
    }
    if candidates > MAX_LOCAL_ALLOCATION_CANDIDATES {
        return Err(LocalAllocationError::CandidateLimitExceeded);
    }
    Ok(())
}

pub(super) fn validate_identifier_shapes(
    hosts: &[LocalHostCapacityCandidateV1],
    candidates: &[LocalAllocationCandidateV1],
) -> Result<(), LocalAllocationError> {
    for host in hosts {
        validate_identifier(host.host_id.as_str(), "host_id")?;
    }
    for host in hosts {
        validate_identifier(host.failure_domain_id.as_str(), "failure_domain_id")?;
    }
    for candidate in candidates {
        validate_identifier(candidate.request_id.as_str(), "request_id")?;
    }
    for candidate in candidates {
        validate_identifier(candidate.host_id.as_str(), "host_id")?;
    }
    Ok(())
}

pub(super) fn validate_hosts(
    hosts: &[&LocalHostCapacityCandidateV1],
) -> Result<(), LocalAllocationError> {
    for (index, host) in hosts.iter().enumerate() {
        if index > 0 && hosts[index - 1].host_id == host.host_id {
            return Err(LocalAllocationError::DuplicateHost(host.host_id.clone()));
        }
    }
    Ok(())
}

pub(super) fn validate_candidates(
    candidates: &[&LocalAllocationCandidateV1],
    hosts: &BTreeMap<&str, &LocalHostCapacityCandidateV1>,
) -> Result<(), LocalAllocationError> {
    for (index, candidate) in candidates.iter().enumerate() {
        if index > 0 && candidates[index - 1].request_id == candidate.request_id {
            return Err(LocalAllocationError::DuplicateRequest(
                candidate.request_id.clone(),
            ));
        }
        if !hosts.contains_key(candidate.host_id.as_str()) {
            return Err(LocalAllocationError::UnknownHost(candidate.host_id.clone()));
        }
        if !(1..=MAX_LOCAL_ALLOCATION_WEIGHT).contains(&candidate.caller_supplied_weight) {
            return Err(LocalAllocationError::InvalidWeight(
                candidate.request_id.clone(),
            ));
        }
        if LocalResourceAxisV1::ALL
            .iter()
            .all(|axis| axis.read(candidate.caller_supplied_desired) == 0)
        {
            return Err(LocalAllocationError::EmptyDesiredResources(
                candidate.request_id.clone(),
            ));
        }
        for axis in LocalResourceAxisV1::ALL {
            if axis.read(candidate.caller_supplied_minimum)
                > axis.read(candidate.caller_supplied_desired)
            {
                return Err(LocalAllocationError::MinimumExceedsDesired {
                    request_id: candidate.request_id.clone(),
                    axis,
                });
            }
        }
    }
    Ok(())
}

fn validate_identifier(value: &str, label: &'static str) -> Result<(), LocalAllocationError> {
    if value.is_empty()
        || value.len() > MAX_LOCAL_IDENTIFIER_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        return Err(LocalAllocationError::InvalidIdentifier(label));
    }
    Ok(())
}
