use super::*;

fn sign_temporal_evidence(
    verifier: &LearningEvidenceVerifierV1,
    name: &str,
    role: LearningEvidenceRoleV1,
    seed: u8,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence:{name}")),
        principal_id: id(name),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 1,
        issued_at: 50,
        expires_at: 10_000,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

fn authentic_temporal_prices(
    registry: &DurablePromptRegistry,
) -> (PricedPromptCandidatesV1, LearningEvidenceVerifierV1) {
    let signers = [
        ("generator", 7, LearningEvidenceRoleV1::Generator),
        ("evaluator", 8, LearningEvidenceRoleV1::Evaluator),
    ]
    .into_iter()
    .map(|(name, seed, role)| {
        let key = SigningKey::from_bytes(&[seed; 32])
            .verifying_key()
            .to_bytes();
        TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id(name),
                credential_chain_digest: digest(name),
                signing_key_digest: Digest32::of_bytes(&key),
                scope_digest: digest("scope"),
                authority_epoch: 1,
                authenticated_at: 1,
                expires_at: 10_000,
            },
            controller_id: id(&format!("controller:{name}")),
            verifying_key: key,
            roles: vec![role],
            revoked_at: None,
        }
    })
    .collect();
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 1,
        signers,
    })
    .expect("host-owned generator and evaluator keys");
    let candidates = enumerate_factors_v1(
        registry.registry().expect("registry"),
        PromptEnumerationRequestV1 {
            set_id: id("set:temporal"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            generation_vector_digest: digest("generation-vector"),
            model_tuple: model_tuple(),
            now_unix_ms: 100,
            required_factor_ids: vec![id("factor:a"), id("factor:b")],
            maximum_candidates: 2,
            selection_grammar_digest: digest("grammar"),
        },
    )
    .expect("enumerate actual signed owner bindings");
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: candidates.receipt.set_id.clone(),
        state_digest: candidates.receipt.state_digest,
        generator_id: id("prompt.optimizer"),
        generator_code_digest: digest("generator-code"),
        grammar_digest: candidates.receipt.selection_grammar_digest,
        hard_filter_digest: digest("filters"),
        truncation_digest: digest("truncation"),
        candidates_digest: candidates.candidates_digest,
        candidate_count: 2,
        omitted_count_bound: 0,
        canonical_order_digest: candidates.canonical_order_digest,
        complete_for_generator: true,
    };
    let completeness_evidence = sign_temporal_evidence(
        &verifier,
        "generator",
        LearningEvidenceRoleV1::Generator,
        /*seed*/ 7,
        &candidate_completeness_signing_payload_v1(&completeness)
            .expect("complete candidate signing bytes"),
    );
    let prices = candidates
        .candidates
        .iter()
        .map(|candidate| {
            let utility = if candidate.factor_id == id("factor:a") {
                FixedQ32::from_raw(100)
            } else {
                FixedQ32::from_raw(90)
            };
            let mut evidence = PromptPricingEvidenceV1 {
                factor_id: candidate.factor_id.clone(),
                state_digest: candidates.receipt.state_digest,
                model_tuple_digest: candidates.model_tuple.digest(),
                expected_incremental_utility_q32: utility,
                downside_q32: FixedQ32::ZERO,
                confidence_lower_q32: utility,
                confidence_upper_q32: utility,
                support_count: 10,
                latency_cost_micros: 0,
                interference_ppm: 0,
                context_crowding_cost_q32: FixedQ32::ZERO,
                privacy_cost_q32: FixedQ32::ZERO,
                instability_cost_q32: FixedQ32::ZERO,
                future_context_option_cost_q32: FixedQ32::ZERO,
                support_audit_digest: digest("support-audit"),
                evidence: completeness_evidence.clone(),
            };
            evidence.evidence = sign_temporal_evidence(
                &verifier,
                "evaluator",
                LearningEvidenceRoleV1::Evaluator,
                /*seed*/ 8,
                &pricing_evidence_signing_payload_v1(&evidence),
            );
            evidence
        })
        .collect();
    let priced = price_factors_v1(
        candidates,
        &completeness,
        &completeness_evidence,
        prices,
        &verifier,
        &PromptPricingPolicyV1 {
            policy_id: id("policy:temporal"),
            token_cost_per_token_q32: FixedQ32::ZERO,
            latency_cost_per_micro_q32: FixedQ32::ZERO,
            interference_cost_per_ppm_q32: FixedQ32::ZERO,
            downside_weight_q32: FixedQ32::ZERO,
            minimum_support_count: 1,
            maximum_interference_ppm: 0,
        },
        /*now_unix_ms*/ 100,
    )
    .expect("price authenticated generator and evaluator attestations");
    (priced, verifier)
}

#[derive(Clone, Copy)]
enum WindowLocation {
    Edge,
    Endpoint,
}

