//! Fail-closed validation for opaque-digest internal V1 history.

use crate::types::*;

pub(crate) fn validate_legacy_v1_read(proposal: &PlasticityProposal) -> Result<(), Error> {
    if proposal.proposer_id == proposal.evaluator_id {
        return Err(Error::SelfEvaluation);
    }
    if proposal.candidate_generation <= proposal.baseline_generation {
        return Err(Error::GenerationNotAdvanced);
    }
    if proposal.evaluation_digest.is_zero() {
        return Err(Error::EmptyDigest("evaluation"));
    }
    if proposal.proposal_digest.is_zero() {
        return Err(Error::EmptyDigest("proposal"));
    }
    if proposal.authority.grants_any() {
        return Err(Error::AuthorityGranted);
    }
    if proposal.parameter_deltas.len() > MAX_PARAMETER_DELTAS {
        return Err(Error::ParameterLimitExceeded);
    }
    if proposal.topology_deltas.len() > MAX_TOPOLOGY_DELTAS {
        return Err(Error::TopologyLimitExceeded);
    }
    if proposal
        .parameter_deltas
        .windows(2)
        .any(|pair| pair[0].parameter_id >= pair[1].parameter_id)
    {
        return Err(Error::NonCanonicalOrder("legacy parameter deltas"));
    }
    for delta in &proposal.parameter_deltas {
        if delta.evidence_digest.is_zero() {
            return Err(Error::EmptyDigest("parameter evidence"));
        }
        if delta.lower_bound > delta.upper_bound {
            return Err(Error::InvertedBounds(delta.parameter_id.to_string()));
        }
        if delta.delta < delta.lower_bound || delta.delta > delta.upper_bound {
            return Err(Error::DeltaOutsideBounds(delta.parameter_id.to_string()));
        }
    }
    if proposal.topology_deltas.windows(2).any(|pair| {
        (&pair[0].module_id, pair[0].operation) >= (&pair[1].module_id, pair[1].operation)
    }) {
        return Err(Error::NonCanonicalOrder("legacy topology deltas"));
    }
    for delta in &proposal.topology_deltas {
        if delta.predecessor_digest.is_zero()
            || delta.candidate_digest.is_zero()
            || delta.evidence_digest.is_zero()
        {
            return Err(Error::EmptyDigest("topology lineage"));
        }
        if delta.predecessor_digest == delta.candidate_digest {
            return Err(Error::TopologyDigestUnchanged(delta.module_id.to_string()));
        }
    }
    Ok(())
}
