use super::*;

use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_prompt_optimizer::canonical::KnowledgeNodeV2;
use codex_hepta_prompt_optimizer::canonical::KnowledgeProjectionInputV2;
use codex_hepta_prompt_optimizer::canonical::KnowledgeSupportV2;
use codex_hepta_prompt_optimizer::canonical::PromptDecisionBoundaryV1;
use codex_hepta_prompt_optimizer::canonical::PromptExercisePolicyV1;
use codex_hepta_prompt_optimizer::canonical::build_complete_generation;
use codex_hepta_prompt_optimizer::canonical::candidate_completeness_signing_payload_v1;
use codex_hepta_prompt_optimizer::canonical::pricing_evidence_signing_payload_v1;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_prompt_registry::final_use_realization_binding;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn model_tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_id: id("model:agentd-product"),
        model_version: "2026-09-26".to_owned(),
        model_digest: digest("model:agentd-product"),
        tokenizer_digest: digest("tokenizer:agentd-product"),
        template_digest: digest("template:agentd-product"),
        tool_schema_digest: digest("tool-schema:agentd-product"),
        context_profile_digest: digest("context-profile:agentd-product"),
        locale_id: id("locale:en-US"),
    }
}

fn trusted_signer(
    principal_id: &str,
    controller_id: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
    scope_digest: Digest32,
) -> TrustedLearningSignerV1 {
    let key = SigningKey::from_bytes(&[seed; 32]);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(principal_id),
            credential_chain_digest: digest(&format!("credential:{principal_id}")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest,
            authority_epoch: 7,
            authenticated_at: 1,
            expires_at: 10_000,
        },
        controller_id: id(controller_id),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
}

fn sign_evidence(
    verifier: &LearningEvidenceVerifierV1,
    principal_id: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!(
            "evidence:{principal_id}:{}",
            Digest32::of_bytes(payload)
        )),
        principal_id: id(principal_id),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at: 10,
        expires_at: 5_000,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

fn install_prompt_registry(
    registry_root: &std::path::Path,
    authority_root: &std::path::Path,
    tuple: &PromptModelTupleV2,
    factor: &PromptFactor,
    realization: &PromptRealizationBindingV2,
    payload: &[u8],
) {
    let mut registry = DurablePromptRegistry::open_state_dir(registry_root, 64)
        .unwrap_or_else(|error| panic!("registry: {error}"));
    registry
        .register_factor(factor.clone())
        .unwrap_or_else(|error| panic!("register factor: {error}"));

    let signing_key = SigningKey::from_bytes(&[61; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        authority_root,
        "review-authority:agentd-prompt".to_owned(),
        signing_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .unwrap_or_else(|error| panic!("authority: {error}"));
    let wall_now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|error| panic!("clock: {error}"))
        .as_millis() as u64;
    let reviewer = id("reviewer:agentd-prompt");
    let admission_scope = digest("scope:agentd-prompt-admission");
    let admission_evidence = digest("evidence:agentd-prompt");
    let admission_binding =
        final_use_admission_binding(factor, &reviewer, admission_scope, admission_evidence)
            .unwrap_or_else(|error| panic!("admission binding: {error}"));
    let admission_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:agentd-prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:agentd-prompt-admission".to_owned(),
        nonce: [62; 32],
        binding: admission_binding,
        not_before_unix_ms: wall_now.saturating_sub(1_000),
        expires_at_unix_ms: wall_now + 30_000,
    };
    let signed_admission = SignedFinalUseGrant {
        signature: signing_key
            .sign(
                &admission_grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("admission signing bytes: {error}")),
            )
            .to_bytes()
            .to_vec(),
        grant: admission_grant,
    };
    registry
        .admit_factor_final_use(
            &authority,
            &signed_admission,
            &factor.factor_id,
            admission_scope,
            admission_evidence,
        )
        .unwrap_or_else(|error| panic!("admit factor: {error}"));
    let admitted = registry
        .registry()
        .unwrap_or_else(|error| panic!("registry read: {error}"))
        .factor(&factor.factor_id)
        .cloned()
        .unwrap_or_else(|| panic!("admitted factor missing"));
    let publisher = id("publisher:agentd-prompt");
    let realization_scope = digest("scope:agentd-prompt-realization");
    let realization_binding = final_use_realization_binding(
        &admitted,
        &publisher,
        realization_scope,
        realization,
        None,
    )
    .unwrap_or_else(|error| panic!("realization binding: {error}"));
    let realization_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:agentd-prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:agentd-prompt-realization".to_owned(),
        nonce: [63; 32],
        binding: realization_binding,
        not_before_unix_ms: wall_now.saturating_sub(1_000),
        expires_at_unix_ms: wall_now + 30_000,
    };
    let signed_realization = SignedFinalUseGrant {
        signature: signing_key
            .sign(
                &realization_grant
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("realization signing bytes: {error}")),
            )
            .to_bytes()
            .to_vec(),
        grant: realization_grant,
    };
    registry
        .register_realization_payload_final_use_v2(
            &authority,
            &signed_realization,
            &publisher,
            realization_scope,
            realization.clone(),
            payload.to_vec(),
            None,
        )
        .unwrap_or_else(|error| panic!("register realization: {error}"));
    assert_eq!(tuple.digest(), realization.model_tuple_digest());
}

