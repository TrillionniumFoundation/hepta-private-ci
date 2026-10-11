use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::LocalHardConstraint;
use super::LocalPairInteraction;
use super::LocalShadowInput;
use super::LocalShadowSelection;
use crate::PromptCandidate;

pub(super) struct ProposalDigestInput<'a> {
    pub(super) input: &'a LocalShadowInput,
    pub(super) total_candidate_count: u32,
    pub(super) candidate_input_digest: Digest32,
    pub(super) interaction_graph_digest: Digest32,
    pub(super) hard_constraint_digest: Digest32,
    pub(super) selections: &'a [LocalShadowSelection],
    pub(super) total_token_cost: u64,
    pub(super) unspent_token_budget: u64,
    pub(super) total_caller_supplied_gain: FixedQ32,
}

pub(super) fn digest_candidate_input(
    input: &LocalShadowInput,
    total_candidate_count: u32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-optimizer.local-shadow-candidates.v2");
    bytes.extend_from_slice(&total_candidate_count.to_be_bytes());
    bytes.push(0);
    push_id(&mut bytes, &input.no_intervention.arm_id);
    bytes.extend_from_slice(input.no_intervention.registry_digest.as_array());
    bytes.extend_from_slice(input.no_intervention.support_reference_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(input.factor_candidates.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for candidate in &input.factor_candidates {
        bytes.push(1);
        push_candidate(&mut bytes, candidate);
    }
    Digest32::of_bytes(&bytes)
}

pub(super) fn digest_interactions(interactions: &[LocalPairInteraction]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-optimizer.local-shadow-interactions.v2");
    bytes.extend_from_slice(
        &u32::try_from(interactions.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for edge in interactions {
        push_id(&mut bytes, &edge.left_candidate_id);
        push_id(&mut bytes, &edge.right_candidate_id);
        bytes.extend_from_slice(&edge.caller_supplied_marginal_gain.raw().to_be_bytes());
        bytes.extend_from_slice(edge.support_reference_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

pub(super) fn digest_hard_constraints(constraints: &[LocalHardConstraint]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-optimizer.local-shadow-hard-constraints.v2");
    bytes.extend_from_slice(
        &u32::try_from(constraints.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for constraint in constraints {
        match constraint {
            LocalHardConstraint::Conflict {
                left_candidate_id,
                right_candidate_id,
                support_reference_digest,
            } => {
                bytes.push(0);
                push_id(&mut bytes, left_candidate_id);
                push_id(&mut bytes, right_candidate_id);
                bytes.extend_from_slice(support_reference_digest.as_array());
            }
            LocalHardConstraint::Requires {
                candidate_id,
                prerequisite_candidate_id,
                support_reference_digest,
            } => {
                bytes.push(1);
                push_id(&mut bytes, candidate_id);
                push_id(&mut bytes, prerequisite_candidate_id);
                bytes.extend_from_slice(support_reference_digest.as_array());
            }
        }
    }
    Digest32::of_bytes(&bytes)
}

pub(super) fn digest_proposal(parts: ProposalDigestInput<'_>) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-optimizer.local-shadow-proposal.v2");
    push_id(&mut bytes, &parts.input.decision_id);
    bytes.extend_from_slice(parts.input.objective_digest.as_array());
    bytes.extend_from_slice(parts.input.state_digest.as_array());
    bytes.extend_from_slice(parts.input.registry_snapshot_digest.as_array());
    bytes.extend_from_slice(&parts.input.token_budget.to_be_bytes());
    bytes.extend_from_slice(
        &u64::try_from(parts.input.maximum_selected_factors)
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    push_id(&mut bytes, &parts.input.no_intervention.arm_id);
    bytes.extend_from_slice(&parts.total_candidate_count.to_be_bytes());
    bytes.push(0); // LocalCandidateScope::SuppliedCandidatesOnly.
    bytes.extend_from_slice(parts.candidate_input_digest.as_array());
    bytes.extend_from_slice(parts.interaction_graph_digest.as_array());
    bytes.extend_from_slice(parts.hard_constraint_digest.as_array());
    bytes.push(0); // LocalSelectionMethod::GreedyMarginalV1.
    bytes.push(0); // LocalOptimalityDisclosure::HeuristicNoCertificate.
    bytes.extend_from_slice(
        &u32::try_from(parts.selections.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for selection in parts.selections {
        push_id(&mut bytes, &selection.candidate_id);
        push_id(&mut bytes, &selection.factor_id);
    }
    bytes.extend_from_slice(&parts.total_token_cost.to_be_bytes());
    bytes.extend_from_slice(&parts.unspent_token_budget.to_be_bytes());
    bytes.extend_from_slice(&parts.total_caller_supplied_gain.raw().to_be_bytes());
    bytes.push(0); // AuthorityPosture::DENY_ALL is part of local semantics.
    Digest32::of_bytes(&bytes)
}

fn push_candidate(bytes: &mut Vec<u8>, candidate: &PromptCandidate) {
    push_id(bytes, &candidate.candidate_id);
    push_id(bytes, &candidate.factor_id);
    push_id(bytes, &candidate.realization_id);
    bytes.push(u8::from(candidate.admitted));
    bytes.push(u8::from(candidate.legal));
    bytes.extend_from_slice(&candidate.expected_gain.raw().to_be_bytes());
    bytes.extend_from_slice(&candidate.cost.to_be_bytes());
    bytes.extend_from_slice(candidate.registry_digest.as_array());
    bytes.extend_from_slice(candidate.support_digest.as_array());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
