fn digest_verified_enumerated(value: &v1::EnumeratedPromptCandidatesV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.verified-enumerated.v2".to_vec();
    bytes.extend_from_slice(value.receipt.receipt_digest.as_array());
    bytes.extend_from_slice(value.candidates_digest.as_array());
    bytes.extend_from_slice(value.canonical_order_digest.as_array());
    bytes.extend_from_slice(value.registry_snapshot.snapshot_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_candidates(candidates: &[v1::PromptCandidateBindingV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidates.v1".to_vec();
    push_len(&mut bytes, candidates.len());
    for candidate in candidates {
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization.realization_id);
        bytes.extend_from_slice(candidate.binding_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_candidate_order(candidates: &[v1::PromptCandidateBindingV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-order.v1".to_vec();
    for candidate in candidates {
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization.realization_id);
    }
    Digest32::of_bytes(&bytes)
}

fn digest_candidate_receipt(value: &v1::EnumeratedPromptCandidatesV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-set-receipt.v1".to_vec();
    push_id(&mut bytes, &value.receipt.set_id);
    for digest in [
        value.receipt.objective_digest,
        value.receipt.state_digest,
        value.receipt.registry_digest,
        value.registry_snapshot.snapshot_digest,
        value.model_tuple.digest(),
        value.receipt.selection_grammar_digest,
        value.candidates_digest,
        value.canonical_order_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_ids(&mut bytes, &value.receipt.candidate_factor_ids);
    bytes.extend_from_slice(&value.omitted_count.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_pricing_receipt(
    factor_id: &StableId,
    state_digest: Digest32,
    expected_utility: FixedQ32,
    downside: FixedQ32,
    token_cost: u32,
    latency_cost_micros: u64,
    interference_ppm: u32,
    confidence: &v1::PromptConfidenceIntervalV1,
    policy_digest: Digest32,
    binding_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.pricing-receipt.v1".to_vec();
    push_id(&mut bytes, factor_id);
    bytes.extend_from_slice(state_digest.as_array());
    bytes.extend_from_slice(&expected_utility.raw().to_be_bytes());
    bytes.extend_from_slice(&downside.raw().to_be_bytes());
    bytes.extend_from_slice(&token_cost.to_be_bytes());
    bytes.extend_from_slice(&latency_cost_micros.to_be_bytes());
    bytes.extend_from_slice(&interference_ppm.to_be_bytes());
    bytes.extend_from_slice(&confidence.lower_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&confidence.upper_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&confidence.support_count.to_be_bytes());
    bytes.extend_from_slice(confidence.support_audit_digest.as_array());
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(binding_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_pricing_set(
    rows: &[v1::PricedPromptCandidateV1],
    policy_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.pricing-set.v1".to_vec();
    bytes.extend_from_slice(policy_digest.as_array());
    push_len(&mut bytes, rows.len());
    for row in rows {
        push_id(&mut bytes, &row.binding.factor_id);
        bytes.extend_from_slice(row.pricing.receipt_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_evidence_binding(
    context: &PromptEvidenceContextV2,
    generator_principal_id: &StableId,
    generator_controller_id: &StableId,
    evaluator_principal_ids: &[StableId],
    evaluator_controller_ids: &[StableId],
    generator_payload_digest: Digest32,
    payload_digests: &[Digest32],
    valid_until: u64,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.evidence-binding.v2".to_vec();
    bytes.extend_from_slice(context.digest().as_array());
    push_id(&mut bytes, generator_principal_id);
    push_id(&mut bytes, generator_controller_id);
    push_ids(&mut bytes, evaluator_principal_ids);
    push_ids(&mut bytes, evaluator_controller_ids);
    bytes.extend_from_slice(generator_payload_digest.as_array());
    for digest in payload_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&valid_until.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn digest_interactions_v2(
    result_digest: Digest32,
    evidence_digests: &[Digest32],
    problem: &DensePromptProblem<'_>,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.interactions.v2".to_vec();
    bytes.extend_from_slice(result_digest.as_array());
    for digest in evidence_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    for index in 0..problem.rows.len() {
        push_id(&mut bytes, &problem.rows[index].binding.factor_id);
        for required in problem.requires[index].indices(problem.rows.len()) {
            bytes.push(0);
            push_id(&mut bytes, &problem.rows[required].binding.factor_id);
        }
        for conflict in problem.conflicts[index].indices(problem.rows.len()) {
            if index < conflict {
                bytes.push(1);
                push_id(&mut bytes, &problem.rows[conflict].binding.factor_id);
            }
        }
        if problem.dominated.contains(index) {
            bytes.push(2);
        }
    }
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_portfolio_receipt_v2(
    portfolio_id: &StableId,
    candidate_set_digest: Digest32,
    factor_ids: &[StableId],
    interaction_digest: Digest32,
    expected_utility: FixedQ32,
    total_tokens: u32,
    valid_until: u64,
    pricing_set_digest: Digest32,
    graph_generation_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.portfolio-receipt.v2".to_vec();
    push_id(&mut bytes, portfolio_id);
    for digest in [
        candidate_set_digest,
        interaction_digest,
        pricing_set_digest,
        graph_generation_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_ids(&mut bytes, factor_ids);
    bytes.extend_from_slice(&expected_utility.raw().to_be_bytes());
    bytes.extend_from_slice(&total_tokens.to_be_bytes());
    bytes.extend_from_slice(&valid_until.to_be_bytes());
    bytes.push(1);
    bytes.push(0);
    Digest32::of_bytes(&bytes)
}

fn digest_portfolio_audit(audit: &PromptPortfolioAuditV2, receipt_digest: Digest32) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.portfolio-audit.v2".to_vec();
    bytes.extend_from_slice(receipt_digest.as_array());
    for value in [
        audit.candidate_count,
        audit.selected_count,
        audit.solver_rounds,
        audit.local_evaluations,
        audit.exact_nodes,
        audit.token_utilization_ppm,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.push(u8::from(audit.no_intervention));
    bytes.push(u8::from(audit.exact_complete));
    bytes.push(match audit.termination {
        PromptSolverTerminationV2::ExactSmallProblem => 0,
        PromptSolverTerminationV2::LocalOptimum => 1,
        PromptSolverTerminationV2::EvaluationBudget => 2,
    });
    for value in [
        audit.incumbent_utility_q32,
        audit.relaxed_upper_bound_q32,
        audit.heuristic_gap_q32,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    for value in [
        audit.token_budget,
        audit.selected_tokens,
        audit.oldest_evidence_age_ms,
        audit.evidence_valid_until_unix_ms,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(audit.graph_generation_digest.as_array());
    bytes.extend_from_slice(audit.evidence_binding_digest.as_array());
    for decision in &audit.decisions {
        push_id(&mut bytes, &decision.factor_id);
        bytes.push(match decision.disposition {
            PromptCandidateDispositionV2::Selected => 0,
            PromptCandidateDispositionV2::Dominated => 1,
            PromptCandidateDispositionV2::NonPositiveUtility => 2,
            PromptCandidateDispositionV2::TokenBudget => 3,
            PromptCandidateDispositionV2::SelectionLimit => 4,
            PromptCandidateDispositionV2::HardConflict => 5,
            PromptCandidateDispositionV2::HeuristicExcluded => 6,
        });
    }
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_exercise_receipt_v2(
    portfolio_id: &StableId,
    boundary: PromptDecisionBoundaryV1,
    exercise_now: FixedQ32,
    wait: FixedQ32,
    decision: PromptExerciseActionV1,
    policy_digest: Digest32,
    portfolio_digest: Digest32,
    audit_digest: Digest32,
    stale_reason: Option<PromptStaleReasonV2>,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.exercise-receipt.v2".to_vec();
    push_id(&mut bytes, portfolio_id);
    bytes.push(boundary_code(boundary));
    bytes.extend_from_slice(&exercise_now.raw().to_be_bytes());
    bytes.extend_from_slice(&wait.raw().to_be_bytes());
    bytes.push(exercise_action_code(decision));
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(portfolio_digest.as_array());
    bytes.extend_from_slice(audit_digest.as_array());
    bytes.push(stale_reason.map_or(255, stale_reason_code));
    Digest32::of_bytes(&bytes)
}

const fn boundary_code(value: PromptDecisionBoundaryV1) -> u8 {
    match value {
        PromptDecisionBoundaryV1::RequestAccepted => 0,
        PromptDecisionBoundaryV1::ObjectiveCompiled => 1,
        PromptDecisionBoundaryV1::BeforePlanning => 2,
        PromptDecisionBoundaryV1::BeforeCandidateGeneration => 3,
        PromptDecisionBoundaryV1::BeforeModelOrToolDispatch => 4,
        PromptDecisionBoundaryV1::AfterObservation => 5,
        PromptDecisionBoundaryV1::AfterFailureOrUncertaintySpike => 6,
        PromptDecisionBoundaryV1::BeforeIrreversibleMutation => 7,
        PromptDecisionBoundaryV1::BeforeVerification => 8,
        PromptDecisionBoundaryV1::BeforeFinalResponse => 9,
        PromptDecisionBoundaryV1::BeforeCompactOrHandoff => 10,
    }
}

const fn exercise_action_code(value: PromptExerciseActionV1) -> u8 {
    match value {
        PromptExerciseActionV1::Exercise => 0,
        PromptExerciseActionV1::Wait => 1,
        PromptExerciseActionV1::RejectStale => 2,
        PromptExerciseActionV1::NoIntervention => 3,
    }
}

const fn stale_reason_code(value: PromptStaleReasonV2) -> u8 {
    match value {
        PromptStaleReasonV2::PortfolioExpired => 0,
        PromptStaleReasonV2::EvidenceExpired => 1,
        PromptStaleReasonV2::StateDrift => 2,
        PromptStaleReasonV2::GenerationDrift => 3,
        PromptStaleReasonV2::ModelDrift => 4,
        PromptStaleReasonV2::GraphDrift => 5,
        PromptStaleReasonV2::TrustRotation => 6,
        PromptStaleReasonV2::ScopeDrift => 7,
        PromptStaleReasonV2::ObjectiveDrift => 8,
        PromptStaleReasonV2::RegistryRevisionOrRevocation => 9,
        PromptStaleReasonV2::PortfolioIntegrity => 10,
    }
}
