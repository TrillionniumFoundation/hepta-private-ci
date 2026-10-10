//! Bounded, deterministic calculations over caller-supplied fleet inputs.
//!
//! This module is an owner-local calculator, not a wire contract, fleet-view
//! attestation, allocation grant, lease, scheduling decision, or effect
//! receipt. Host identities, failure domains, capacities, request weights,
//! floors, and demands are all supplied by the caller. A successful result
//! describes only those supplied values and always carries a deny-all claim
//! boundary. Publishing `fleet_allocation_grantV1` requires separately
//! registered owner receipts and authority integration that this module does
//! not provide.

use std::collections::BTreeMap;

use crate::LocalAllocationCalculationV1;
use crate::LocalAllocationCandidateV1;
use crate::LocalAllocationError;
use crate::LocalAllocationShareV1;
use crate::LocalHostCapacityCandidateV1;
use crate::LocalResourceAxisV1;
use crate::LocalResourceVectorV1;
use crate::MAX_LOCAL_ALLOCATION_WEIGHT;
use crate::allocation_digest::digest_calculation;
use crate::allocation_validation::validate_candidates;
use crate::allocation_validation::validate_counts;
use crate::allocation_validation::validate_hosts;
use crate::allocation_validation::validate_identifier_shapes;

// Greater than MAX_LOCAL_ALLOCATION_WEIGHT squared, so floor-encoded event
// keys preserve the exact order of distinct k/weight ratios.
const DISCRETE_FAIRNESS_SCALE: u128 = 1_u128 << 40;
const _: () = assert!(
    DISCRETE_FAIRNESS_SCALE
        > (MAX_LOCAL_ALLOCATION_WEIGHT as u128) * (MAX_LOCAL_ALLOCATION_WEIGHT as u128)
);

/// Calculates weighted max-min shares over bounded, caller-supplied inputs.
///
/// Minimums are reserved first per host and axis. Remaining capacity is shared
/// using caller-supplied weights and stable request-ID tie breaks. Failure is
/// atomic because this function has no state or effects and publishes no
/// partial result.
pub fn calculate_local_allocation_v1(
    host_candidates: &[LocalHostCapacityCandidateV1],
    allocation_candidates: &[LocalAllocationCandidateV1],
) -> Result<LocalAllocationCalculationV1, LocalAllocationError> {
    validate_counts(host_candidates.len(), allocation_candidates.len())?;
    validate_identifier_shapes(host_candidates, allocation_candidates)?;

    let mut hosts: Vec<_> = host_candidates.iter().collect();
    hosts.sort();
    validate_hosts(&hosts)?;

    let host_by_id: BTreeMap<_, _> = hosts
        .iter()
        .map(|host| (host.host_id.as_str(), *host))
        .collect();
    let mut candidates: Vec<_> = allocation_candidates.iter().collect();
    candidates.sort();
    validate_candidates(&candidates, &host_by_id)?;
    candidates.sort_by(|left, right| {
        left.host_id
            .cmp(&right.host_id)
            .then_with(|| left.request_id.cmp(&right.request_id))
            .then_with(|| left.agent_id.cmp(&right.agent_id))
    });

    let mut resources: Vec<_> = candidates
        .iter()
        .map(|candidate| candidate.caller_supplied_minimum)
        .collect();
    let mut cursor = 0;
    for host in &hosts {
        let start = cursor;
        while cursor < candidates.len() && candidates[cursor].host_id == host.host_id {
            cursor += 1;
        }
        for axis in LocalResourceAxisV1::ALL {
            allocate_axis(
                &candidates[start..cursor],
                &mut resources[start..cursor],
                axis,
                axis.read(host.caller_supplied_allocatable),
                host.host_id.as_str(),
            )?;
        }
    }

    let shares: Vec<_> = candidates
        .iter()
        .zip(resources)
        .map(|(candidate, resources)| {
            let host = host_by_id
                .get(candidate.host_id.as_str())
                .copied()
                .ok_or(LocalAllocationError::ArithmeticInvariant("host binding"))?;
            Ok(LocalAllocationShareV1 {
                request_id: candidate.request_id.clone(),
                agent_id: candidate.agent_id.clone(),
                host_id: candidate.host_id.clone(),
                failure_domain_id: host.failure_domain_id.clone(),
                resources,
            })
        })
        .collect::<Result<_, LocalAllocationError>>()?;
    let calculation_content_sha256 = digest_calculation(&hosts, &candidates, &shares)?;
    Ok(LocalAllocationCalculationV1::new(
        calculation_content_sha256,
        shares,
    ))
}

