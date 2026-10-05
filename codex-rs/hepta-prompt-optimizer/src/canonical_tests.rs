use super::*;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_prompt_registry::final_use_realization_binding;
use codex_hepta_prompt_registry::final_use_revoke_binding;
use ed25519_dalek::Signer;
use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptFactorRelation;
use codex_hepta_prompt_registry::PromptFactorRelationKind;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn model_tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_id: id("model:test"),
        model_version: "2026-09-21".to_owned(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
    }
}

fn priced(rows: Vec<(&str, &str, u32, i64)>) -> PricedPromptCandidatesV1 {
    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, _tuple, authority, signing_key, now) =
        registry_fixture(&temp.path().join("registry"), &[1]);
    if rows.iter().any(|(factor, _, _, _)| *factor == "factor:b") {
        register_second_factor(&mut registry, &authority, &signing_key, now);
    }
    let enumerated = enumerate_factors_v1(
        registry.registry().expect("registry"),
        PromptEnumerationRequestV1 {
            set_id: id("set:1"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            generation_vector_digest: digest("generation-vector"),
            model_tuple: model_tuple(),
            now_unix_ms: 100,
            required_factor_ids: rows.iter().map(|(factor, _, _, _)| id(factor)).collect(),
            maximum_candidates: u32::try_from(rows.len()).expect("small arithmetic fixture"),
            selection_grammar_digest: digest("grammar"),
        },
    )
    .expect("arithmetic fixture retains the real sealed owner source");
    let pricing_policy_digest = digest("pricing-policy");
    let priced_rows = enumerated
        .candidates
        .iter()
        .map(|binding| {
            let (_, _, tokens, utility) = rows
                .iter()
                .find(|(factor, _, _, _)| id(factor) == binding.factor_id)
                .expect("fixture price");
            assert_eq!(*tokens, binding.realization.token_cost);
            let mut pricing = PromptPricingReceiptV1 {
                factor_id: binding.factor_id.clone(),
                state_digest: enumerated.receipt.state_digest,
                expected_utility_q32: FixedQ32::from_raw(*utility),
                downside_q32: FixedQ32::ZERO,
                token_cost: *tokens,
                latency_cost_micros: 0,
                interference_ppm: 0,
                confidence_interval: PromptConfidenceIntervalV1 {
                    lower_q32: FixedQ32::from_raw(*utility),
                    upper_q32: FixedQ32::from_raw(*utility),
                    support_count: 10,
                    support_audit_digest: digest("support-audit"),
                },
                receipt_digest: Digest32::ZERO,
                authority: AuthorityPosture::DENY_ALL,
            };
            pricing.receipt_digest = digest_pricing_receipt(
                &pricing.factor_id,
                pricing.state_digest,
                pricing.expected_utility_q32,
                pricing.downside_q32,
                pricing.token_cost,
                pricing.latency_cost_micros,
                pricing.interference_ppm,
                &pricing.confidence_interval,
                pricing_policy_digest,
                binding.binding_digest,
            );
            PricedPromptCandidateV1 {
                binding: binding.clone(),
                net_utility_q32: pricing.expected_utility_q32,
                pricing,
            }
        })
        .collect::<Vec<_>>();
    let pricing_set_digest = digest_pricing_set(&priced_rows, pricing_policy_digest);
    PricedPromptCandidatesV1 {
        candidates: enumerated,
        completeness_digest: digest("completeness"),
        pricing_policy_digest,
        rows: priced_rows,
        pricing_set_digest,
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn support(label: &str) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(&format!("support:{label}")),
        source_revision: Revision::new(1).unwrap_or_else(|error| panic!("revision: {error}")),
        source_fact_digest: digest(&format!("fact:{label}")),
        validity_digest: digest(&format!("validity:{label}")),
        valid_from_unix_seconds: None,
        valid_to_unix_seconds: None,
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
        Generation::new(1).unwrap_or_else(|error| panic!("generation: {error}")),
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
    .unwrap_or_else(|error| panic!("select bundle: {error}"));

    assert_eq!(
        selected.receipt.factor_ids,
        vec![id("factor:a"), id("factor:b")]
    );
    assert_eq!(
        selected.receipt.expected_utility_q32,
        FixedQ32::from_raw(99)
    );
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
    .unwrap_or_else(|error| panic!("select conflict: {error}"));
    assert_eq!(selected.receipt.factor_ids, vec![id("factor:a")]);
}

#[test]
fn candidate_missing_from_complete_interaction_graph_cannot_be_selected() {
    let priced = priced(vec![("factor:a", "realization:a", 1, 100)]);
    let request = PromptPortfolioRequestV1 {
        portfolio_id: id("portfolio:graph-coverage"),
        graph_query_id: id("query:graph-coverage"),
        token_budget: 1,
        maximum_selected_factors: 1,
        requested_valid_until_unix_ms: 5_000,
    };
    let absent = graph(&["factor:b"], Vec::new());
    assert_eq!(
        select_portfolio_v1(
            &priced,
            &absent,
            Vec::new(),
            &verifier(),
            request.clone(),
            100
        ),
        Err(CanonicalPromptError::KnowledgeGraph(
            "candidate factor missing from complete graph: factor:a".to_owned()
        ))
    );
    let represented = graph(&["factor:a"], Vec::new());
    let selected =
        select_portfolio_v1(&priced, &represented, Vec::new(), &verifier(), request, 100)
            .expect("represented factor without relations remains eligible");
    assert_eq!(selected.receipt.factor_ids, vec![id("factor:a")]);
    assert_eq!(
        selected.registry_digest,
        priced.candidates.registry_snapshot.registry_digest
    );
    assert_eq!(
        selected.receipt.receipt_digest,
        selected.compute_receipt_digest()
    );
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

#[test]
fn enumeration_selects_lowest_cost_compatible_realization_per_factor() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, _tuple, _authority, _signing_key, _now) =
        registry_fixture(&temp.path().join("registry"), &[50, 5]);

    let enumerated = enumerate_factors_v1(
        registry.registry().expect("registry"),
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
        id("realization:1")
    );
    assert!(!enumerated.receipt.authority.grants_any());
}

