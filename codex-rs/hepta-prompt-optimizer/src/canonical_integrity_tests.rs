use super::*;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture ID")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn portfolio() -> SelectedPromptPortfolioV1 {
    select_portfolio_v1(
        &tests::priced(vec![("factor:a", "realization:a", 1, 100)]),
        &tests::graph(&["factor:a"], Vec::new()),
        Vec::new(),
        &tests::verifier(),
        PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:integrity"),
            graph_query_id: id("query:integrity"),
            token_budget: 8,
            maximum_selected_factors: 1,
            requested_valid_until_unix_ms: 5_000,
        },
        100,
    )
    .expect("canonical selection")
}

fn rehash_portfolio_receipt(portfolio: &mut SelectedPromptPortfolioV1) {
    let receipt = &mut portfolio.receipt;
    receipt.receipt_digest = digest_portfolio_receipt(
        &receipt.portfolio_id,
        receipt.candidate_set_digest,
        &receipt.factor_ids,
        receipt.interaction_digest,
        receipt.expected_utility_q32,
        receipt.total_token_upper_bound,
        receipt.valid_until_unix_ms,
        portfolio.pricing_set_digest,
        portfolio.graph_generation_digest,
    );
}

#[test]
fn rehashed_pricing_mutation_cannot_mint_selection_provenance() {
    let mut priced = tests::priced(vec![("factor:a", "realization:a", 1, 100)]);
    let original_seal = priced.verified_pricing_digest;
    priced.rows[0].net_utility_q32 = FixedQ32::ONE;
    priced.rows[0].pricing.expected_utility_q32 = FixedQ32::ONE;
    // Recompute every public receipt exactly as an adversarial caller can.
    tests::seal_priced_fixture(&mut priced);
    priced.verified_pricing_digest = original_seal;
    assert_eq!(
        priced.validate(),
        Err(CanonicalPromptError::PricingIntegrity)
    );
    assert_eq!(
        select_portfolio_v1(
            &priced,
            &tests::graph(&["factor:a"], Vec::new()),
            Vec::new(),
            &tests::verifier(),
            PromptPortfolioRequestV1 {
                portfolio_id: id("portfolio:forged-pricing"),
                graph_query_id: id("query:forged-pricing"),
                token_budget: 8,
                maximum_selected_factors: 1,
                requested_valid_until_unix_ms: 5_000,
            },
            100,
        ),
        Err(CanonicalPromptError::PricingIntegrity)
    );
}

#[test]
fn rehashed_expiry_and_utility_cannot_mint_exercise_provenance() {
    let original = portfolio();
    assert_eq!(original.validate(), Ok(()));
    let temporary = tempfile::tempdir().expect("tempdir");
    let registry = DurablePromptRegistry::open_state_dir(&temporary.path().join("registry"), 64)
        .expect("registry");
    for mutate in [
        (|value: &mut SelectedPromptPortfolioV1| value.receipt.valid_until_unix_ms = 9_000)
            as fn(&mut SelectedPromptPortfolioV1),
        |value| value.receipt.expected_utility_q32 = FixedQ32::ONE,
        |value| value.objective_digest = digest("other-objective"),
        |value| value.state_digest = digest("other-state"),
        |value| value.generation_vector_digest = digest("other-generation"),
    ] {
        let mut changed = original.clone();
        mutate(&mut changed);
        rehash_portfolio_receipt(&mut changed);
        assert_eq!(
            exercise_v1(
                registry.registry().expect("registry view"),
                &changed,
                PromptExerciseRequestV1 {
                    decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
                    current_state_digest: changed.state_digest,
                    generation_vector_digest: changed.generation_vector_digest,
                    model_tuple: changed.model_tuple.clone(),
                    now_unix_ms: 100,
                    wait_value_q32: FixedQ32::ZERO,
                    policy_digest: digest("exercise-policy"),
                },
            ),
            Err(CanonicalPromptError::PortfolioIntegrity)
        );
    }
}