#[test]
fn portfolio_expires_before_future_conflict_or_endpoint_visibility_changes() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, _tuple, authority, signing_key, grant_now) =
        registry_fixture(&temp.path().join("registry"), &[1]);
    register_second_factor(&mut registry, &authority, &signing_key, grant_now);
    let (priced, verifier) = authentic_temporal_prices(&registry);
    let source_digest = priced.candidates.registry_snapshot.registry_digest;
    for location in [WindowLocation::Edge, WindowLocation::Endpoint] {
        let mut graph = graph(
            &["factor:a", "factor:b"],
            vec![(
                "factor:a",
                KnowledgeRelationKindV2::PromptConflicts,
                "factor:b",
            )],
        );
        let support = match location {
            WindowLocation::Edge => &mut graph.edges[0].supports[0],
            WindowLocation::Endpoint => &mut graph.nodes[1].supports[0],
        };
        support.valid_from_unix_seconds = Some(1);
        support.valid_to_unix_seconds = Some(2);
        let graph = build_complete_generation(
            graph.generation,
            KnowledgeProjectionInputV2 {
                source_snapshot_digest: graph.source_snapshot_digest,
                generation_vector_digest: graph.generation_vector_digest,
                graph_profile_digest: graph.graph_profile_digest,
                complete_source_cut: true,
                nodes: graph.nodes,
                edges: graph.edges,
            },
        )
        .expect("complete graph containing a future temporal conflict");
        let request = PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:temporal"),
            graph_query_id: id("query:temporal"),
            token_budget: 2,
            maximum_selected_factors: 2,
            requested_valid_until_unix_ms: 5_000,
        };
        let mut selected = select_portfolio_v1(
            &priced,
            &graph,
            Vec::new(),
            &verifier,
            request.clone(),
            /*now_unix_ms*/ 999,
        )
        .expect("select before conflict visibility");
        assert_eq!(
            selected.receipt.factor_ids,
            vec![id("factor:a"), id("factor:b")]
        );
        assert_eq!(selected.receipt.valid_until_unix_ms, 1_000);
        let mut exercise_request = exercise_request_for(&selected);
        exercise_request.now_unix_ms = 999;
        assert_eq!(
            exercise_v1(
                registry.registry().expect("registry"),
                &selected,
                exercise_request.clone()
            )
            .expect("exercise within stable temporal cut")
            .decision,
            PromptExerciseActionV1::Exercise
        );
        for (at, factor_ids, valid_until) in [
            (1_000, vec![id("factor:a")], 2_000),
            (2_000, vec![id("factor:a"), id("factor:b")], 5_000),
        ] {
            exercise_request.now_unix_ms = at;
            assert_eq!(
                registry
                    .snapshot_v2(digest("generation-vector"), &model_tuple())
                    .expect("unchanged registry source")
                    .registry_digest,
                source_digest
            );
            assert_eq!(
                exercise_v1(
                    registry.registry().expect("registry"),
                    &selected,
                    exercise_request.clone()
                )
                .expect("old temporal selection is stale")
                .decision,
                PromptExerciseActionV1::RejectStale
            );
            selected =
                select_portfolio_v1(&priced, &graph, Vec::new(), &verifier, request.clone(), at)
                    .expect("reselect at inclusive start or exclusive end boundary");
            assert_eq!(selected.receipt.factor_ids, factor_ids);
            assert_eq!(selected.receipt.valid_until_unix_ms, valid_until);
        }
    }
}

#[test]
fn temporal_expiry_ignores_past_unrepresentable_and_unrelated_support_boundaries() {
    let priced = priced(vec![
        ("factor:a", "realization:a", 1, 100),
        ("factor:b", "realization:b", 1, 90),
    ]);
    for relation in [
        KnowledgeRelationKindV2::PromptConflicts,
        KnowledgeRelationKindV2::Causes,
    ] {
        let mut graph = graph(
            &["factor:a", "factor:b", "factor:c", "factor:d"],
            vec![
                ("factor:a", relation.clone(), "factor:b"),
                (
                    "factor:c",
                    KnowledgeRelationKindV2::PromptConflicts,
                    "factor:d",
                ),
            ],
        );
        if relation == KnowledgeRelationKindV2::Causes {
            graph.edges[0].supports[0].valid_from_unix_seconds = Some(1);
        } else {
            graph.edges[0].supports[0].valid_from_unix_seconds = Some(i64::MAX - 1);
            graph.edges[0].supports[0].valid_to_unix_seconds = Some(i64::MAX);
        }
        graph.edges[1].supports[0].valid_from_unix_seconds = Some(1);
        graph.nodes[2].supports[0].valid_from_unix_seconds = Some(1);
        // Past candidate support starts must not become an invalid zero deadline.
        graph.nodes[0].supports[0].valid_from_unix_seconds = Some(-2);
        let graph = build_complete_generation(
            graph.generation,
            KnowledgeProjectionInputV2 {
                source_snapshot_digest: graph.source_snapshot_digest,
                generation_vector_digest: graph.generation_vector_digest,
                graph_profile_digest: graph.graph_profile_digest,
                complete_source_cut: true,
                nodes: graph.nodes,
                edges: graph.edges,
            },
        )
        .expect("valid distant future and unrelated graph");
        let selected = select_portfolio_v1(
            &priced,
            &graph,
            Vec::new(),
            &verifier(),
            PromptPortfolioRequestV1 {
                portfolio_id: id("portfolio:unrelated-time"),
                graph_query_id: id("query:unrelated-time"),
                token_budget: 2,
                maximum_selected_factors: 2,
                requested_valid_until_unix_ms: 5_000,
            },
            /*now_unix_ms*/ 999,
        )
        .expect("select with no representable relevant future boundary");
        assert_eq!(selected.receipt.valid_until_unix_ms, 5_000);
        assert_eq!(
            selected.receipt.factor_ids,
            vec![id("factor:a"), id("factor:b")]
        );
    }
}