fn selected_portfolio(
    registry: &DurablePromptRegistry,
    factor_ids: Vec<StableId>,
) -> SelectedPromptPortfolioV1 {
    let snapshot = registry
        .snapshot_v2(digest("generation-vector"), &model_tuple())
        .expect("snapshot");
    let realizations = registry
        .read_compatible_v2(
            &snapshot,
            digest("generation-vector"),
            &model_tuple(),
            100,
            factor_ids.clone(),
            8,
        )
        .expect("bindings")
        .bindings;
    let bindings = factor_ids
        .iter()
        .map(|factor_id| {
            let realization = realizations
                .iter()
                .find(|binding| &binding.factor_id == factor_id)
                .expect("selected realization")
                .clone();
            PromptCandidateBindingV1 {
                factor_id: factor_id.clone(),
                binding_digest: realization.digest(),
                realization,
            }
        })
        .collect::<Vec<_>>();
    let mut selected = SelectedPromptPortfolioV1 {
        receipt: PromptPortfolioReceiptV1 {
            portfolio_id: id("portfolio:1"),
            candidate_set_digest: digest("candidate-set"),
            factor_ids,
            interaction_digest: digest("interaction"),
            expected_utility_q32: FixedQ32::from_raw(10),
            total_token_upper_bound: bindings
                .iter()
                .map(|binding| binding.realization.token_cost)
                .sum(),
            valid_until_unix_ms: 5_000,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        },
        selected: bindings,
        registry_digest: snapshot.registry_digest,
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
    selected.receipt.receipt_digest = selected.compute_receipt_digest();
    selected
}

fn exercise_request_for(portfolio: &SelectedPromptPortfolioV1) -> PromptExerciseRequestV1 {
    PromptExerciseRequestV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: portfolio.state_digest,
        generation_vector_digest: portfolio.generation_vector_digest,
        model_tuple: portfolio.model_tuple.clone(),
        now_unix_ms: 200,
        wait_value_q32: FixedQ32::ZERO,
        policy_digest: digest("exercise-policy"),
    }
}