#[test]
fn named_agentd_product_executes_sealed_optimizer_chain_and_stages_exact_bytes() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let registry_root = temporary.path().join("prompt-registry");
    let runtime_root = temporary.path().join("prompt-runtime");
    let authority_root = temporary.path().join("prompt-authority");
    let payload = b"Inspect evidence before mutation.";
    let tuple = model_tuple();
    let factor = PromptFactor {
        factor_id: id("factor:agentd-product"),
        proposer_id: id("proposer:agentd-product"),
        semantic_version: id("v1"),
        semantic_purpose: "inspect evidence before mutation".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:truth")],
        content_digest: digest("factor:agentd-product"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    let realization = PromptRealizationBindingV2 {
        realization_id: id("realization:agentd-product"),
        factor_id: factor.factor_id.clone(),
        model_id: tuple.model_id.clone(),
        model_version: tuple.model_version.clone(),
        model_digest: tuple.model_digest,
        tokenizer_digest: tuple.tokenizer_digest,
        template_digest: tuple.template_digest,
        tool_schema_digest: tuple.tool_schema_digest,
        context_profile_digest: tuple.context_profile_digest,
        locale_id: tuple.locale_id.clone(),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: Digest32::of_bytes(payload),
        token_cost: 4,
        expires_unix_ms: None,
    };
    install_prompt_registry(
        &registry_root,
        &authority_root,
        &tuple,
        &factor,
        &realization,
        payload,
    );

    let pipeline = AgentdPromptPipelineOwner::open_state_dirs(&registry_root, &runtime_root, 64)
        .unwrap_or_else(|error| panic!("pipeline: {error}"));
    let objective_digest = digest("objective:agentd-product");
    let scope_digest = digest("scope:agentd-product");
    let state_digest = digest("state:agentd-product");
    let generation_vector_digest = digest("generation:agentd-product");
    let grammar_digest = digest("grammar:agentd-product");
    let logical_now = 100_u64;
    let enumeration = PromptEnumerationRequestV1 {
        set_id: id("enumeration:agentd-product"),
        objective_digest,
        scope_digest,
        state_digest,
        generation_vector_digest,
        model_tuple: tuple.clone(),
        now_unix_ms: logical_now,
        required_factor_ids: vec![factor.factor_id.clone()],
        maximum_candidates: 8,
        selection_grammar_digest: grammar_digest,
    };
    let preflight = pipeline
        .enumerate_candidates(enumeration.clone())
        .unwrap_or_else(|error| panic!("preflight enumeration: {error}"));

    let generator_key = SigningKey::from_bytes(&[71; 32]);
    let evaluator_key = SigningKey::from_bytes(&[72; 32]);
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest,
        objective_digest,
        authority_epoch: 7,
        signers: vec![
            trusted_signer(
                "generator:prompt",
                "controller:generator",
                71,
                LearningEvidenceRoleV1::Generator,
                scope_digest,
            ),
            trusted_signer(
                "evaluator:prompt",
                "controller:evaluator",
                72,
                LearningEvidenceRoleV1::Evaluator,
                scope_digest,
            ),
        ],
    })
    .unwrap_or_else(|error| panic!("verifier: {error}"));
    assert_ne!(
        generator_key.verifying_key().to_bytes(),
        evaluator_key.verifying_key().to_bytes()
    );

    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: preflight.receipt.set_id.clone(),
        state_digest,
        generator_id: id("prompt.optimizer"),
        generator_code_digest: digest("generator-code:prompt.optimizer"),
        grammar_digest,
        hard_filter_digest: digest("hard-filter:prompt.optimizer"),
        truncation_digest: digest("truncation:prompt.optimizer"),
        candidates_digest: preflight.candidates_digest,
        candidate_count: u32::try_from(preflight.candidates.len()).unwrap_or(u32::MAX),
        omitted_count_bound: preflight.omitted_count,
        canonical_order_digest: preflight.canonical_order_digest,
        complete_for_generator: true,
    };
    let completeness_payload = candidate_completeness_signing_payload_v1(&completeness)
        .unwrap_or_else(|error| panic!("completeness payload: {error}"));
    let completeness_evidence = sign_evidence(
        &verifier,
        "generator:prompt",
        71,
        LearningEvidenceRoleV1::Generator,
        &completeness_payload,
    );

    let pricing_policy = PromptPricingPolicyV1 {
        policy_id: id("pricing-policy:agentd-product"),
        token_cost_per_token_q32: FixedQ32::ZERO,
        latency_cost_per_micro_q32: FixedQ32::ZERO,
        interference_cost_per_ppm_q32: FixedQ32::ZERO,
        downside_weight_q32: FixedQ32::ONE,
        minimum_support_count: 1,
        maximum_interference_ppm: 1_000_000,
    };
    let policy_digest = pricing_policy
        .digest()
        .unwrap_or_else(|error| panic!("pricing policy: {error}"));
    let candidate = &preflight.candidates[0];
    let placeholder = sign_evidence(
        &verifier,
        "evaluator:prompt",
        72,
        LearningEvidenceRoleV1::Evaluator,
        b"placeholder",
    );
    let mut pricing = PromptPricingEvidenceV1 {
        factor_id: candidate.factor_id.clone(),
        candidate_set_digest: preflight.candidates_digest,
        registry_snapshot_digest: preflight.registry_snapshot.snapshot_digest,
        generation_vector_digest,
        realization_id: candidate.realization.realization_id.clone(),
        realization_binding_digest: candidate.binding_digest,
        objective_digest,
        scope_digest,
        state_digest,
        model_tuple_digest: tuple.digest(),
        pricing_policy_digest: policy_digest,
        expected_incremental_utility_q32: FixedQ32::from_raw(100),
        downside_q32: FixedQ32::ZERO,
        confidence_lower_q32: FixedQ32::from_raw(90),
        confidence_upper_q32: FixedQ32::from_raw(110),
        support_count: 8,
        latency_cost_micros: 1,
        interference_ppm: 0,
        context_crowding_cost_q32: FixedQ32::ZERO,
        privacy_cost_q32: FixedQ32::ZERO,
        instability_cost_q32: FixedQ32::ZERO,
        future_context_option_cost_q32: FixedQ32::ZERO,
        source_support_audit_digest: digest("pricing-support:agentd-product"),
        evidence: placeholder,
    };
    let pricing_payload = pricing_evidence_signing_payload_v1(&pricing);
    pricing.evidence = sign_evidence(
        &verifier,
        "evaluator:prompt",
        72,
        LearningEvidenceRoleV1::Evaluator,
        &pricing_payload,
    );

    let graph_source_digest = digest("graph-source:agentd-product");
    let graph_profile_digest = digest("graph-profile:agentd-product");
    let graph = build_complete_generation(
        Generation::new(1).unwrap_or_else(|error| panic!("generation: {error}")),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: graph_source_digest,
            generation_vector_digest,
            graph_profile_digest,
            complete_source_cut: true,
            nodes: vec![KnowledgeNodeV2 {
                node_id: factor.factor_id.clone(),
                node_kind_id: id("kind:prompt-factor"),
                payload_digest: factor.content_digest,
                supports: vec![KnowledgeSupportV2 {
                    source_id: id("support:agentd-product"),
                    source_revision: Revision::new(1)
                        .unwrap_or_else(|error| panic!("revision: {error}")),
                    source_fact_digest: factor.content_digest,
                    validity_digest: digest("validity:agentd-product"),
                    valid_from_unix_seconds: None,
                    valid_to_unix_seconds: None,
                    tombstoned: false,
                }],
            }],
            edges: Vec::new(),
        },
    )
    .unwrap_or_else(|error| panic!("graph: {error}"));

    let exercise_policy = PromptExercisePolicyV1 {
        policy_id: id("exercise-policy:agentd-product"),
        objective_digest,
        scope_digest,
        model_tuple_digest: tuple.digest(),
        allowed_boundaries: vec![PromptDecisionBoundaryV1::BeforeModelOrToolDispatch],
        minimum_exercise_margin_q32: FixedQ32::ZERO,
        valid_from_unix_ms: 1,
        valid_until_unix_ms: 5_000,
    };
    let exercise_request = PromptExerciseRequestV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: state_digest,
        generation_vector_digest,
        model_tuple: tuple.clone(),
        current_graph_generation_digest: graph.generation_digest,
        current_graph_source_snapshot_digest: graph.source_snapshot_digest,
        current_graph_profile_digest: graph.graph_profile_digest,
        current_trust_digest: verifier.trust_digest(),
        current_authority_epoch: verifier.authority_epoch(),
        now_unix_ms: logical_now,
        wait_value_q32: FixedQ32::ZERO,
        wait_value_evidence_digest: digest("wait-evidence:agentd-product"),
        policy: exercise_policy,
    };
    let wall_now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|error| panic!("clock: {error}"))
        .as_millis() as u64;
    let prepared = run_canonical_prompt_product_v1(
        &pipeline,
        &verifier,
        AgentdCanonicalPromptProductRequestV1 {
            thread_id: "thread:product".to_owned(),
            turn_id: "turn:product".to_owned(),
            model: "gpt-test".to_owned(),
            requested_deadline_ms: wall_now + 60_000,
            enumeration,
            completeness,
            completeness_evidence,
            pricing_evidence: vec![pricing],
            pricing_policy,
            graph,
            pair_evidence: Vec::new(),
            portfolio_request: PromptPortfolioRequestV1 {
                portfolio_id: id("portfolio:agentd-product"),
                graph_query_id: id("query:agentd-product"),
                token_budget: 128,
                maximum_selected_factors: 1,
                requested_valid_until_unix_ms: 4_000,
            },
            exercise_request,
            compilation_request: PromptRegistryCompilationRequestV2 {
                compilation_id: id("compilation:agentd-product"),
                serialization_id: id("serialization:agentd-product"),
                attachment_id: id("attachment:agentd-product"),
                registry_model_tuple: tuple.clone(),
                context_model_profile: ContextModelProfileV2 {
                    model_digest: tuple.model_digest,
                    provider_id_digest: digest("provider:agentd-product"),
                    provider_model_digest: tuple.model_digest,
                    tokenizer_digest: tuple.tokenizer_digest,
                    serializer_digest: digest("serializer:agentd-product"),
                    template_digest: tuple.template_digest,
                    tool_schema_digest: tuple.tool_schema_digest,
                    maximum_context_tokens: 128,
                },
                now_unix_ms: logical_now,
                token_budget: 128,
                truncation_policy_digest: digest("context-truncation:agentd-product"),
            },
        },
    )
    .unwrap_or_else(|error| panic!("canonical product chain: {error}"));
    prepared
        .validate()
        .unwrap_or_else(|error| panic!("prepared receipt: {error}"));
    assert_eq!(prepared.staged, PromptRuntimeStageDisposition::Inserted);
    assert_eq!(
        prepared.portfolio().receipt.factor_ids,
        vec![factor.factor_id.clone()]
    );
    assert!(!prepared.solver_audit_digest.is_zero());

    let staged = pipeline
        .runtime_owner()
        .prepare(codex_hepta_codex_adapter::PromptRuntimePrepareRequest {
            thread_id: "thread:product".to_owned(),
            turn_id: "turn:product".to_owned(),
            model_context_window: Some(128),
        })
        .unwrap_or_else(|error| panic!("prepare staged product prompt: {error}"))
        .unwrap_or_else(|| panic!("staged attachment missing"));
    assert_eq!(staged.developer_fragments.len(), 1);
    assert_eq!(staged.developer_fragments[0].text.as_bytes(), payload);
}
