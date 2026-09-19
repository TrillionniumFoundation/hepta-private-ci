use super::*;

use codex_hepta_kg::{
    build_complete_generation, KnowledgeEdgeIdentityV2, KnowledgeEdgeV2, KnowledgeNodeV2,
    KnowledgeProjectionInputV2, KnowledgeRelationKindV2, KnowledgeSupportV2,
};
use codex_hepta_learning_ledger::{
    AuthenticatedPrincipalV1, LearningEvidenceTrustV1, TrustedLearningSignerV1,
};
use codex_hepta_prompt_registry::{
    FactorSource, Lifecycle, PromptFactor, PromptRealizationBindingV2, PromptRoleV2,
};
use codex_hepta_types::{Generation, ProbabilityQ32, Revision};
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn model_tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        locale_id: id("locale:en-US"),
    }
}

fn binding(factor: &str, realization: &str, tokens: u32) -> PromptRealizationBindingV2 {
    let tuple = model_tuple();
    PromptRealizationBindingV2 {
        realization_id: id(realization),
        factor_id: id(factor),
        model_digest: tuple.model_digest,
        tokenizer_digest: tuple.tokenizer_digest,
        template_digest: tuple.template_digest,
        tool_schema_digest: tuple.tool_schema_digest,
        locale_id: tuple.locale_id,
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: digest(&format!("payload:{realization}")),
        token_cost: tokens,
        expires_unix_ms: Some(10_000),
    }
}

fn register_factor(registry: &mut PromptRegistry, factor_id: &str) {
    registry
        .register_factor(PromptFactor {
            factor_id: id(factor_id),
            proposer_id: id(&format!("proposer:{factor_id}")),
            semantic_version: id("v1"),
            content_digest: digest(&format!("factor:{factor_id}")),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        })
        .unwrap_or_else(|error| panic!("register factor: {error}"));
    registry
        .admit_factor(
            &id(factor_id),
            &id(&format!("reviewer:{factor_id}")),
            digest("admission"),
        )
        .unwrap_or_else(|error| panic!("admit factor: {error}"));
}

fn candidate(factor: &str, realization: &str, tokens: u32) -> PromptCandidateBindingV1 {
    let realization = binding(factor, realization, tokens);
    PromptCandidateBindingV1 {
        factor_id: realization.factor_id.clone(),
        binding_digest: realization.digest(),
        realization,
    }
}

