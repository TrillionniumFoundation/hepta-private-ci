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

fn binding(factor: &str, realization: &str, tokens: u32) -> PromptRealizationBindingV2 {
    let tuple = model_tuple();
    PromptRealizationBindingV2 {
        realization_id: id(realization),
        factor_id: id(factor),
        model_id: tuple.model_id,
        model_version: tuple.model_version,
        model_digest: tuple.model_digest,
        tokenizer_digest: tuple.tokenizer_digest,
        template_digest: tuple.template_digest,
        tool_schema_digest: tuple.tool_schema_digest,
        context_profile_digest: tuple.context_profile_digest,
        locale_id: tuple.locale_id,
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: digest(&format!("payload:{realization}")),
        token_cost: tokens,
        expires_unix_ms: Some(10_000),
    }
}

fn candidate(factor: &str, realization: &str, tokens: u32) -> PromptCandidateBindingV1 {
    let realization = binding(factor, realization, tokens);
    PromptCandidateBindingV1 {
        factor_id: realization.factor_id.clone(),
        binding_digest: realization.digest(),
        realization,
    }
}

fn dummy_snapshot(
    tuple: &PromptModelTupleV2,
    generation_vector: Digest32,
) -> PromptRegistrySnapshotV2 {
    PromptRegistrySnapshotV2 {
        revision: Revision::new(1).unwrap_or_else(|error| panic!("revision: {error}")),
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
        .map(
            |((factor, _, tokens, utility), binding)| PricedPromptCandidateV1 {
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
            },
        )
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
        source_revision: Revision::new(1).unwrap_or_else(|error| panic!("revision: {error}")),
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

#[test]
fn revocation_after_selection_rejects_exercise_at_delivery_boundary() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, _tuple, authority, signing_key, now) =
        registry_fixture(&temp.path().join("registry"), &[1, 2]);
    let snapshot = registry
        .snapshot_v2(digest("generation-vector"), &model_tuple())
        .expect("snapshot");
    let realization = registry
        .read_compatible_v2(
            &snapshot,
            digest("generation-vector"),
            &model_tuple(),
            100,
            vec![id("factor:a")],
            8,
        )
        .expect("bindings")
        .bindings[0]
        .clone();
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