#[test]
fn exercise_rejects_selected_factor_substitution_even_with_recomputed_checksum() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, _tuple, authority, signing_key, now) =
        registry_fixture(&temp.path().join("registry"), &[1]);
    register_second_factor(&mut registry, &authority, &signing_key, now);
    let original = selected_portfolio(&registry, vec![id("factor:a")]);
    let replacement = selected_portfolio(&registry, vec![id("factor:b")]);
    let request = exercise_request_for(&original);
    // Both independent selections are currently live under the same owner.
    for portfolio in [&original, &replacement] {
        assert_eq!(
            exercise_v1(
                registry.registry().expect("registry"),
                portfolio,
                request.clone()
            )
            .expect("live selection")
            .decision,
            PromptExerciseActionV1::Exercise
        );
    }
    let mut substituted = original.clone();
    substituted.selected = replacement.selected;
    assert_eq!(substituted.receipt.factor_ids, vec![id("factor:a")]);
    assert_eq!(
        exercise_v1(
            registry.registry().expect("registry"),
            &substituted,
            request.clone()
        )
        .expect("substitution rejection")
        .decision,
        PromptExerciseActionV1::RejectStale
    );
    // A checksum cannot make the mismatched factor receipt structurally valid.
    substituted.receipt.receipt_digest = substituted.compute_receipt_digest();
    assert_eq!(
        exercise_v1(
            registry.registry().expect("registry"),
            &substituted,
            request.clone()
        )
        .expect("recomputed substitution rejection")
        .decision,
        PromptExerciseActionV1::RejectStale
    );
    let mut duplicated = original;
    duplicated.selected.push(duplicated.selected[0].clone());
    duplicated.receipt.factor_ids.push(id("factor:a"));
    duplicated.receipt.total_token_upper_bound *= 2;
    duplicated.receipt.receipt_digest = duplicated.compute_receipt_digest();
    assert_eq!(
        exercise_v1(registry.registry().expect("registry"), &duplicated, request)
            .expect("duplicate factor rejection")
            .decision,
        PromptExerciseActionV1::RejectStale
    );
}

#[test]
fn exercise_binds_realization_objective_state_and_source_vector_to_the_receipt() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, _tuple, _authority, _signing_key, _now) =
        registry_fixture(&temp.path().join("registry"), &[1, 1]);
    let original = selected_portfolio(&registry, vec![id("factor:a")]);
    let request = exercise_request_for(&original);
    let snapshot = registry
        .snapshot_v2(original.generation_vector_digest, &original.model_tuple)
        .expect("snapshot");
    let alternate = registry
        .read_compatible_v2(
            &snapshot,
            original.generation_vector_digest,
            &original.model_tuple,
            /*now_unix_ms*/ 200,
            vec![id("factor:a")],
            /*maximum_results*/ 8,
        )
        .expect("both current realizations")
        .bindings
        .into_iter()
        .find(|binding| binding.realization_id != original.selected[0].realization.realization_id)
        .expect("alternate admitted realization");
    let mut realization_drift = original.clone();
    realization_drift.selected[0].binding_digest = alternate.digest();
    realization_drift.selected[0].realization = alternate;
    let mut objective_drift = original.clone();
    objective_drift.objective_digest = digest("new-objective");
    let mut state_drift = original.clone();
    state_drift.state_digest = digest("new-state");
    let mut state_request = request.clone();
    state_request.current_state_digest = state_drift.state_digest;
    let mut vector_drift = original;
    vector_drift.generation_vector_digest = digest("new-generation-vector");
    let mut vector_request = request.clone();
    vector_request.generation_vector_digest = vector_drift.generation_vector_digest;
    for (portfolio, request) in [
        (realization_drift, request.clone()),
        (objective_drift, request),
        (state_drift, state_request),
        (vector_drift, vector_request),
    ] {
        assert_eq!(
            exercise_v1(registry.registry().expect("registry"), &portfolio, request)
                .expect("proposal drift rejection")
                .decision,
            PromptExerciseActionV1::RejectStale
        );
    }
}