fn dummy_snapshot(tuple: &PromptModelTupleV2, generation_vector: Digest32) -> PromptRegistrySnapshotV2 {
    PromptRegistrySnapshotV2 {
        revision: Revision::new(1).expect("revision"),
        registry_digest: digest("registry"),
        lifecycle_frontier: 1,
        revocation_frontier: 0,
        generation_vector_digest: generation_vector,
        model_tuple_digest: tuple.digest(),
        snapshot_digest: digest("snapshot"),
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn priced(rows: Vec<(&str, &str, u32, i64)>) -> PricedPromptCandidatesV1 {
    let tuple = model_tuple();
    let generation_vector = digest("generation-vector");
    let state = digest("state");
    let candidates = rows
        .iter()
        .map(|(factor, realization, tokens, _)| candidate(factor, realization, *tokens))
        .collect::<Vec<_>>();
    let factor_ids = candidates
        .iter()
        .map(|candidate| candidate.factor_id.clone())
        .collect::<Vec<_>>();
    let enumerated = EnumeratedPromptCandidatesV1 {
        registry_snapshot: dummy_snapshot(&tuple, generation_vector),
        model_tuple: tuple,
        generation_vector_digest: generation_vector,
        candidates_digest: digest("candidate-set"),
        canonical_order_digest: digest("candidate-order"),
        omitted_count: 0,
        receipt: PromptCandidateSetReceiptV1 {
            set_id: id("set:1"),
            objective_digest: digest("objective"),
            state_digest: state,
            registry_digest: digest("registry"),
            candidate_factor_ids: factor_ids,
            selection_grammar_digest: digest("grammar"),
            receipt_digest: digest("candidate-receipt"),
            authority: AuthorityPosture::DENY_ALL,
        },
        candidates: candidates.clone(),
    };
    let priced_rows = rows
        .into_iter()
        .zip(candidates)
        .map(|((factor, _, tokens, utility), binding)| PricedPromptCandidateV1 {
            binding,
            pricing: PromptPricingReceiptV1 {
                factor_id: id(factor),
                state_digest: state,
                expected_utility_q32: FixedQ32::from_raw(utility),
                downside_q32: FixedQ32::ZERO,
                token_cost: tokens,
                latency_cost_micros: 0,
                interference_ppm: 0,
                confidence_interval: PromptConfidenceIntervalV1 {
                    lower_q32: FixedQ32::from_raw(utility),
                    upper_q32: FixedQ32::from_raw(utility),
                    support_count: 10,
                    support_audit_digest: digest("support-audit"),
                },
                receipt_digest: digest(&format!("pricing:{factor}")),
                authority: AuthorityPosture::DENY_ALL,
            },
            net_utility_q32: FixedQ32::from_raw(utility),
        })
        .collect();
    PricedPromptCandidatesV1 {
        candidates: enumerated,
        completeness_digest: digest("completeness"),
        pricing_policy_digest: digest("pricing-policy"),
        rows: priced_rows,
        pricing_set_digest: digest("pricing-set"),
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn support(label: &str) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(&format!("support:{label}")),
        source_revision: Revision::new(1).expect("revision"),
        source_fact_digest: digest(&format!("fact:{label}")),
        validity_digest: digest(&format!("validity:{label}")),
        tombstoned: false,
    }
}

fn graph(
    factors: &[&str],
    relations: Vec<(&str, KnowledgeRelationKindV2, &str)>,
) -> KnowledgeGenerationV2 {
    let nodes = factors
        .iter()
        .map(|factor| KnowledgeNodeV2 {
            node_id: id(factor),
            node_kind_id: id("kind:prompt-factor"),
            payload_digest: digest(&format!("node:{factor}")),
            supports: vec![support(factor)],
        })
        .collect();
    let edges = relations
        .into_iter()
        .map(|(left, relation, right)| KnowledgeEdgeV2 {
            identity: KnowledgeEdgeIdentityV2 {
                source_node_id: id(left),
                relation,
                target_node_id: id(right),
            },
            confidence: ProbabilityQ32::ONE,
            validity_digest: digest(&format!("edge:{left}:{right}")),
            supports: vec![support(&format!("{left}:{right}"))],
        })
        .collect();
    build_complete_generation(
        Generation::new(1).expect("generation"),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: digest("kg-source"),
            generation_vector_digest: digest("generation-vector"),
            graph_profile_digest: digest("kg-profile"),
            complete_source_cut: true,
            nodes,
            edges,
        },
    )
    .unwrap_or_else(|error| panic!("graph: {error}"))
}

fn verifier() -> LearningEvidenceVerifierV1 {
    let signing = SigningKey::from_bytes(&[7; 32]);
    let public = signing.verifying_key().to_bytes();
    LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 1,
        signers: vec![TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id("evaluator"),
                credential_chain_digest: digest("credential"),
                signing_key_digest: Digest32::of_bytes(&public),
                scope_digest: digest("scope"),
                authority_epoch: 1,
                authenticated_at: 1,
                expires_at: 10_000,
            },
            controller_id: id("controller:evaluator"),
            verifying_key: public,
            roles: vec![LearningEvidenceRoleV1::Evaluator],
            revoked_at: None,
        }],
    })
    .unwrap_or_else(|error| panic!("verifier: {error}"))
}

#[test]
fn enumeration_selects_lowest_cost_compatible_realization_per_factor() {
    let mut registry = PromptRegistry::new(64).expect("registry");
    register_factor(&mut registry, "factor:a");
    registry
        .register_realization_v2(binding("factor:a", "realization:expensive", 50))
        .expect("expensive");
    registry
        .register_realization_v2(binding("factor:a", "realization:cheap", 5))
        .expect("cheap");

    let enumerated = enumerate_factors_v1(
        &registry,
        PromptEnumerationRequestV1 {
            set_id: id("set:enum"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            generation_vector_digest: digest("generation-vector"),
            model_tuple: model_tuple(),
            now_unix_ms: 100,
            required_factor_ids: vec![id("factor:a")],
            maximum_candidates: 8,
            selection_grammar_digest: digest("grammar"),
        },
    )
    .expect("enumerate");
    assert_eq!(enumerated.candidates.len(), 1);
    assert_eq!(
        enumerated.candidates[0].realization.realization_id,
        id("realization:cheap")
    );
    assert!(!enumerated.receipt.authority.grants_any());
}

#[test]
fn prerequisite_bundle_can_select_negative_prerequisite_for_positive_bundle() {
    let priced = priced(vec![
        ("factor:a", "realization:a", 1, 100),
        ("factor:b", "realization:b", 1, -1),
    ]);
    let graph = graph(
        &["factor:a", "factor:b"],
        vec![(
            "factor:a",
            KnowledgeRelationKindV2::PromptRequires,
            "factor:b",
        )],
    );
    let selected = select_portfolio_v1(
        &priced,
        &graph,
        Vec::new(),
        &verifier(),
        PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:bundle"),
            graph_query_id: id("query:bundle"),
            token_budget: 2,
            maximum_selected_factors: 2,
            requested_valid_until_unix_ms: 5_000,
        },
        100,
    )
    .expect("select bundle");

    assert_eq!(
        selected.receipt.factor_ids,
        vec![id("factor:a"), id("factor:b")]
    );
    assert_eq!(selected.receipt.expected_utility_q32, FixedQ32::from_raw(99));
    assert_eq!(
        selected.optimality,
        PromptOptimalityDisclosureV1::HeuristicNoCertificate
    );
}