fn allocate_axis(
    candidates: &[&LocalAllocationCandidateV1],
    resources: &mut [LocalResourceVectorV1],
    axis: LocalResourceAxisV1,
    capacity: u64,
    host_id: &str,
) -> Result<(), LocalAllocationError> {
    let minimum_sum = candidates.iter().try_fold(0_u128, |sum, candidate| {
        sum.checked_add(u128::from(axis.read(candidate.caller_supplied_minimum)))
            .ok_or(LocalAllocationError::ArithmeticInvariant("minimum sum"))
    })?;
    if minimum_sum > u128::from(capacity) {
        return Err(LocalAllocationError::InsufficientCapacity {
            host_id: host_id.to_string(),
            axis,
        });
    }

    let available = u128::from(capacity) - minimum_sum;
    let total_need = candidates.iter().try_fold(0_u128, |sum, candidate| {
        sum.checked_add(u128::from(discretionary_need(candidate, axis)))
            .ok_or(LocalAllocationError::ArithmeticInvariant("desired sum"))
    })?;
    let target = available.min(total_need);
    if target == 0 {
        return Ok(());
    }

    // Each discretionary unit is one event keyed by current_units / weight.
    // Selecting a prefix gives discrete weighted max-min fairness and makes
    // every result a prefix of the result for one more unit of capacity.
    let mut low = 0_u128;
    let mut high = 0_u128;
    for candidate in candidates {
        let need = discretionary_need(candidate, axis);
        if need > 0 {
            high = high.max(event_key(need - 1, candidate.caller_supplied_weight)?);
        }
    }
    // The u128 interval halves each time, so this is at most 128 iterations.
    while low < high {
        let middle = low + (high - low) / 2;
        if count_events(candidates, axis, middle)? >= target {
            high = middle;
        } else {
            low = middle + 1;
        }
    }

    let threshold = low;
    let mut distributed = 0_u128;
    let mut tied = Vec::new();
    for (index, candidate) in candidates.iter().enumerate() {
        let need = discretionary_need(candidate, axis);
        if need == 0 {
            continue;
        }
        let below = if threshold == 0 {
            0
        } else {
            events_at_or_below(need, candidate.caller_supplied_weight, threshold - 1)?
        };
        let addition = u64::try_from(below)
            .map_err(|_| LocalAllocationError::ArithmeticInvariant("weighted share"))?;
        let value = axis
            .read(resources[index])
            .checked_add(addition)
            .ok_or(LocalAllocationError::ArithmeticInvariant("resource share"))?;
        axis.write(&mut resources[index], value);
        distributed = distributed
            .checked_add(below)
            .ok_or(LocalAllocationError::ArithmeticInvariant("distributed sum"))?;
        if below < u128::from(need)
            && event_key(addition, candidate.caller_supplied_weight)? == threshold
        {
            tied.push(index);
        }
    }
    let remainder =
        target
            .checked_sub(distributed)
            .ok_or(LocalAllocationError::ArithmeticInvariant(
                "threshold distribution",
            ))?;
    let leftover = usize::try_from(remainder)
        .map_err(|_| LocalAllocationError::ArithmeticInvariant("weighted remainder"))?;
    if leftover > tied.len() {
        return Err(LocalAllocationError::ArithmeticInvariant(
            "threshold tie count",
        ));
    }
    // The host slice is already in request-ID order, so ties are stable here.
    for index in tied.into_iter().take(leftover) {
        let value = axis.read(resources[index]).checked_add(1).ok_or(
            LocalAllocationError::ArithmeticInvariant("resource remainder"),
        )?;
        axis.write(&mut resources[index], value);
    }
    Ok(())
}

fn discretionary_need(candidate: &LocalAllocationCandidateV1, axis: LocalResourceAxisV1) -> u64 {
    axis.read(candidate.caller_supplied_desired) - axis.read(candidate.caller_supplied_minimum)
}

fn event_key(unit_index: u64, weight: u32) -> Result<u128, LocalAllocationError> {
    if weight == 0 {
        return Err(LocalAllocationError::ArithmeticInvariant(
            "zero fairness weight",
        ));
    }
    u128::from(unit_index)
        .checked_mul(DISCRETE_FAIRNESS_SCALE)
        .map(|scaled| scaled / u128::from(weight))
        .ok_or(LocalAllocationError::ArithmeticInvariant(
            "fairness event key",
        ))
}

fn events_at_or_below(
    need: u64,
    weight: u32,
    threshold: u128,
) -> Result<u128, LocalAllocationError> {
    if need == 0 {
        return Ok(0);
    }
    let strict_upper = threshold
        .checked_add(1)
        .and_then(|value| value.checked_mul(u128::from(weight)))
        .ok_or(LocalAllocationError::ArithmeticInvariant(
            "fairness threshold",
        ))?;
    let positive_events =
        strict_upper
            .checked_sub(1)
            .ok_or(LocalAllocationError::ArithmeticInvariant(
                "fairness threshold",
            ))?
            / DISCRETE_FAIRNESS_SCALE;
    Ok(1 + positive_events.min(u128::from(need - 1)))
}

fn count_events(
    candidates: &[&LocalAllocationCandidateV1],
    axis: LocalResourceAxisV1,
    threshold: u128,
) -> Result<u128, LocalAllocationError> {
    candidates.iter().try_fold(0_u128, |sum, candidate| {
        let count = events_at_or_below(
            discretionary_need(candidate, axis),
            candidate.caller_supplied_weight,
            threshold,
        )?;
        sum.checked_add(count)
            .ok_or(LocalAllocationError::ArithmeticInvariant(
                "fairness event count",
            ))
    })
}
