use super::*;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_prompt_registry::final_use_realization_binding;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_id: id("model:verified"),
        model_version: "2026-09-28".to_owned(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        context_profile_digest: digest("context"),
        locale_id: id("locale:en-US"),
    }
}

struct Fixture {
    _temporary: tempfile::TempDir,
    registry: DurablePromptRegistry,
    graph: codex_hepta_kg::KnowledgeGenerationV2,
    verifier: codex_hepta_learning_ledger::LearningEvidenceVerifierV1,
    generator_key: SigningKey,
    evaluator_key: SigningKey,
    model_tuple: PromptModelTupleV2,
    now: u64,
}

fn fixture(same_controller: bool, verifier_objective: Digest32) -> Fixture {
    let temporary = tempfile::tempdir().expect("tempdir");
    let registry_root = temporary.path().join("registry");
    let authority_root = temporary.path().join("authority");
    let mut registry = DurablePromptRegistry::open_state_dir(&registry_root, 64)
        .expect("durable prompt registry");
    let factor = PromptFactor {
        factor_id: id("factor:verified"),
        proposer_id: id("proposer:verified"),
        semantic_version: id("semantic:v1"),
        semantic_purpose: "inspect evidence before mutation".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:truth")],
        content_digest: digest("factor-content"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    registry
        .register_factor(factor.clone())
        .expect("register factor");

    let admission_key = SigningKey::from_bytes(&[23; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &authority_root,
        "authority:prompt-verified".to_owned(),
        admission_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let actor = id("reviewer:verified");
    let scope = digest("registry-scope");
    let evidence = digest("registry-evidence");
    let binding = final_use_admission_binding(&factor, &actor, scope, evidence)
        .expect("admission binding");
    let admission_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "authority:prompt-verified".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:prompt-admission".to_owned(),
        nonce: [31; 32],
        binding,
        not_before_unix_ms: 1,
        expires_at_unix_ms: 10_000,
    };
    let admission_signed = SignedFinalUseGrant {
        signature: admission_key
            .sign(&admission_grant.signing_bytes().expect("admission bytes"))
            .to_bytes()
            .to_vec(),
        grant: admission_grant,
    };
    registry
        .admit_factor_final_use(
            &authority,
            &admission_signed,
            &factor.factor_id,
            scope,
            evidence,
        )
        .expect("admit factor");
    let admitted_factor = registry
        .registry()
        .expect("registry")
        .factor(&factor.factor_id)
        .cloned()
        .expect("admitted factor");

    let model_tuple = tuple();
    let payload = b"Inspect evidence before mutation.".to_vec();
    let realization = PromptRealizationBindingV2 {
        realization_id: id("realization:verified"),
        factor_id: factor.factor_id.clone(),
        model_id: model_tuple.model_id.clone(),
        model_version: model_tuple.model_version.clone(),
        model_digest: model_tuple.model_digest,
        tokenizer_digest: model_tuple.tokenizer_digest,
        template_digest: model_tuple.template_digest,
        tool_schema_digest: model_tuple.tool_schema_digest,
        context_profile_digest: model_tuple.context_profile_digest,
        locale_id: model_tuple.locale_id.clone(),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: Digest32::of_bytes(&payload),
        token_cost: 4,
        expires_unix_ms: Some(5_000),
    };
    let publisher = id("publisher:verified");
    let realization_scope = digest("realization-scope");
    let realization_binding = final_use_realization_binding(
        &admitted_factor,
        &publisher,
        realization_scope,
        &realization,
        None,
    )
    .expect("realization binding");
    let realization_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "authority:prompt-verified".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:realization".to_owned(),
        nonce: [32; 32],
        binding: realization_binding,
        not_before_unix_ms: 1,
        expires_at_unix_ms: 10_000,
    };
    let realization_signed = SignedFinalUseGrant {
        signature: admission_key
            .sign(
                &realization_grant
                    .signing_bytes()
                    .expect("realization bytes"),
            )
            .to_bytes()
            .to_vec(),
        grant: realization_grant,
    };
    registry
        .register_realization_payload_final_use_v2(
            &authority,
            &realization_signed,
            &publisher,
            realization_scope,
            realization,
            payload,
            None,
        )
        .expect("register realization");

    let support = KnowledgeSupportV2 {
        source_id: id("support:verified"),
        source_revision: Revision::new(1).expect("revision"),
        source_fact_digest: digest("source-fact"),
        validity_digest: digest("validity"),
        valid_from_unix_seconds: Some(0),
        valid_to_unix_seconds: Some(5),
        tombstoned: false,
    };
    let graph = build_complete_generation(
        Generation::new(1).expect("generation"),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: digest("graph-source"),
            generation_vector_digest: digest("generation-vector"),
            graph_profile_digest: digest("graph-profile"),
            complete_source_cut: true,
            nodes: vec![KnowledgeNodeV2 {
                node_id: factor.factor_id,
                node_kind_id: id("kind:prompt-factor"),
                payload_digest: digest("node-payload"),
                supports: vec![support],
            }],
            edges: Vec::new(),
        },
    )
    .expect("knowledge generation");

    let generator_key = SigningKey::from_bytes(&[41; 32]);
    let evaluator_key = SigningKey::from_bytes(&[42; 32]);
    let evidence_scope = digest("evidence-scope");
    let generator_controller = id("controller:generator");
    let evaluator_controller = if same_controller {
        generator_controller.clone()
    } else {
        id("controller:evaluator")
    };
    let verifier = codex_hepta_learning_ledger::LearningEvidenceVerifierV1::new(
        LearningEvidenceTrustV1 {
            scope_digest: evidence_scope,
            objective_digest: verifier_objective,
            authority_epoch: 1,
            signers: vec![
                TrustedLearningSignerV1 {
                    principal: principal(
                        "principal:generator",
                        &generator_key,
                        evidence_scope,
                    ),
                    controller_id: generator_controller,
                    verifying_key: generator_key.verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Generator],
                    revoked_at: None,
                },
                TrustedLearningSignerV1 {
                    principal: principal(
                        "principal:evaluator",
                        &evaluator_key,
                        evidence_scope,
                    ),
                    controller_id: evaluator_controller,
                    verifying_key: evaluator_key.verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Evaluator],
                    revoked_at: None,
                },
            ],
        },
    )
    .expect("learning verifier");

    Fixture {
        _temporary: temporary,
        registry,
        graph,
        verifier,
        generator_key,
        evaluator_key,
        model_tuple,
        now: 100,
    }
}

