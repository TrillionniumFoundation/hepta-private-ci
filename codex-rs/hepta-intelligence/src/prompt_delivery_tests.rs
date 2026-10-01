use super::*;
use codex_hepta_kg::build_prompt_factor_projection_v1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_prompt_optimizer::canonical::*;
use codex_hepta_types::Generation;

use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_prompt_registry::final_use_realization_binding;
use codex_hepta_prompt_registry::final_use_revoke_binding;
use codex_hepta_types::FixedQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn sign_learning_evidence(
    verifier: &LearningEvidenceVerifierV1,
    key: &SigningKey,
    principal_id: &str,
    role: LearningEvidenceRoleV1,
    evidence_id: &str,
    payload: &[u8],
    now: u64,
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(evidence_id),
        principal_id: id(principal_id),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at: now,
        expires_at: now + 30_000,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

pub(crate) fn admitted_registry(
    root: &std::path::Path,
    payload: &[u8],
) -> (
    DurablePromptRegistry,
    PromptModelTupleV2,
    FinalUseAuthority,
    SigningKey,
    u64,
) {
    let mut registry =
        DurablePromptRegistry::open_state_dir(root, 64).expect("open durable registry");
    let factor = PromptFactor {
        factor_id: id("factor:verify"),
        proposer_id: id("proposer:1"),
        semantic_version: id("v1"),
        semantic_purpose: "inspect evidence before mutation".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:truth")],
        content_digest: digest("factor:verify"),
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

    let tuple = PromptModelTupleV2 {
        model_id: id("model:hepta-test"),
        model_version: "2026-09-18".to_owned(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
    };
    let realization = PromptRealizationBindingV2 {
        realization_id: id("realization:verify"),
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
        grant_id: "realization:prompt:1".to_owned(),
        nonce: [24; 32],
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
    (registry, tuple, authority, signing_key, now)
}

pub(crate) struct CanonicalSelection {
    pub(crate) portfolio: SelectedPromptPortfolioV1,
    pub(crate) exercise_request: PromptExerciseRequestV1,
}

pub(crate) fn canonical_selection(
    registry: &DurablePromptRegistry,
    tuple: &PromptModelTupleV2,
    now: u64,
) -> CanonicalSelection {
    let candidates = enumerate_factors_v1(
        registry.registry().expect("registry"),
        PromptEnumerationRequestV1 {
            set_id: id("set:canonical"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            generation_vector_digest: digest("generation-vector"),
            model_tuple: tuple.clone(),
            now_unix_ms: now,
            required_factor_ids: vec![id("factor:verify")],
            maximum_candidates: 8,
            selection_grammar_digest: digest("grammar"),
        },
    )
    .expect("enumerate current registry");
    let generator_key = SigningKey::from_bytes(&[79; 32]);
    let evaluator_key = SigningKey::from_bytes(&[80; 32]);
    let evidence_scope = digest("scope:prompt-selection-evidence");
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: evidence_scope,
        objective_digest: candidates.receipt.objective_digest,
        authority_epoch: 1,
        signers: [
            (
                "prompt.optimizer",
                LearningEvidenceRoleV1::Generator,
                &generator_key,
            ),
            (
                "prompt-evaluator:fixture",
                LearningEvidenceRoleV1::Evaluator,
                &evaluator_key,
            ),
        ]
        .into_iter()
        .map(|(principal_id, role, key)| {
            let public_key = key.verifying_key().to_bytes();
            TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: id(principal_id),
                    credential_chain_digest: digest(&format!("credential:{principal_id}")),
                    signing_key_digest: Digest32::of_bytes(&public_key),
                    scope_digest: evidence_scope,
                    authority_epoch: 1,
                    authenticated_at: 1,
                    expires_at: now + 30_000,
                },
                controller_id: id(&format!("controller:{principal_id}")),
                verifying_key: public_key,
                roles: vec![role],
                revoked_at: None,
            }
        })
        .collect(),
    })
    .expect("host-pinned prompt evidence trust");
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: candidates.receipt.set_id.clone(),
        state_digest: candidates.receipt.state_digest,
        generator_id: id("prompt.optimizer"),
        generator_code_digest: digest("prompt-generator-fixture-code"),
        grammar_digest: candidates.receipt.selection_grammar_digest,
        hard_filter_digest: digest("prompt-generator-fixture-filters"),
        truncation_digest: digest("prompt-generator-fixture-truncation"),
        candidates_digest: candidates.candidates_digest,
        candidate_count: u32::try_from(candidates.candidates.len()).expect("bounded candidates"),
        omitted_count_bound: candidates.omitted_count,
        canonical_order_digest: candidates.canonical_order_digest,
        complete_for_generator: true,
    };
    let completeness_evidence = sign_learning_evidence(
        &verifier,
        &generator_key,
        "prompt.optimizer",
        LearningEvidenceRoleV1::Generator,
        "evidence:prompt-completeness",
        &candidate_completeness_signing_payload_v1(&completeness).expect("completeness payload"),
        now,
    );
    let pricing_evidence = candidates
        .candidates
        .iter()
        .map(|candidate| {
            let mut evidence = PromptPricingEvidenceV1 {
                factor_id: candidate.factor_id.clone(),
                state_digest: candidates.receipt.state_digest,
                model_tuple_digest: candidates.model_tuple.digest(),
                expected_incremental_utility_q32: FixedQ32::ONE,
                downside_q32: FixedQ32::ZERO,
                confidence_lower_q32: FixedQ32::ONE,
                confidence_upper_q32: FixedQ32::ONE,
                support_count: 10,
                latency_cost_micros: 0,
                interference_ppm: 0,
                context_crowding_cost_q32: FixedQ32::ZERO,
                privacy_cost_q32: FixedQ32::ZERO,
                instability_cost_q32: FixedQ32::ZERO,
                future_context_option_cost_q32: FixedQ32::ZERO,
                support_audit_digest: digest("prompt-pricing-fixture-support"),
                evidence: completeness_evidence.clone(),
            };
            evidence.evidence = sign_learning_evidence(
                &verifier,
                &evaluator_key,
                "prompt-evaluator:fixture",
                LearningEvidenceRoleV1::Evaluator,
                &format!("evidence:pricing:{}", candidate.factor_id),
                &pricing_evidence_signing_payload_v1(&evidence),
                now,
            );
            evidence
        })
        .collect();
    let policy = PromptPricingPolicyV1 {
        policy_id: id("policy:prompt-pricing-fixture"),
        token_cost_per_token_q32: FixedQ32::ZERO,
        latency_cost_per_micro_q32: FixedQ32::ZERO,
        interference_cost_per_ppm_q32: FixedQ32::ZERO,
        downside_weight_q32: FixedQ32::ZERO,
        minimum_support_count: 1,
        maximum_interference_ppm: 1_000_000,
    };
    let vector = candidates.generation_vector_digest;
    let priced = price_factors_v1(
        candidates,
        &completeness,
        &completeness_evidence,
        pricing_evidence,
        &verifier,
        &policy,
        now,
    )
    .expect("price authenticated prompt candidates");
    let source = registry
        .registry()
        .expect("registry")
        .factor_graph_source_v1();
    let projection =
        build_prompt_factor_projection_v1(Generation::new(1).expect("generation"), vector, &source)
            .expect("current owner prompt graph projection");
    let portfolio = select_portfolio_v1(
        &priced,
        &projection,
        Vec::new(),
        &verifier,
        PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:1"),
            graph_query_id: id("query:prompt-selection-fixture"),
            token_budget: 128,
            maximum_selected_factors: 8,
            requested_valid_until_unix_ms: 9_000,
        },
        now,
    )
    .expect("select sealed prompt portfolio");
    let exercise_request = PromptExerciseRequestV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: digest("state"),
        generation_vector_digest: digest("generation-vector"),
        model_tuple: tuple.clone(),
        now_unix_ms: now,
        wait_value_q32: FixedQ32::ZERO,
        policy_digest: digest("exercise-policy"),
    };
    CanonicalSelection {
        portfolio,
        exercise_request,
    }
}

