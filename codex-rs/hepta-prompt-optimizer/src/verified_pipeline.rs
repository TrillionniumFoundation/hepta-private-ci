/// Enumerate from the live registry and immediately seal the recomputed result.
pub fn enumerate_verified_factors_v2(
    registry: &PromptRegistry,
    request: PromptEnumerationRequestV1,
) -> Result<VerifiedEnumeratedPromptCandidatesV2, VerifiedPromptErrorV2> {
    let value = enumerate_factors_v1(registry, request)?;
    verify_enumerated_prompt_candidates_v2(value)
}

/// Reopen an enumerated transport value by recomputing every semantic digest,
/// count, order and exact realization binding.
pub fn verify_enumerated_prompt_candidates_v2(
    value: EnumeratedPromptCandidatesV1,
) -> Result<VerifiedEnumeratedPromptCandidatesV2, VerifiedPromptErrorV2> {
    validate_enumerated(&value)?;
    let scope_digest = evidence_scope_digest(&value);
    Ok(VerifiedEnumeratedPromptCandidatesV2 {
        value,
        scope_digest,
    })
}

/// Verify generator/evaluator evidence, enforce controller separation, bind each
/// evaluator row to one exact realization, and seal the canonical pricing set.
#[allow(clippy::too_many_arguments)]
pub fn price_verified_factors_v2(
    candidates: VerifiedEnumeratedPromptCandidatesV2,
    completeness: &CandidateSetCompletenessReceiptV1,
    completeness_evidence: &SignedLearningEvidenceV1,
    pricing_evidence: Vec<BoundPromptPricingEvidenceV2>,
    verifier: &LearningEvidenceVerifierV1,
    policy: &PromptPricingPolicyV1,
    now_unix_ms: u64,
) -> Result<VerifiedPricedPromptCandidatesV2, VerifiedPromptErrorV2> {
    validate_enumerated(&candidates.value)?;
    if now_unix_ms == 0 {
        return Err(VerifiedPromptErrorV2::EvidenceExpired);
    }
    if verifier.objective_digest() != candidates.value.receipt.objective_digest {
        return Err(VerifiedPromptErrorV2::ObjectiveMismatch);
    }
    if verifier.scope_digest() != candidates.scope_digest {
        return Err(VerifiedPromptErrorV2::ScopeMismatch);
    }
    if pricing_evidence.len() != candidates.value.candidates.len()
        || pricing_evidence.len() > MAX_EVIDENCE_ROWS
    {
        return Err(VerifiedPromptErrorV2::Incomplete(
            "pricing evidence does not cover the exact candidate set".to_owned(),
        ));
    }

    let completeness_payload = candidate_completeness_signing_payload_v1(completeness)
        .map_err(VerifiedPromptErrorV2::Canonical)?;
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            completeness_evidence,
            &completeness_payload,
            now_unix_ms,
        )
        .map_err(|error| VerifiedPromptErrorV2::LearningEvidence(error.to_string()))?;
    if &completeness.generator_id != &generator.principal().principal_id {
        return Err(VerifiedPromptErrorV2::IdentityMismatch(
            "candidate generator principal",
        ));
    }

    let pricing_policy_digest = policy.digest()?;
    let by_factor = candidates
        .value
        .candidates
        .iter()
        .map(|candidate| (candidate.factor_id.clone(), candidate))
        .collect::<BTreeMap<_, _>>();
    let mut raw_rows = Vec::with_capacity(pricing_evidence.len());
    let mut seen = BTreeSet::new();
    let mut evaluator_controller_ids = BTreeSet::new();
    let mut lineage_parts = vec![generator.payload_digest()];
    let mut valid_until = completeness_evidence.expires_at;

    for bound in pricing_evidence {
        let factor_id = bound.evidence.factor_id.clone();
        if !seen.insert(factor_id.clone()) {
            return Err(VerifiedPromptErrorV2::DuplicateIdentity(
                factor_id.to_string(),
            ));
        }
        let candidate = by_factor.get(&factor_id).ok_or_else(|| {
            VerifiedPromptErrorV2::IdentityMismatch("pricing factor is outside candidate set")
        })?;
        if bound.candidate_set_digest != candidates.value.candidates_digest
            || bound.registry_snapshot_digest
                != candidates.value.registry_snapshot.snapshot_digest
            || bound.generation_vector_digest != candidates.value.generation_vector_digest
            || bound.realization_id != candidate.realization.realization_id
            || bound.realization_binding_digest != candidate.binding_digest
            || bound.realization_binding_digest != candidate.realization.digest()
            || bound.pricing_policy_digest != pricing_policy_digest
            || bound.evidence.state_digest != candidates.value.receipt.state_digest
            || bound.evidence.model_tuple_digest != candidates.value.model_tuple.digest()
        {
            return Err(VerifiedPromptErrorV2::IdentityMismatch(
                "pricing evidence context",
            ));
        }
        let payload = pricing_evidence_signing_payload_v1(&bound.evidence);
        let evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &bound.evidence.evidence,
                &payload,
                now_unix_ms,
            )
            .map_err(|error| VerifiedPromptErrorV2::LearningEvidence(error.to_string()))?;
        verify_signed_actor_separation(&generator, &evaluator, now_unix_ms).map_err(|error| {
            if generator.controller_id() == evaluator.controller_id() {
                VerifiedPromptErrorV2::ControllerCollision
            } else {
                VerifiedPromptErrorV2::LearningEvidence(error.to_string())
            }
        })?;
        evaluator_controller_ids.insert(evaluator.controller_id().clone());
        lineage_parts.push(evaluator.payload_digest());
        valid_until = valid_until.min(bound.evidence.evidence.expires_at);
        if let Some(expires) = candidate.realization.expires_unix_ms {
            valid_until = valid_until.min(expires);
        }
        raw_rows.push(bound.evidence);
    }
    if valid_until <= now_unix_ms {
        return Err(VerifiedPromptErrorV2::EvidenceExpired);
    }

    let value = price_factors_v1(
        candidates.value,
        completeness,
        completeness_evidence,
        raw_rows,
        verifier,
        policy,
        now_unix_ms,
    )?;
    validate_priced(&value)?;
    lineage_parts.sort();
    let evidence_lineage_digest = digest_lineage(
        verifier.trust_digest(),
        verifier.authority_epoch(),
        &lineage_parts,
    );
    Ok(VerifiedPricedPromptCandidatesV2 {
        scope_digest: evidence_scope_digest(&value.candidates),
        trust_digest: verifier.trust_digest(),
        authority_epoch: verifier.authority_epoch(),
        valid_until_unix_ms: valid_until,
        evidence_lineage_digest,
        generator_controller_id: generator.controller_id().clone(),
        evaluator_controller_ids,
        value,
    })
}