#[test]
fn hard_conflict_cannot_be_outweighed_by_positive_numeric_utility() {
    let priced = priced(vec![
        ("factor:a", "realization:a", 1, 100),
        ("factor:b", "realization:b", 1, 90),
    ]);
    let graph = graph(
        &["factor:a", "factor:b"],
        vec![(
            "factor:a",
            KnowledgeRelationKindV2::PromptConflicts,
            "factor:b",
        )],
    );
    let selected = select_portfolio_v1(
        &priced,
        &graph,
        Vec::new(),
        &verifier(),
        PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:conflict"),
            graph_query_id: id("query:conflict"),
            token_budget: 2,
            maximum_selected_factors: 2,
            requested_valid_until_unix_ms: 5_000,
        },
        100,
    )
    .expect("select conflict");
    assert_eq!(selected.receipt.factor_ids, vec![id("factor:a")]);
}

#[test]
fn revocation_after_selection_rejects_exercise_at_delivery_boundary() {
    let mut registry = PromptRegistry::new(64).expect("registry");
    register_factor(&mut registry, "factor:a");
    let realization = binding("factor:a", "realization:a", 1);
    registry
        .register_realization_v2(realization.clone())
        .expect("realization");
    let selected = SelectedPromptPortfolioV1 {
        receipt: PromptPortfolioReceiptV1 {
            portfolio_id: id("portfolio:1"),
            candidate_set_digest: digest("candidate-set"),
            factor_ids: vec![id("factor:a")],
            interaction_digest: digest("interaction"),
            expected_utility_q32: FixedQ32::from_raw(10),
            total_token_upper_bound: 1,
            valid_until_unix_ms: 5_000,
            receipt_digest: digest("portfolio-receipt"),
            authority: AuthorityPosture::DENY_ALL,
        },
        selected: vec![PromptCandidateBindingV1 {
            factor_id: id("factor:a"),
            binding_digest: realization.digest(),
            realization,
        }],
        objective_digest: digest("objective"),
        state_digest: digest("state"),
        model_tuple: model_tuple(),
        model_tuple_digest: model_tuple().digest(),
        generation_vector_digest: digest("generation-vector"),
        pricing_set_digest: digest("pricing-set"),
        graph_generation_digest: digest("graph"),
        selection_method: PromptSelectionMethodV1::GreedyPrerequisiteBundleV1,
        optimality: PromptOptimalityDisclosureV1::HeuristicNoCertificate,
    };
    registry.revoke_factor(&id("factor:a")).expect("revoke");
    let exercise = exercise_v1(
        &registry,
        &selected,
        PromptExerciseRequestV1 {
            decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
            current_state_digest: digest("state"),
            generation_vector_digest: digest("generation-vector"),
            model_tuple: model_tuple(),
            now_unix_ms: 200,
            wait_value_q32: FixedQ32::ZERO,
            policy_digest: digest("exercise-policy"),
        },
    )
    .expect("exercise receipt");
    assert_eq!(exercise.decision, PromptExerciseActionV1::RejectStale);
    assert!(!exercise.authority.grants_any());
}

#[test]
fn incomplete_candidate_completeness_cannot_be_authenticated_for_pricing() {
    let receipt = CandidateSetCompletenessReceiptV1 {
        set_id: id("set:1"),
        state_digest: digest("state"),
        generator_id: id("prompt.optimizer"),
        generator_code_digest: digest("generator-code"),
        grammar_digest: digest("grammar"),
        hard_filter_digest: digest("filters"),
        truncation_digest: digest("truncation"),
        candidates_digest: digest("candidates"),
        candidate_count: 1,
        omitted_count_bound: 0,
        canonical_order_digest: digest("order"),
        complete_for_generator: false,
    };
    assert!(candidate_completeness_signing_payload_v1(&receipt).is_err());
}