#[test]
fn exercised_registry_payload_is_the_exact_context_attachment_input() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-registry");
    let payload = b"Inspect evidence before mutation.";
    let (registry, tuple, _authority, _signing_key, _grant_now) = admitted_registry(&root, payload);
    let selected = canonical_selection(&registry, &tuple, 100);

    let output = compile_prompt_registry_v2(
        &registry,
        &selected.portfolio,
        &selected.exercise_request,
        PromptRegistryCompilationRequestV2 {
            compilation_id: id("compilation:prompt:1"),
            serialization_id: id("serialization:prompt:1"),
            attachment_id: id("attachment:prompt:1"),
            registry_model_tuple: tuple.clone(),
            context_model_profile: ContextModelProfileV2 {
                model_digest: tuple.model_digest,
                provider_id_digest: digest("provider"),
                provider_model_digest: tuple.model_digest,
                tokenizer_digest: tuple.tokenizer_digest,
                serializer_digest: digest("serializer"),
                template_digest: tuple.template_digest,
                tool_schema_digest: tuple.tool_schema_digest,
                maximum_context_tokens: 128,
            },
            now_unix_ms: 100,
            token_budget: 128,
            truncation_policy_digest: digest("truncation"),
        },
    )
    .expect("compile exercised prompt registry context");

    assert_eq!(
        output.compiled.receipt().selected_item_ids(),
        vec![id("realization:verify")]
    );
    assert_eq!(output.selected_deliveries.len(), 1);
    assert_eq!(output.selected_deliveries[0].payload, payload);
    assert_eq!(
        output.selected_deliveries[0].binding.digest(),
        selected.portfolio.selected[0].binding_digest
    );
    assert_eq!(
        output.exercise_receipt_digest,
        exercise_v1(
            registry.registry().expect("registry"),
            &selected.portfolio,
            selected.exercise_request.clone()
        )
        .expect("exercise")
        .receipt_digest
    );
    assert_eq!(
        output.portfolio_receipt_digest,
        selected.portfolio.receipt.receipt_digest
    );
    assert_eq!(
        Digest32::of_bytes(&output.serialized_payload),
        output.serialization.payload_digest()
    );
    assert_eq!(
        output.attachment.payload_digest(),
        output.serialization.payload_digest()
    );
    assert!(
        output
            .serialized_payload
            .windows(payload.len())
            .any(|window| window == payload)
    );

    let factor_v1 = registry
        .registry()
        .expect("registry")
        .factor_protocol_v1(&id("factor:verify"))
        .expect("factor projection")
        .expect("factor exists");
    assert_eq!(
        factor_v1.semantic_purpose,
        "inspect evidence before mutation"
    );
    let realization_v1 = registry
        .registry()
        .expect("registry")
        .realization_protocol_v1(&id("realization:verify"))
        .expect("realization projection")
        .expect("realization exists");
    assert_eq!(realization_v1.model_id, tuple.model_id);
    assert_eq!(realization_v1.model_version, tuple.model_version);
    output.validate().expect("compiled delivery validates");
}