#[test]
fn portfolio_semantics_reject_mismatched_factors_tokens_and_expiry() {
    let original = portfolio();
    for mutate in [
        (|value: &mut SelectedPromptPortfolioV1| {
            value.receipt.factor_ids = vec![id("factor:other")]
        }) as fn(&mut SelectedPromptPortfolioV1),
        |value| value.receipt.total_token_upper_bound = 0,
        |value| value.receipt.valid_until_unix_ms = 10_001,
        |value| value.model_tuple_digest = digest("other-model"),
    ] {
        let mut changed = original.clone();
        mutate(&mut changed);
        rehash_portfolio_receipt(&mut changed);
        // Even an internally minted seal cannot bypass semantic constraints.
        changed.verified_portfolio_digest = integrity::portfolio_digest(&changed);
        assert_eq!(
            changed.validate(),
            Err(CanonicalPromptError::PortfolioIntegrity)
        );
    }
}

#[test]
fn candidate_fields_must_match_completeness_bound_content_digests() {
    let original = tests::priced(vec![("factor:a", "realization:a", 1, 100)]);
    let mut changed = original.candidates.clone();
    changed.candidates[0].realization.token_cost = 2;
    changed.candidates[0].binding_digest = changed.candidates[0].realization.digest();
    assert_eq!(
        integrity::validate_candidates(&changed),
        Err(CanonicalPromptError::CandidateIntegrity)
    );
    let mut duplicate = original.candidates;
    duplicate.candidates.push(duplicate.candidates[0].clone());
    assert_eq!(
        integrity::validate_candidates(&duplicate),
        Err(CanonicalPromptError::CandidateIntegrity)
    );
}

#[test]
fn rehashed_enumeration_metadata_cannot_hide_omissions() {
    let mut priced = tests::priced(vec![("factor:a", "realization:a", 1, 100)]);
    priced.candidates.omitted_count = 10;
    tests::seal_priced_fixture(&mut priced);
    let original_enumeration_seal = priced.candidates.verified_enumeration_digest;
    priced.candidates.omitted_count = 0;
    // Refresh public hashes while retaining the seal minted for ten omissions.
    tests::seal_priced_fixture(&mut priced);
    priced.candidates.verified_enumeration_digest = original_enumeration_seal;
    assert_eq!(
        integrity::validate_candidates(&priced.candidates),
        Err(CanonicalPromptError::CandidateIntegrity)
    );
}

#[test]
fn selection_cannot_mix_pricing_with_another_objective_or_trust_epoch() {
    let priced = tests::priced(vec![("factor:a", "realization:a", 1, 100)]);
    for verifier in [
        tests::verifier_for(digest("other-objective"), /*authority_epoch*/ 1),
        tests::verifier_for(digest("objective"), /*authority_epoch*/ 2),
    ] {
        assert_eq!(
            select_portfolio_v1(
                &priced,
                &tests::graph(&["factor:a"], Vec::new()),
                Vec::new(),
                &verifier,
                PromptPortfolioRequestV1 {
                    portfolio_id: id("portfolio:mixed-trust"),
                    graph_query_id: id("query:mixed-trust"),
                    token_budget: 8,
                    maximum_selected_factors: 1,
                    requested_valid_until_unix_ms: 5_000,
                },
                100,
            ),
            Err(CanonicalPromptError::PricingIntegrity)
        );
    }
}