/// Reverify graph/pair evidence and seal the canonical selector output. Pair
/// evidence is bound to both exact realization bindings and the exact pricing set.
#[allow(clippy::too_many_arguments)]
pub fn select_verified_portfolio_v2(
    priced: &VerifiedPricedPromptCandidatesV2,
    graph: &KnowledgeGenerationV2,
    pair_evidence: Vec<BoundPromptPairUtilityEvidenceV2>,
    verifier: &LearningEvidenceVerifierV1,
    request: PromptPortfolioRequestV1,
    now_unix_ms: u64,
) -> Result<VerifiedSelectedPromptPortfolioV2, VerifiedPromptErrorV2> {
    validate_priced(&priced.value)?;
    validate_verifier_context(priced, verifier)?;
    if request.maximum_selected_factors == 0
        || request.maximum_selected_factors > MAX_CANONICAL_SELECTED_FACTORS
    {
        return Err(VerifiedPromptErrorV2::BoundExceeded(
            "selected factor limit",
        ));
    }
    if request.token_budget > MAX_CANONICAL_TOKEN_BUDGET {
        return Err(VerifiedPromptErrorV2::BoundExceeded("token budget"));
    }
    graph
        .validate()
        .map_err(|error| VerifiedPromptErrorV2::KnowledgeGraph(error.to_string()))?;
    if graph.generation_vector_digest != priced.value.candidates.generation_vector_digest {
        return Err(VerifiedPromptErrorV2::GraphDrift);
    }

    let by_factor = priced
        .value
        .rows
        .iter()
        .map(|row| (row.binding.factor_id.clone(), &row.binding))
        .collect::<BTreeMap<_, _>>();
    let mut raw_pair_rows = Vec::with_capacity(pair_evidence.len());
    let mut seen_pairs = BTreeSet::new();
    let mut lineage_parts = vec![priced.evidence_lineage_digest];
    let mut valid_until = priced.valid_until_unix_ms.min(graph_valid_until(graph)?);

    for bound in pair_evidence {
        let left = by_factor.get(&bound.evidence.left_factor_id).ok_or(
            VerifiedPromptErrorV2::IdentityMismatch("left pair factor"),
        )?;
        let right = by_factor.get(&bound.evidence.right_factor_id).ok_or(
            VerifiedPromptErrorV2::IdentityMismatch("right pair factor"),
        )?;
        let pair = canonical_pair(
            &bound.evidence.left_factor_id,
            &bound.evidence.right_factor_id,
        );
        if !seen_pairs.insert(pair) {
            return Err(VerifiedPromptErrorV2::DuplicateIdentity(
                "pair evidence".to_owned(),
            ));
        }
        if bound.candidate_set_digest != priced.value.candidates.candidates_digest
            || bound.pricing_set_digest != priced.value.pricing_set_digest
            || bound.left_realization_binding_digest != left.binding_digest
            || bound.right_realization_binding_digest != right.binding_digest
            || bound.evidence.graph_generation_digest != graph.generation_digest
            || bound.evidence.state_digest != priced.value.candidates.receipt.state_digest
        {
            return Err(VerifiedPromptErrorV2::IdentityMismatch(
                "pair evidence context",
            ));
        }
        let payload = pair_utility_evidence_signing_payload_v1(&bound.evidence);
        let evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &bound.evidence.evidence,
                &payload,
                now_unix_ms,
            )
            .map_err(|error| VerifiedPromptErrorV2::LearningEvidence(error.to_string()))?;
        if evaluator.controller_id() == &priced.generator_controller_id {
            return Err(VerifiedPromptErrorV2::ControllerCollision);
        }
        lineage_parts.push(evaluator.payload_digest());
        valid_until = valid_until.min(bound.evidence.evidence.expires_at);
        raw_pair_rows.push(bound.evidence);
    }
    if valid_until <= now_unix_ms {
        return Err(VerifiedPromptErrorV2::EvidenceExpired);
    }

    let value = select_portfolio_v1(
        &priced.value,
        graph,
        raw_pair_rows,
        verifier,
        request,
        now_unix_ms,
    )?;
    lineage_parts.sort();
    let evidence_lineage_digest = digest_lineage(
        priced.trust_digest,
        priced.authority_epoch,
        &lineage_parts,
    );
    let context = PromptPortfolioVerificationContextV2 {
        candidate_set_digest: priced.value.candidates.candidates_digest,
        pricing_set_digest: priced.value.pricing_set_digest,
        registry_snapshot_digest: priced.value.candidates.registry_snapshot.snapshot_digest,
        generation_vector_digest: priced.value.candidates.generation_vector_digest,
        model_tuple_digest: priced.value.candidates.model_tuple.digest(),
        graph_generation_digest: graph.generation_digest,
        objective_digest: priced.value.candidates.receipt.objective_digest,
        state_digest: priced.value.candidates.receipt.state_digest,
        scope_digest: priced.scope_digest,
        trust_digest: priced.trust_digest,
        authority_epoch: priced.authority_epoch,
        valid_until_unix_ms: valid_until.min(value.receipt.valid_until_unix_ms),
        evidence_lineage_digest,
    };
    verify_selected_prompt_portfolio_v2(value, context)
}

