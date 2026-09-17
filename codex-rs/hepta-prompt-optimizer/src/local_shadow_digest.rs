use codex_hepta_types::{Digest32, FixedQ32, StableId};

use super::{
    LocalCandidateDisposition, LocalHardConstraint, LocalPairInteraction,
    LocalShadowCandidateDecision, LocalShadowInput, LocalShadowSelection,
};
use crate::PromptCandidate;

pub(super) struct ProposalDigestInput<'a> {
    pub(super) input: &'a LocalShadowInput,
    pub(super) total_candidate_count: u32,
    pub(super) candidate_input_digest: Digest32,
    pub(super) interaction_graph_digest: Digest32,
    pub(super) hard_constraint_digest: Digest32,
    pub(super) selections: &'a [LocalShadowSelection],
    pub(super) decisions: &'a [LocalShadowCandidateDecision],
    pub(super) total_token_cost: u64,
    pub(super) unspent_token_budget: u64,
    pub(super) total_caller_supplied_gain: FixedQ32,
}

pub(super) fn digest_candidate_input(
    input: &LocalShadowInput,
    total_candidate_count: u32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-optimizer.local-shadow-candidates.v3");
    bytes.extend_from_slice(&total_candidate_count.to_be_bytes());
    push_id(&mut bytes, &input.no_intervention.arm_id);
    bytes.extend_from_slice(input.no_intervention.registry_digest.as_array());
    bytes.extend_from_slice(input.no_intervention.support_reference_digest.as_array());
    push_len(&mut bytes, input.factor_candidates.len());
    for candidate in &input.factor_candidates {
        push_candidate(&mut bytes, candidate);
    }
    Digest32::of_bytes(&bytes)
}

pub(super) fn digest_interactions(interactions: &[LocalPairInteraction]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-optimizer.local-shadow-interactions.v3.sparse-zero");
    push_len(&mut bytes, interactions.len());
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
    bytes.extend_from_slice(b"hepta.prompt-optimizer.local-shadow-hard-constraints.v3");
    push_len(&mut bytes, constraints.len());
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
    bytes.extend_from_slice(b"hepta.prompt-optimizer.local-shadow-proposal.v3");
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
    bytes.extend_from_slice(&parts.total_candidate_count.to_be_bytes());
    bytes.extend_from_slice(parts.candidate_input_digest.as_array());
    bytes.extend_from_slice(parts.interaction_graph_digest.as_array());
    bytes.extend_from_slice(parts.hard_constraint_digest.as_array());
    push_len(&mut bytes, parts.selections.len());
    for selection in parts.selections {
        push_id(&mut bytes, &selection.candidate_id);
        push_id(&mut bytes, &selection.factor_id);
    }
    push_len(&mut bytes, parts.decisions.len());
    for decision in parts.decisions {
        push_id(&mut bytes, &decision.candidate_id);
        bytes.push(disposition_code(decision.disposition));
        push_len(&mut bytes, decision.prerequisite_closure.len());
        for id in &decision.prerequisite_closure {
            push_id(&mut bytes, id);
        }
    }
    bytes.extend_from_slice(&parts.total_token_cost.to_be_bytes());
    bytes.extend_from_slice(&parts.unspent_token_budget.to_be_bytes());
    bytes.extend_from_slice(&parts.total_caller_supplied_gain.raw().to_be_bytes());

    // Bind the fixed local-shadow audit semantics explicitly. These are not
    // registered wire enums; the strings are domain markers for this source
    // version and prevent an audit-semantic change from preserving the digest.
    for marker in [
        b"candidate-scope:supplied-only".as_slice(),
        b"candidate-completeness:unknown-caller-supplied".as_slice(),
        b"pricing-provenance:caller-supplied-opaque".as_slice(),
        b"model-compatibility:unverified".as_slice(),
        b"exercise-boundary:unbound".as_slice(),
        b"interaction-policy:missing-as-zero".as_slice(),
        b"selection-method:prerequisite-closure-greedy-density-v2".as_slice(),
        b"optimality:heuristic-no-certificate".as_slice(),
    ] {
        push_bytes(&mut bytes, marker);
    }
    bytes.extend_from_slice(&0u32.to_be_bytes()); // omitted_candidate_count
    Digest32::of_bytes(&bytes)
}

fn push_candidate(bytes: &mut Vec<u8>, candidate: &PromptCandidate) {
    push_id(bytes, &candidate.candidate_id);
    push_id(bytes, &candidate.factor_id);
    push_id(bytes, &candidate.realization_id);
    bytes.extend_from_slice(&candidate.expected_gain.raw().to_be_bytes());
    bytes.extend_from_slice(&candidate.cost.to_be_bytes());
    bytes.extend_from_slice(candidate.registry_digest.as_array());
    bytes.extend_from_slice(candidate.support_digest.as_array());
}

fn disposition_code(value: LocalCandidateDisposition) -> u8 {
    match value {
        LocalCandidateDisposition::Selected => 0,
        LocalCandidateDisposition::NonPositiveMarginal => 1,
        LocalCandidateDisposition::OverBudget => 2,
        LocalCandidateDisposition::SelectionLimit => 3,
        LocalCandidateDisposition::Conflict => 4,
        LocalCandidateDisposition::HeuristicNotSelected => 5,
    }
}

fn push_len(bytes: &mut Vec<u8>, len: usize) {
    bytes.extend_from_slice(&u64::try_from(len).unwrap_or(u64::MAX).to_be_bytes());
}

fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) {
    push_len(bytes, value.len());
    bytes.extend_from_slice(value);
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_bytes(bytes, value.as_str().as_bytes());
}