fn principal(
    principal_id: &str,
    key: &SigningKey,
    scope_digest: Digest32,
) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(principal_id),
        credential_chain_digest: digest(&format!("credential:{principal_id}")),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest,
        authority_epoch: 1,
        authenticated_at: 1,
        expires_at: 10_000,
    }
}

fn sign_evidence(
    verifier: &codex_hepta_learning_ledger::LearningEvidenceVerifierV1,
    key: &SigningKey,
    principal_id: &str,
    role: LearningEvidenceRoleV1,
    evidence_id: &str,
    payload: &[u8],
    expires_at: u64,
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(evidence_id),
        principal_id: id(principal_id),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at: 1,
        expires_at,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

fn enumerate(fixture: &Fixture) -> EnumeratedPromptCandidatesV1 {
    enumerate_factors_v1(
        fixture.registry.registry().expect("registry"),
        PromptEnumerationRequestV1 {
            set_id: id("set:verified"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            evidence_scope_digest: digest("evidence-scope"),
            generation_vector_digest: digest("generation-vector"),
            model_tuple: fixture.model_tuple.clone(),
            now_unix_ms: fixture.now,
            required_factor_ids: vec![id("factor:verified")],
            maximum_candidates: 8,
            selection_grammar_digest: digest("grammar"),
            generator_code_digest: digest("generator-code"),
            hard_filter_digest: digest("hard-filter"),
            truncation_digest: digest("truncation"),
        },
    )
    .expect("verified enumeration")
}

fn completeness(
    candidates: &EnumeratedPromptCandidatesV1,
) -> CandidateSetCompletenessReceiptV1 {
    CandidateSetCompletenessReceiptV1 {
        set_id: candidates.receipt.set_id.clone(),
        state_digest: candidates.receipt.state_digest,
        generator_id: id("prompt.optimizer"),
        generator_code_digest: digest("generator-code"),
        grammar_digest: candidates.receipt.selection_grammar_digest,
        hard_filter_digest: digest("hard-filter"),
        truncation_digest: digest("truncation"),
        candidates_digest: candidates.candidates_digest,
        candidate_count: u32::try_from(candidates.candidates.len()).expect("small fixture"),
        omitted_count_bound: candidates.omitted_count,
        canonical_order_digest: candidates.canonical_order_digest,
        complete_for_generator: true,
    }
}

fn policy() -> PromptPricingPolicyV1 {
    PromptPricingPolicyV1 {
        policy_id: id("pricing-policy:verified"),
        token_cost_per_token_q32: FixedQ32::ZERO,
        latency_cost_per_micro_q32: FixedQ32::ZERO,
        interference_cost_per_ppm_q32: FixedQ32::ZERO,
        downside_weight_q32: FixedQ32::ONE,
        minimum_support_count: 1,
        maximum_interference_ppm: 1_000_000,
    }
}

fn signed_inputs(
    fixture: &Fixture,
    candidates: &EnumeratedPromptCandidatesV1,
    pricing_expires_at: u64,
    realization_id: StableId,
) -> (
    CandidateSetCompletenessReceiptV1,
    SignedLearningEvidenceV1,
    PromptPricingEvidenceV1,
) {
    let completeness = completeness(candidates);
    let completeness_payload = super::raw::candidate_completeness_signing_payload_v1(&completeness)
        .expect("completeness payload");
    let completeness_evidence = sign_evidence(
        &fixture.verifier,
        &fixture.generator_key,
        "principal:generator",
        LearningEvidenceRoleV1::Generator,
        "evidence:completeness",
        &completeness_payload,
        4_000,
    );
    let binding = &candidates.candidates[0];
    let pricing_policy_digest = policy().digest().expect("pricing policy");
    let placeholder = sign_evidence(
        &fixture.verifier,
        &fixture.evaluator_key,
        "principal:evaluator",
        LearningEvidenceRoleV1::Evaluator,
        "evidence:placeholder",
        b"placeholder",
        pricing_expires_at,
    );
    let mut pricing = PromptPricingEvidenceV1 {
        factor_id: binding.factor_id.clone(),
        realization_id,
        objective_digest: candidates.receipt.objective_digest,
        evidence_scope_digest: candidates.evidence_scope_digest(),
        candidate_set_digest: candidates.candidates_digest,
        registry_snapshot_digest: candidates.registry_snapshot.snapshot_digest,
        generation_vector_digest: candidates.generation_vector_digest,
        model_tuple_digest: candidates.model_tuple.digest(),
        realization_binding_digest: binding.binding_digest,
        pricing_policy_digest,
        state_digest: candidates.receipt.state_digest,
        expected_incremental_utility_q32: FixedQ32::from_raw(100),
        downside_q32: FixedQ32::from_raw(1),
        confidence_lower_q32: FixedQ32::from_raw(90),
        confidence_upper_q32: FixedQ32::from_raw(110),
        support_count: 10,
        latency_cost_micros: 1,
        interference_ppm: 0,
        context_crowding_cost_q32: FixedQ32::ZERO,
        privacy_cost_q32: FixedQ32::ZERO,
        instability_cost_q32: FixedQ32::ZERO,
        future_context_option_cost_q32: FixedQ32::ZERO,
        support_audit_digest: digest("pricing-support"),
        evidence: placeholder,
    };
    let payload = pricing_evidence_signing_payload_v1(&pricing);
    pricing.evidence = sign_evidence(
        &fixture.verifier,
        &fixture.evaluator_key,
        "principal:evaluator",
        LearningEvidenceRoleV1::Evaluator,
        "evidence:pricing",
        &payload,
        pricing_expires_at,
    );
    (completeness, completeness_evidence, pricing)
}

fn priced(fixture: &Fixture) -> PricedPromptCandidatesV1 {
    let candidates = enumerate(fixture);
    let realization_id = candidates.candidates[0].realization.realization_id.clone();
    let (completeness, completeness_evidence, pricing) =
        signed_inputs(fixture, &candidates, 4_000, realization_id);
    price_factors_v1(
        candidates,
        &completeness,
        &completeness_evidence,
        vec![pricing],
        &fixture.verifier,
        &policy(),
        fixture.now,
    )
    .expect("verified pricing")
}

fn selected(fixture: &Fixture) -> SelectedPromptPortfolioV1 {
    let priced = priced(fixture);
    select_portfolio_v1(
        &priced,
        &fixture.graph,
        Vec::new(),
        &fixture.verifier,
        PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:verified"),
            graph_query_id: id("query:verified"),
            token_budget: 32,
            maximum_selected_factors: 4,
            requested_valid_until_unix_ms: 4_000,
            expected_graph_source_snapshot_digest: fixture.graph.source_snapshot_digest,
            expected_graph_profile_digest: fixture.graph.graph_profile_digest,
            exact_oracle_max_factors: 8,
            local_improvement_rounds: 8,
        },
        fixture.now,
    )
    .expect("verified selection")
}

fn exercise_request(fixture: &Fixture) -> PromptExerciseRequestV1 {
    PromptExerciseRequestV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: digest("state"),
        generation_vector_digest: digest("generation-vector"),
        model_tuple: fixture.model_tuple.clone(),
        now_unix_ms: 200,
        wait_value_q32: FixedQ32::ZERO,
        policy: PromptExercisePolicyV1::new(
            id("exercise-policy:verified"),
            digest("objective"),
            digest("evidence-scope"),
            vec![PromptDecisionBoundaryV1::BeforeModelOrToolDispatch],
            1,
            4_000,
        )
        .expect("exercise policy"),
        current_graph: fixture.graph.clone(),
        current_verifier: fixture.verifier.clone(),
    }
}