/// Reopen a selected portfolio after persistence or transport. The caller must
/// supply the immutable verification context emitted by selection.
pub fn verify_selected_prompt_portfolio_v2(
    value: SelectedPromptPortfolioV1,
    context: PromptPortfolioVerificationContextV2,
) -> Result<VerifiedSelectedPromptPortfolioV2, VerifiedPromptErrorV2> {
    validate_selected(&value, &context)?;
    Ok(VerifiedSelectedPromptPortfolioV2 { value, context })
}

/// Revalidate current trust, graph generation/validity, portfolio evidence
/// validity and the live prompt registry immediately before the effect boundary.
pub fn exercise_verified_portfolio_v2(
    registry: &PromptRegistry,
    portfolio: &VerifiedSelectedPromptPortfolioV2,
    graph: &KnowledgeGenerationV2,
    verifier: &LearningEvidenceVerifierV1,
    request: PromptExerciseRequestV1,
) -> Result<PromptExerciseDecisionV1, VerifiedPromptErrorV2> {
    validate_selected(&portfolio.value, &portfolio.context)?;
    if verifier.trust_digest() != portfolio.context.trust_digest
        || verifier.authority_epoch() != portfolio.context.authority_epoch
    {
        return Err(VerifiedPromptErrorV2::TrustRotated);
    }
    if verifier.objective_digest() != portfolio.context.objective_digest {
        return Err(VerifiedPromptErrorV2::ObjectiveMismatch);
    }
    if verifier.scope_digest() != portfolio.context.scope_digest {
        return Err(VerifiedPromptErrorV2::ScopeMismatch);
    }
    graph
        .validate()
        .map_err(|error| VerifiedPromptErrorV2::KnowledgeGraph(error.to_string()))?;
    if graph.generation_digest != portfolio.context.graph_generation_digest
        || graph.generation_vector_digest != portfolio.context.generation_vector_digest
    {
        return Err(VerifiedPromptErrorV2::GraphDrift);
    }
    let graph_valid_until = graph_valid_until(graph)?;
    if request.now_unix_ms == 0
        || request.now_unix_ms >= portfolio.context.valid_until_unix_ms
        || request.now_unix_ms >= graph_valid_until
    {
        return Err(VerifiedPromptErrorV2::EvidenceExpired);
    }
    let decision = exercise_v1(registry, &portfolio.value, request)?;
    match decision.decision {
        PromptExerciseActionV1::RejectStale => Err(VerifiedPromptErrorV2::Stale),
        PromptExerciseActionV1::Exercise
        | PromptExerciseActionV1::Wait
        | PromptExerciseActionV1::NoIntervention => Ok(decision),
    }
}