#[test]
fn empty_portfolio_preserves_no_intervention_with_legacy_receipt_metadata() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, _tuple, _authority, _signing_key, _now) =
        registry_fixture(&temp.path().join("registry"), &[1]);
    let mut portfolio = selected_portfolio(&registry, vec![id("factor:a")]);
    let request = exercise_request_for(&portfolio);
    portfolio.selected.clear();
    portfolio.state_digest = Digest32::ZERO;
    assert_eq!(
        exercise_v1(registry.registry().expect("registry"), &portfolio, request)
            .expect("no intervention")
            .decision,
        PromptExerciseActionV1::NoIntervention
    );
}

#[test]
fn revocation_after_selection_rejects_exercise_at_delivery_boundary() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, _tuple, authority, signing_key, now) =
        registry_fixture(&temp.path().join("registry"), &[1, 2]);
    let selected = selected_portfolio(&registry, vec![id("factor:a")]);
    let live = exercise_v1(
        registry.registry().expect("registry"),
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
    .expect("selected realization remains live among alternatives");
    assert_eq!(live.decision, PromptExerciseActionV1::Exercise);
    revoke_registry(&mut registry, &authority, &signing_key, now);
    let exercise = exercise_v1(
        registry.registry().expect("registry"),
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

fn register_second_factor(
    registry: &mut DurablePromptRegistry,
    authority: &FinalUseAuthority,
    signing_key: &SigningKey,
    now: u64,
) {
    let factor = PromptFactor {
        factor_id: id("factor:b"),
        proposer_id: id("proposer:2"),
        semantic_version: id("v1"),
        semantic_purpose: "second governed factor for relation evidence".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:truth")],
        content_digest: digest("factor:b"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    registry
        .register_factor(factor.clone())
        .expect("second factor");
    let scope = digest("scope:prompt:second-factor");
    let evidence = digest("evidence:prompt:second-factor");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "admission:prompt:2".to_owned(),
        nonce: [72; 32],
        binding: final_use_admission_binding(&factor, &id("reviewer:2"), scope, evidence)
            .expect("second factor binding"),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: signing_key
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    registry
        .admit_factor_final_use(authority, &signed, &factor.factor_id, scope, evidence)
        .expect("admit second factor");
    let admitted_factor = registry
        .registry()
        .expect("registry")
        .factor(&factor.factor_id)
        .expect("admitted second factor");
    let tuple = model_tuple();
    let realization = PromptRealizationBindingV2 {
        realization_id: id("realization:second-factor"),
        factor_id: factor.factor_id.clone(),
        model_id: tuple.model_id.clone(),
        model_version: tuple.model_version.clone(),
        model_digest: tuple.model_digest,
        tokenizer_digest: tuple.tokenizer_digest,
        template_digest: tuple.template_digest,
        tool_schema_digest: tuple.tool_schema_digest,
        context_profile_digest: tuple.context_profile_digest,
        locale_id: tuple.locale_id,
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: digest("second factor payload"),
        token_cost: 1,
        expires_unix_ms: None,
    };
    let publisher = id("publisher:prompt");
    let scope = digest("scope:second-realization");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "realization:prompt:second-factor".to_owned(),
        nonce: [73; 32],
        binding: final_use_realization_binding(
            admitted_factor,
            &publisher,
            scope,
            &realization,
            None,
        )
        .expect("second realization binding"),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: signing_key
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    registry
        .register_realization_payload_final_use_v2(
            authority,
            &signed,
            &publisher,
            scope,
            realization,
            b"second factor payload".to_vec(),
            None,
        )
        .expect("second realization");
}

#[test]
fn relation_only_source_drift_rejects_co_selected_unchanged_realizations() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, _tuple, authority, signing_key, now) =
        registry_fixture(&temp.path().join("registry"), &[1]);
    register_second_factor(&mut registry, &authority, &signing_key, now);
    let selected = selected_portfolio(&registry, vec![id("factor:a"), id("factor:b")]);
    assert_eq!(
        selected.receipt.factor_ids,
        vec![id("factor:a"), id("factor:b")]
    );
    let request = PromptExerciseRequestV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: digest("state"),
        generation_vector_digest: digest("generation-vector"),
        model_tuple: model_tuple(),
        now_unix_ms: 200,
        wait_value_q32: FixedQ32::ZERO,
        policy_digest: digest("exercise-policy"),
    };
    assert_eq!(
        exercise_v1(
            registry.registry().expect("registry"),
            &selected,
            request.clone()
        )
        .expect("live exercise")
        .decision,
        PromptExerciseActionV1::Exercise
    );
    registry
        .register_factor_relation(PromptFactorRelation {
            relation_id: id("relation:a:b:conflict"),
            left_factor_id: id("factor:a"),
            right_factor_id: id("factor:b"),
            kind: PromptFactorRelationKind::Conflicts,
            evidence_digest: digest("relation evidence"),
        })
        .expect("persist conflict evidence");
    let snapshot = registry
        .snapshot_v2(request.generation_vector_digest, &request.model_tuple)
        .expect("current snapshot");
    assert_ne!(snapshot.registry_digest, selected.registry_digest);
    assert_eq!(
        registry
            .read_compatible_v2(
                &snapshot,
                request.generation_vector_digest,
                &request.model_tuple,
                request.now_unix_ms,
                selected.receipt.factor_ids.clone(),
                2
            )
            .expect("unchanged compatible bindings")
            .bindings,
        selected
            .selected
            .iter()
            .map(|binding| binding.realization.clone())
            .collect::<Vec<_>>()
    );
    let rejected = exercise_v1(
        registry.registry().expect("registry"),
        &selected,
        request.clone(),
    )
    .expect("source drift decision");
    assert_eq!(rejected.decision, PromptExerciseActionV1::RejectStale);
    assert!(!rejected.authority.grants_any());

    // Replacing the frozen source field cannot reuse the previous checksum.
    let mut replaced = selected;
    replaced.registry_digest = snapshot.registry_digest;
    assert_ne!(
        replaced.receipt.receipt_digest,
        replaced.compute_receipt_digest()
    );
    assert_eq!(
        exercise_v1(registry.registry().expect("registry"), &replaced, request)
            .expect("checksum drift decision")
            .decision,
        PromptExerciseActionV1::RejectStale
    );
}

fn registry_fixture(
    root: &std::path::Path,
    costs: &[u32],
) -> (
    DurablePromptRegistry,
    PromptModelTupleV2,
    FinalUseAuthority,
    SigningKey,
    u64,
) {
    let payload = b"payload";
    let mut registry =
        DurablePromptRegistry::open_state_dir(root, 64).expect("open durable registry");
    let factor = PromptFactor {
        factor_id: id("factor:a"),
        proposer_id: id("proposer:1"),
        semantic_version: id("v1"),
        semantic_purpose: "inspect evidence before mutation".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:truth")],
        content_digest: digest("factor:a"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    registry
        .register_factor(factor.clone())
        .expect("register factor");

    let signing_key = SigningKey::from_bytes(&[23; 32]);
    let authority_root = root
        .parent()
        .expect("registry root parent")
        .join("prompt-admission-authority");
    let authority = FinalUseAuthority::open_state_dir(
        &authority_root,
        "review-authority:prompt".to_owned(),
        signing_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("final-use authority");
    let reviewer = id("reviewer:1");
    let scope = digest("scope:prompt");
    let evidence = digest("evidence:prompt");
    let binding = final_use_admission_binding(&factor, &reviewer, scope, evidence)
        .expect("final-use admission binding");
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "admission:prompt:1".to_owned(),
        nonce: [23; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: signing_key
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    registry
        .admit_factor_final_use(&authority, &signed, &factor.factor_id, scope, evidence)
        .expect("admit factor through final-use authority");
    let admitted_factor = registry
        .registry()
        .expect("registry remains readable after admission")
        .factor(&factor.factor_id)
        .cloned()
        .expect("admitted factor remains present");

    let tuple = model_tuple();
    // A registry profile admits only one active realization. Distinct roles
    // provide legal alternatives for the optimizer without weakening that rule.
    let roles = [
        PromptRoleV2::DeveloperInstruction,
        PromptRoleV2::SystemInstruction,
    ];
    assert!(costs.len() <= roles.len());
    for (index, cost) in costs.iter().enumerate() {
        let realization = PromptRealizationBindingV2 {
            realization_id: id(&format!("realization:{index}")),
            factor_id: factor.factor_id.clone(),
            model_id: tuple.model_id.clone(),
            model_version: tuple.model_version.clone(),
            model_digest: tuple.model_digest,
            tokenizer_digest: tuple.tokenizer_digest,
            template_digest: tuple.template_digest,
            tool_schema_digest: tuple.tool_schema_digest,
            context_profile_digest: tuple.context_profile_digest,
            locale_id: tuple.locale_id.clone(),
            role: roles[index],
            payload_digest: Digest32::of_bytes(payload),
            token_cost: *cost,
            expires_unix_ms: None,
        };
        let realization_actor = id("publisher:prompt");
        let realization_scope = digest("scope:realization:prompt");
        let authority_binding = final_use_realization_binding(
            &admitted_factor,
            &realization_actor,
            realization_scope,
            &realization,
            None,
        )
        .expect("realization authority binding");
        let realization_grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "review-authority:prompt".to_owned(),
            authority_epoch: 1,
            grant_id: format!("realization:prompt:{index}"),
            nonce: [u8::try_from(index + 24).expect("small fixture"); 32],
            binding: authority_binding,
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 30_000,
        };
        let realization_signed = SignedFinalUseGrant {
            signature: signing_key
                .sign(
                    &realization_grant
                        .signing_bytes()
                        .expect("realization signing bytes"),
                )
                .to_bytes()
                .to_vec(),
            grant: realization_grant,
        };
        registry
            .register_realization_payload_final_use_v2(
                &authority,
                &realization_signed,
                &realization_actor,
                realization_scope,
                realization,
                payload.to_vec(),
                None,
            )
            .expect("register actual payload through final-use authority");
    }
    (registry, tuple, authority, signing_key, now)
}

fn revoke_registry(
    registry: &mut DurablePromptRegistry,
    authority: &FinalUseAuthority,
    signing_key: &SigningKey,
    grant_now: u64,
) {
    let factor = registry
        .registry()
        .expect("registry")
        .factor(&id("factor:a"))
        .cloned()
        .expect("admitted factor");
    let actor = id("revoker:test");
    let revoke_scope = digest("scope:revoke:test");
    let reason = digest("reason:revoke");
    let cutoff = grant_now + 5_000;
    let revoke_binding = final_use_revoke_binding(&factor, &actor, revoke_scope, reason, cutoff)
        .expect("revoke binding");
    let revoke_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "revoke:prompt:1".to_owned(),
        nonce: [250; 32],
        binding: revoke_binding,
        not_before_unix_ms: grant_now.saturating_sub(1_000),
        expires_at_unix_ms: grant_now + 30_000,
    };
    let revoke_signed = SignedFinalUseGrant {
        signature: signing_key
            .sign(&revoke_grant.signing_bytes().expect("revoke signing bytes"))
            .to_bytes()
            .to_vec(),
        grant: revoke_grant,
    };
    registry
        .revoke_factor_final_use(
            authority,
            &revoke_signed,
            &factor.factor_id,
            &actor,
            revoke_scope,
            reason,
            cutoff,
        )
        .expect("final-use revocation");
}

#[path = "canonical_temporal_tests.rs"]
mod temporal;

#[path = "canonical_source_tests.rs"]
mod source;

#[path = "canonical_candidate_source_tests.rs"]
mod candidate_source;
