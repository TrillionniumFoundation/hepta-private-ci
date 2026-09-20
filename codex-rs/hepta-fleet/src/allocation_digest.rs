use codex_hepta_contracts::Sha256Digest;
use sha2::Digest;
use sha2::Sha256;

use crate::LOCAL_ALLOCATION_CALCULATOR_VERSION;
use crate::LocalAllocationCandidateV1;
use crate::LocalAllocationError;
use crate::LocalAllocationShareV1;
use crate::LocalHostCapacityCandidateV1;
use crate::LocalResourceVectorV1;

pub(super) fn digest_calculation(
    hosts: &[&LocalHostCapacityCandidateV1],
    candidates: &[&LocalAllocationCandidateV1],
    shares: &[LocalAllocationShareV1],
) -> Result<Sha256Digest, LocalAllocationError> {
    let mut hasher = Sha256::new();
    hasher.update(b"hepta.runtime-fleet.local-allocation-calculation.v1");
    hasher.update(LOCAL_ALLOCATION_CALCULATOR_VERSION.to_be_bytes());
    hasher.update([0]); // CallerSuppliedCandidatesAndCapacityOnly.
    push_len(&mut hasher, hosts.len())?;
    for host in hosts {
        push_text(&mut hasher, host.host_id.as_str())?;
        push_text(&mut hasher, host.failure_domain_id.as_str())?;
        push_vector(&mut hasher, host.caller_supplied_allocatable);
    }
    push_len(&mut hasher, candidates.len())?;
    for candidate in candidates {
        push_text(&mut hasher, candidate.request_id.as_str())?;
        push_text(&mut hasher, candidate.agent_id.as_str())?;
        push_text(&mut hasher, candidate.host_id.as_str())?;
        hasher.update(candidate.caller_supplied_weight.to_be_bytes());
        push_vector(&mut hasher, candidate.caller_supplied_minimum);
        push_vector(&mut hasher, candidate.caller_supplied_desired);
    }
    push_len(&mut hasher, shares.len())?;
    for share in shares {
        push_text(&mut hasher, share.request_id.as_str())?;
        push_text(&mut hasher, share.agent_id.as_str())?;
        push_text(&mut hasher, share.host_id.as_str())?;
        push_text(&mut hasher, share.failure_domain_id.as_str())?;
        push_vector(&mut hasher, share.resources);
    }
    hasher.update([0; 8]); // LocalAllocationClaimBoundaryV1::DENY_ALL.
    Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
}

fn push_len(hasher: &mut Sha256, length: usize) -> Result<(), LocalAllocationError> {
    let length = u32::try_from(length)
        .map_err(|_| LocalAllocationError::ArithmeticInvariant("canonical length"))?;
    hasher.update(length.to_be_bytes());
    Ok(())
}

fn push_text(hasher: &mut Sha256, value: &str) -> Result<(), LocalAllocationError> {
    push_len(hasher, value.len())?;
    hasher.update(value.as_bytes());
    Ok(())
}

fn push_vector(hasher: &mut Sha256, vector: LocalResourceVectorV1) {
    hasher.update(vector.concurrent_turns.to_be_bytes());
    hasher.update(vector.memory_mib.to_be_bytes());
    hasher.update(vector.tool_processes.to_be_bytes());
    hasher.update(vector.turn_queue_slots.to_be_bytes());
}