#[test]
fn sealed_canonical_pipeline_reaches_exercise_with_exact_certificate() {
    let fixture = fixture(false, digest("objective"));
    let portfolio = selected(&fixture);
    assert_eq!(
        portfolio.audit().optimality,
        PromptOptimalityAuditV1::ExactCertificate
    );
    assert_eq!(portfolio.receipt.factor_ids, vec![id("factor:verified")]);
    let decision = exercise_v1(
        fixture.registry.registry().expect("registry"),
        &portfolio,
        exercise_request(&fixture),
    )
    .expect("exercise");
    assert_eq!(decision.decision, PromptExerciseActionV1::Exercise);
    assert_eq!(decision.audit().rejection_reason, None);
    assert!(!decision.authority.grants_any());
}

#[test]
fn generator_and_evaluator_under_same_controller_are_rejected() {
    let fixture = fixture(true, digest("objective"));
    let candidates = enumerate(&fixture);
    let realization_id = candidates.candidates[0].realization.realization_id.clone();
    let (completeness, completeness_evidence, pricing) =
        signed_inputs(&fixture, &candidates, 4_000, realization_id);
    assert_eq!(
        price_factors_v1(
            candidates,
            &completeness,
            &completeness_evidence,
            vec![pricing],
            &fixture.verifier,
            &policy(),
            fixture.now,
        ),
        Err(CanonicalPromptError::EvidenceIndependence)
    );
}