#[test]
fn revocation_after_exercise_prevents_delivery_of_the_selected_realization() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-registry-revocation");
    let (mut registry, tuple, authority, signing_key, grant_now) =
        admitted_registry(&root, b"Bound instruction");
    let selected = canonical_selection(&registry, &tuple, 100);

    let factor = registry
        .registry()
        .expect("registry")
        .factor(&id("factor:verify"))
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
        nonce: [25; 32],
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
            &authority,
            &revoke_signed,
            &factor.factor_id,
            &actor,
            revoke_scope,
            reason,
            cutoff,
        )
        .expect("final-use revocation");

    let error = compile_prompt_registry_v2(
        &registry,
        &selected.portfolio,
        &selected.exercise_request,
        PromptRegistryCompilationRequestV2 {
            compilation_id: id("compilation:prompt:2"),
            serialization_id: id("serialization:prompt:2"),
            attachment_id: id("attachment:prompt:2"),
            registry_model_tuple: tuple.clone(),
            context_model_profile: ContextModelProfileV2 {
                model_digest: tuple.model_digest,
                provider_id_digest: digest("provider"),
                provider_model_digest: tuple.model_digest,
                tokenizer_digest: tuple.tokenizer_digest,
                serializer_digest: digest("serializer"),
                template_digest: tuple.template_digest,
                tool_schema_digest: tuple.tool_schema_digest,
                maximum_context_tokens: 128,
            },
            now_unix_ms: 100,
            token_budget: 128,
            truncation_policy_digest: digest("truncation"),
        },
    )
    .expect_err("stale exercised selection must not deliver");
    assert!(matches!(
        error,
        PromptRegistryCompilationErrorV2::Pipeline(_)
    ));
}

#[test]
fn compiler_rejects_registry_and_context_model_drift() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-registry-model-drift");
    let (registry, tuple, _authority, _signing_key, _grant_now) =
        admitted_registry(&root, b"Bound instruction");
    let selected = canonical_selection(&registry, &tuple, 100);

    let error = compile_prompt_registry_v2(
        &registry,
        &selected.portfolio,
        &selected.exercise_request,
        PromptRegistryCompilationRequestV2 {
            compilation_id: id("compilation:prompt:3"),
            serialization_id: id("serialization:prompt:3"),
            attachment_id: id("attachment:prompt:3"),
            registry_model_tuple: tuple.clone(),
            context_model_profile: ContextModelProfileV2 {
                model_digest: digest("other-model"),
                provider_id_digest: digest("provider"),
                provider_model_digest: tuple.model_digest,
                tokenizer_digest: tuple.tokenizer_digest,
                serializer_digest: digest("serializer"),
                template_digest: tuple.template_digest,
                tool_schema_digest: tuple.tool_schema_digest,
                maximum_context_tokens: 128,
            },
            now_unix_ms: 100,
            token_budget: 128,
            truncation_policy_digest: digest("truncation"),
        },
    )
    .expect_err("model drift must fail");
    assert!(matches!(
        error,
        PromptRegistryCompilationErrorV2::Pipeline(_)
    ));
}

pub(crate) fn revoke_registry(
    registry: &mut DurablePromptRegistry,
    authority: &FinalUseAuthority,
    signing_key: &SigningKey,
    grant_now: u64,
) {
    let factor = registry
        .registry()
        .expect("registry")
        .factor(&id("factor:verify"))
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
        nonce: [25; 32],
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
