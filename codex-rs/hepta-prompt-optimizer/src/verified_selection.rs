#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptCandidateDispositionV2 {
    Selected,
    Dominated,
    NonPositiveUtility,
    TokenBudget,
    SelectionLimit,
    HardConflict,
    HeuristicExcluded,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateDecisionV2 {
    pub factor_id: StableId,
    pub disposition: PromptCandidateDispositionV2,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptSolverTerminationV2 {
    ExactSmallProblem,
    LocalOptimum,
    EvaluationBudget,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioAuditV2 {
    pub candidate_count: u32,
    pub selected_count: u32,
    pub no_intervention: bool,
    pub solver_rounds: u32,
    pub local_evaluations: u32,
    pub exact_nodes: u32,
    pub exact_complete: bool,
    pub termination: PromptSolverTerminationV2,
    pub incumbent_utility_q32: FixedQ32,
    pub relaxed_upper_bound_q32: FixedQ32,
    pub heuristic_gap_q32: FixedQ32,
    pub token_budget: u64,
    pub selected_tokens: u64,
    pub token_utilization_ppm: u32,
    pub oldest_evidence_age_ms: u64,
    pub evidence_valid_until_unix_ms: u64,
    pub graph_generation_digest: Digest32,
    pub evidence_binding_digest: Digest32,
    pub decisions: Vec<PromptCandidateDecisionV2>,
    pub audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedSelectedPromptPortfolioV2 {
    inner: v1::SelectedPromptPortfolioV1,
    context: PromptEvidenceContextV2,
    trust_digest: Digest32,
    authority_epoch: u64,
    scope_digest: Digest32,
    evidence_valid_until_unix_ms: u64,
    graph_valid_until_unix_ms: u64,
    audit: PromptPortfolioAuditV2,
}

impl VerifiedSelectedPromptPortfolioV2 {
    #[must_use]
    pub fn as_v1(&self) -> &v1::SelectedPromptPortfolioV1 {
        &self.inner
    }

    #[must_use]
    pub fn audit(&self) -> &PromptPortfolioAuditV2 {
        &self.audit
    }

    #[must_use]
    pub fn context(&self) -> &PromptEvidenceContextV2 {
        &self.context
    }

    #[must_use]
    pub fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    #[must_use]
    pub fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    #[must_use]
    pub fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    #[must_use]
    pub fn evidence_valid_until_unix_ms(&self) -> u64 {
        self.evidence_valid_until_unix_ms
    }

    #[must_use]
    pub fn graph_valid_until_unix_ms(&self) -> u64 {
        self.graph_valid_until_unix_ms
    }
}

impl Deref for VerifiedSelectedPromptPortfolioV2 {
    type Target = v1::SelectedPromptPortfolioV1;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

pub fn select_portfolio_verified_v2(
    priced: &VerifiedPricedPromptCandidatesV2,
    graph: &KnowledgeGenerationV2,
    pair_evidence: Vec<PromptPairUtilityEvidenceV2>,
    verifier: &LearningEvidenceVerifierV1,
    request: PromptPortfolioRequestV1,
    now_unix_ms: u64,
) -> Result<VerifiedSelectedPromptPortfolioV2, VerifiedPromptError> {
    validate_selection_request(&request, now_unix_ms)?;
    validate_verifier_context(verifier, &priced.context)?;
    graph
        .validate()
        .map_err(|error| VerifiedPromptError::Graph(format!("{error:?}")))?;
    if graph.generation_vector_digest != priced.candidates.generation_vector_digest {
        return Err(VerifiedPromptError::GraphDrift);
    }

    let factor_ids = priced
        .rows
        .iter()
        .map(|row| row.binding.factor_id.clone())
        .collect::<Vec<_>>();
    let relation_result = query_relations(
        graph,
        KnowledgeRelationQueryV2 {
            query_id: request.graph_query_id.clone(),
            generation_digest: graph.generation_digest,
            seed_node_ids: factor_ids.clone(),
            valid_at_unix_seconds: Some(
                i64::try_from(now_unix_ms / 1000)
                    .map_err(|_| VerifiedPromptError::PortfolioExpired)?,
            ),
            relation_kinds: vec![
                KnowledgeRelationKindV2::PromptComplements,
                KnowledgeRelationKindV2::PromptSubstitutes,
                KnowledgeRelationKindV2::PromptConflicts,
                KnowledgeRelationKindV2::PromptRequires,
                KnowledgeRelationKindV2::PromptDominates,
                KnowledgeRelationKindV2::PromptRedundant,
                KnowledgeRelationKindV2::PromptSupersedes,
            ],
            maximum_edges: MAX_CANONICAL_INTERACTION_EDGES,
        },
    )
    .map_err(|error| VerifiedPromptError::Graph(format!("{error:?}")))?;
    if relation_result.omitted_count != 0 {
        return Err(VerifiedPromptError::InteractionProjectionIncomplete(
            relation_result.omitted_count,
        ));
    }

    let mut problem = DensePromptProblem::new(
        priced,
        request.token_budget,
        request.maximum_selected_factors,
    )?;
    let mut numeric_edges = BTreeMap::<(StableId, StableId), Digest32>::new();
    let mut graph_valid_until = u64::MAX;
    for edge in &relation_result.edges {
        graph_valid_until = graph_valid_until.min(edge_valid_until_ms(edge, now_unix_ms)?);
        let left = &edge.identity.source_node_id;
        let right = &edge.identity.target_node_id;
        let Some(&left_index) = problem.id_to_index.get(left) else {
            if edge.identity.relation == KnowledgeRelationKindV2::PromptRequires
                && problem.id_to_index.contains_key(left)
            {
                return Err(VerifiedPromptError::RequiredFactorUnavailable(
                    right.to_string(),
                ));
            }
            continue;
        };
        let Some(&right_index) = problem.id_to_index.get(right) else {
            if edge.identity.relation == KnowledgeRelationKindV2::PromptRequires {
                return Err(VerifiedPromptError::RequiredFactorUnavailable(
                    right.to_string(),
                ));
            }
            continue;
        };
        match edge.identity.relation {
            KnowledgeRelationKindV2::PromptRequires => {
                problem.requires[left_index].insert(right_index);
            }
            KnowledgeRelationKindV2::PromptConflicts
            | KnowledgeRelationKindV2::PromptRedundant => {
                problem.conflicts[left_index].insert(right_index);
                problem.conflicts[right_index].insert(left_index);
            }
            KnowledgeRelationKindV2::PromptDominates
            | KnowledgeRelationKindV2::PromptSupersedes => {
                problem.dominated.insert(right_index);
            }
            KnowledgeRelationKindV2::PromptComplements
            | KnowledgeRelationKindV2::PromptSubstitutes => {
                let key = stable_pair(left, right);
                if numeric_edges.insert(key, edge.validity_digest).is_some() {
                    return Err(VerifiedPromptError::Graph(
                        "duplicate numeric interaction".to_owned(),
                    ));
                }
            }
            _ => {}
        }
    }
    problem.finish_constraints()?;

    let mut pair_by_key = BTreeMap::new();
    let mut pair_payload_digests = Vec::new();
    let mut evidence_valid_until = priced.evidence_valid_until_unix_ms;
    for evidence in pair_evidence {
        if evidence.context != priced.context
            || evidence.state_digest != priced.candidates.receipt.state_digest
            || evidence.graph_generation_digest != graph.generation_digest
            || evidence.left_factor_id >= evidence.right_factor_id
            || evidence.support_audit_digest.is_zero()
            || evidence.confidence_lower_q32 > evidence.marginal_utility_q32
            || evidence.marginal_utility_q32 > evidence.confidence_upper_q32
        {
            return Err(VerifiedPromptError::Evidence(
                "invalid pair evidence binding".to_owned(),
            ));
        }
        let key = stable_pair(&evidence.left_factor_id, &evidence.right_factor_id);
        let expected_validity = numeric_edges
            .get(&key)
            .ok_or_else(|| VerifiedPromptError::Evidence("unexpected pair evidence".to_owned()))?;
        if evidence.edge_validity_digest != *expected_validity {
            return Err(VerifiedPromptError::Evidence(
                "pair edge validity drift".to_owned(),
            ));
        }
        let payload = pair_evidence_signing_payload_v2(&evidence);
        let verified = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence.evidence,
                &payload,
                now_unix_ms,
            )
            .map_err(|error| VerifiedPromptError::Evidence(format!("{error:?}")))?;
        if verified.controller_id() == &priced.generator_controller_id
            || verified.principal().principal_id == priced.generator_principal_id
        {
            return Err(VerifiedPromptError::EvidenceIndependence(
                "pair evaluator collides with candidate generator".to_owned(),
            ));
        }
        evidence_valid_until = evidence_valid_until.min(evidence.evidence.expires_at);
        pair_payload_digests.push(verified.payload_digest());
        if pair_by_key
            .insert(key, evidence.marginal_utility_q32)
            .is_some()
        {
            return Err(VerifiedPromptError::DuplicateEvidence(
                "pair interaction".to_owned(),
            ));
        }
    }
    for key in numeric_edges.keys() {
        let value = pair_by_key.get(key).ok_or_else(|| {
            VerifiedPromptError::MissingEvidence(format!("pair {} {}", key.0, key.1))
        })?;
        let left_index = *problem
            .id_to_index
            .get(&key.0)
            .ok_or_else(|| VerifiedPromptError::Graph("left factor missing".to_owned()))?;
        let right_index = *problem
            .id_to_index
            .get(&key.1)
            .ok_or_else(|| VerifiedPromptError::Graph("right factor missing".to_owned()))?;
        problem
            .pair_values
            .insert((left_index, right_index), *value);
    }
    if evidence_valid_until <= now_unix_ms || graph_valid_until <= now_unix_ms {
        return Err(VerifiedPromptError::EvidenceExpired);
    }

    let outcome = solve_prompt_problem(&problem)?;
    let selected_bindings = outcome
        .selected
        .indices(problem.rows.len())
        .map(|index| problem.rows[index].binding.clone())
        .collect::<Vec<_>>();
    let selected_ids = selected_bindings
        .iter()
        .map(|binding| binding.factor_id.clone())
        .collect::<Vec<_>>();
    let total_tokens = problem.tokens(outcome.selected)?;
    let total_token_upper_bound =
        u32::try_from(total_tokens).map_err(|_| VerifiedPromptError::TokenBudgetLimit)?;
    let expected_utility = problem.utility(outcome.selected)?;

    let mut valid_until = request
        .requested_valid_until_unix_ms
        .min(evidence_valid_until)
        .min(graph_valid_until);
    for binding in &selected_bindings {
        if let Some(expires) = binding.realization.expires_unix_ms {
            valid_until = valid_until.min(expires);
        }
    }
    if valid_until <= now_unix_ms {
        return Err(VerifiedPromptError::PortfolioExpired);
    }

    pair_payload_digests.sort();
    let interaction_digest =
        digest_interactions_v2(relation_result.result_digest, &pair_payload_digests, &problem);
    let receipt_digest = digest_portfolio_receipt_v2(
        &request.portfolio_id,
        priced.candidates.candidates_digest,
        &selected_ids,
        interaction_digest,
        expected_utility,
        total_token_upper_bound,
        valid_until,
        priced.pricing_set_digest,
        graph.generation_digest,
    );
    let inner = v1::SelectedPromptPortfolioV1 {
        receipt: v1::PromptPortfolioReceiptV1 {
            portfolio_id: request.portfolio_id,
            candidate_set_digest: priced.candidates.candidates_digest,
            factor_ids: selected_ids,
            interaction_digest,
            expected_utility_q32: expected_utility,
            total_token_upper_bound,
            valid_until_unix_ms: valid_until,
            receipt_digest,
            authority: AuthorityPosture::DENY_ALL,
        },
        selected: selected_bindings,
        objective_digest: priced.candidates.receipt.objective_digest,
        state_digest: priced.candidates.receipt.state_digest,
        model_tuple: priced.candidates.model_tuple.clone(),
        model_tuple_digest: priced.candidates.model_tuple.digest(),
        generation_vector_digest: priced.candidates.generation_vector_digest,
        pricing_set_digest: priced.pricing_set_digest,
        graph_generation_digest: graph.generation_digest,
        selection_method: PromptSelectionMethodV1::GreedyPrerequisiteBundleV1,
        optimality: PromptOptimalityDisclosureV1::HeuristicNoCertificate,
    };
    validate_selected(&inner, priced)?;

    let decisions = build_candidate_decisions(&problem, outcome.selected)?;
    let selected_tokens = total_tokens;
    let token_utilization_ppm = if request.token_budget == 0 {
        0
    } else {
        u32::try_from(
            selected_tokens
                .saturating_mul(PPM_ONE)
                .checked_div(request.token_budget)
                .unwrap_or(0)
                .min(PPM_ONE),
        )
        .unwrap_or(u32::MAX)
    };
    let relaxed_upper_bound = problem.relaxed_upper_bound()?;
    let heuristic_gap = relaxed_upper_bound
        .checked_sub(expected_utility)
        .unwrap_or(FixedQ32::ZERO)
        .max(FixedQ32::ZERO);
    let termination = if outcome.exact_complete {
        PromptSolverTerminationV2::ExactSmallProblem
    } else if outcome.local_evaluations >= MAX_LOCAL_SEARCH_EVALUATIONS {
        PromptSolverTerminationV2::EvaluationBudget
    } else {
        PromptSolverTerminationV2::LocalOptimum
    };
    let mut audit = PromptPortfolioAuditV2 {
        candidate_count: u32::try_from(problem.rows.len()).unwrap_or(u32::MAX),
        selected_count: u32::try_from(outcome.selected.count()).unwrap_or(u32::MAX),
        no_intervention: outcome.selected.count() == 0,
        solver_rounds: outcome.rounds,
        local_evaluations: outcome.local_evaluations,
        exact_nodes: outcome.exact_nodes,
        exact_complete: outcome.exact_complete,
        termination,
        incumbent_utility_q32: expected_utility,
        relaxed_upper_bound_q32: relaxed_upper_bound,
        heuristic_gap_q32: heuristic_gap,
        token_budget: request.token_budget,
        selected_tokens,
        token_utilization_ppm,
        oldest_evidence_age_ms: now_unix_ms.saturating_sub(priced.oldest_evidence_issued_at),
        evidence_valid_until_unix_ms: evidence_valid_until,
        graph_generation_digest: graph.generation_digest,
        evidence_binding_digest: priced.evidence_binding_digest,
        decisions,
        audit_digest: Digest32::ZERO,
    };
    audit.audit_digest = digest_portfolio_audit(&audit, receipt_digest);

    Ok(VerifiedSelectedPromptPortfolioV2 {
        inner,
        context: priced.context.clone(),
        trust_digest: verifier.trust_digest(),
        authority_epoch: verifier.authority_epoch(),
        scope_digest: verifier.scope_digest(),
        evidence_valid_until_unix_ms: evidence_valid_until,
        graph_valid_until_unix_ms: graph_valid_until,
        audit,
    })
}