#[test]
fn selection_obeys_pricing_verification_time_and_exclusive_horizon() {
    for horizon in [150, 201] {
        let mut priced = tests::priced(vec![("factor:a", "realization:a", 1, 100)]);
        priced.verified_valid_until_unix_ms = horizon;
        priced.verified_pricing_digest = integrity::priced_digest(&priced);
        for now in [99, 100, horizon - 1, horizon] {
            let selected = select_portfolio_v1(
                &priced,
                &tests::graph(&["factor:a"], Vec::new()),
                Vec::new(),
                &tests::verifier(),
                PromptPortfolioRequestV1 {
                    portfolio_id: id("portfolio:freshness"),
                    graph_query_id: id("query:freshness"),
                    token_budget: 8,
                    maximum_selected_factors: 1,
                    requested_valid_until_unix_ms: 5_000,
                },
                now,
            );
            if now < priced.verified_at_unix_ms {
                assert_eq!(selected, Err(CanonicalPromptError::InvalidTime));
            } else if now >= horizon {
                assert_eq!(selected, Err(CanonicalPromptError::PortfolioExpired));
            } else {
                assert_eq!(
                    selected
                        .expect("fresh selection")
                        .receipt
                        .valid_until_unix_ms,
                    horizon
                );
            }
        }
    }
}

#[test]
fn pair_evidence_expiry_caps_selected_portfolio_horizon() {
    let priced = tests::priced(vec![
        ("factor:a", "realization:a", 1, 100),
        ("factor:b", "realization:b", 1, 100),
    ]);
    let graph = tests::graph(
        &["factor:a", "factor:b"],
        vec![(
            "factor:a",
            KnowledgeRelationKindV2::PromptComplements,
            "factor:b",
        )],
    );
    let verifier = tests::verifier();
    let mut pair = PromptPairUtilityEvidenceV1 {
        left_factor_id: id("factor:a"),
        right_factor_id: id("factor:b"),
        state_digest: priced.candidates.receipt.state_digest,
        graph_generation_digest: graph.generation_digest,
        edge_validity_digest: digest("edge:factor:a:factor:b"),
        marginal_utility_q32: FixedQ32::from_raw(10),
        confidence_lower_q32: FixedQ32::from_raw(10),
        confidence_upper_q32: FixedQ32::from_raw(10),
        support_audit_digest: digest("pair-audit"),
        evidence: SignedLearningEvidenceV1 {
            evidence_id: id("evidence:pair"),
            principal_id: id("evaluator"),
            role: LearningEvidenceRoleV1::Evaluator,
            trust_digest: verifier.trust_digest(),
            scope_digest: verifier.scope_digest(),
            objective_digest: verifier.objective_digest(),
            authority_epoch: 1,
            issued_at: 50,
            expires_at: 200,
            payload_digest: Digest32::ZERO,
            signature: [0; 64],
        },
    };
    pair.evidence.payload_digest =
        Digest32::of_bytes(&pair_utility_evidence_signing_payload_v1(&pair));
    pair.evidence.signature = SigningKey::from_bytes(&[7; 32])
        .sign(&pair.evidence.signing_bytes())
        .to_bytes();
    let selected = select_portfolio_v1(
        &priced,
        &graph,
        vec![pair],
        &verifier,
        PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:pair-horizon"),
            graph_query_id: id("query:pair-horizon"),
            token_budget: 8,
            maximum_selected_factors: 2,
            requested_valid_until_unix_ms: 5_000,
        },
        100,
    )
    .expect("pair signed evidence");
    assert_eq!(selected.receipt.valid_until_unix_ms, 201);
}

#[test]
fn exercise_cannot_use_a_portfolio_before_selection_time() {
    let selected = portfolio();
    let temporary = tempfile::tempdir().expect("tempdir");
    let registry = DurablePromptRegistry::open_state_dir(&temporary.path().join("registry"), 64)
        .expect("registry");
    let decision = exercise_v1(
        registry.registry().expect("registry view"),
        &selected,
        PromptExerciseRequestV1 {
            decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
            current_state_digest: selected.state_digest,
            generation_vector_digest: selected.generation_vector_digest,
            model_tuple: selected.model_tuple.clone(),
            now_unix_ms: selected.selected_at_unix_ms - 1,
            wait_value_q32: FixedQ32::ZERO,
            policy_digest: digest("exercise-policy"),
        },
    )
    .expect("stale decision receipt");
    assert_eq!(decision.decision, PromptExerciseActionV1::RejectStale);
}