#[test]
fn objective_mismatch_is_rejected_before_evidence_use() {
    let fixture = fixture(false, digest("different-objective"));
    let candidates = enumerate(&fixture);
    let realization_id = candidates.candidates[0].realization.realization_id.clone();
    let (completeness, completeness_evidence, pricing) =
        signed_inputs(&fixture, &candidates, 4_000, realization_id);
    assert_eq!(
        price_factors_v1(
            candidates,
            &completeness,
            &completeness_evidence,
            vec![pricing],
            &fixture.verifier,
            &policy(),
            fixture.now,
        ),
        Err(CanonicalPromptError::EvidenceContextMismatch)
    );
}

#[test]
fn pricing_evidence_cannot_rebind_to_another_realization() {
    let fixture = fixture(false, digest("objective"));
    let candidates = enumerate(&fixture);
    let (completeness, completeness_evidence, pricing) = signed_inputs(
        &fixture,
        &candidates,
        4_000,
        id("realization:forged"),
    );
    assert!(matches!(
        price_factors_v1(
            candidates,
            &completeness,
            &completeness_evidence,
            vec![pricing],
            &fixture.verifier,
            &policy(),
            fixture.now,
        ),
        Err(CanonicalPromptError::InvalidPricingEvidence(_))
    ));
}

#[test]
fn expired_pricing_is_unavailable_not_zero_cost_benefit() {
    let fixture = fixture(false, digest("objective"));
    let candidates = enumerate(&fixture);
    let realization_id = candidates.candidates[0].realization.realization_id.clone();
    let (completeness, completeness_evidence, pricing) =
        signed_inputs(&fixture, &candidates, fixture.now - 1, realization_id);
    let priced = price_factors_v1(
        candidates,
        &completeness,
        &completeness_evidence,
        vec![pricing],
        &fixture.verifier,
        &policy(),
        fixture.now,
    )
    .expect("expired pricing is represented explicitly");
    assert!(priced.rows.is_empty());
    assert_eq!(
        priced.unavailable(),
        &[PromptUnavailablePricingV1 {
            factor_id: id("factor:verified"),
            reason: PromptPricingUnavailableReasonV1::EvidenceExpired,
        }]
    );
}

#[test]
fn pricing_receipt_utility_tamper_is_detected_by_type_state() {
    let fixture = fixture(false, digest("objective"));
    let mut priced = priced(&fixture);
    priced.inner.rows[0].pricing.expected_utility_q32 = FixedQ32::from_raw(9_999);
    assert_eq!(
        priced.verify_internal(),
        Err(CanonicalPromptError::CandidateIntegrity("pricing row"))
    );
}

#[test]
fn candidate_order_and_binding_tamper_are_detected() {
    let fixture = fixture(false, digest("objective"));
    let mut candidates = enumerate(&fixture);
    candidates.inner.candidates[0].factor_id = id("factor:forged");
    assert_eq!(
        candidates.verify_internal(),
        Err(CanonicalPromptError::CandidateIntegrity("candidate binding"))
    );
}

#[test]
fn exercise_rejects_graph_and_trust_drift_with_typed_reasons() {
    let fixture = fixture(false, digest("objective"));
    let portfolio = selected(&fixture);

    let mut graph_request = exercise_request(&fixture);
    graph_request.current_graph.graph_profile_digest = digest("drifted-graph-profile");
    let graph_decision = exercise_v1(
        fixture.registry.registry().expect("registry"),
        &portfolio,
        graph_request,
    )
    .expect("graph drift decision");
    assert_eq!(graph_decision.decision, PromptExerciseActionV1::RejectStale);
    assert_eq!(
        graph_decision.audit().rejection_reason,
        Some(PromptExerciseRejectionReasonV1::GraphDrift)
    );

    let rotated = fixture(false, digest("objective"));
    let mut trust_request = exercise_request(&fixture);
    trust_request.current_verifier = rotated.verifier;
    let trust_decision = exercise_v1(
        fixture.registry.registry().expect("registry"),
        &portfolio,
        trust_request,
    )
    .expect("trust drift decision");
    assert_eq!(trust_decision.decision, PromptExerciseActionV1::RejectStale);
    assert_eq!(
        trust_decision.audit().rejection_reason,
        Some(PromptExerciseRejectionReasonV1::TrustDrift)
    );
}

#[test]
fn policy_context_mismatch_cannot_be_hidden_behind_a_digest() {
    let fixture = fixture(false, digest("objective"));
    let portfolio = selected(&fixture);
    let mut request = exercise_request(&fixture);
    request.policy = PromptExercisePolicyV1::new(
        id("exercise-policy:wrong-objective"),
        digest("different-objective"),
        digest("evidence-scope"),
        vec![PromptDecisionBoundaryV1::BeforeModelOrToolDispatch],
        1,
        4_000,
    )
    .expect("well-formed but wrong policy");
    let decision = exercise_v1(
        fixture.registry.registry().expect("registry"),
        &portfolio,
        request,
    )
    .expect("typed rejection");
    assert_eq!(decision.decision, PromptExerciseActionV1::RejectStale);
    assert_eq!(
        decision.audit().rejection_reason,
        Some(PromptExerciseRejectionReasonV1::TrustDrift)
    );
}
