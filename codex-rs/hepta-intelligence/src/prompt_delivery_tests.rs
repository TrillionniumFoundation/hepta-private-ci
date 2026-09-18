use super::*;

use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_prompt_optimizer::PromptAuthenticationErrorV1;
use codex_hepta_prompt_optimizer::PromptCandidateEnumerationRequestV1;
use codex_hepta_prompt_optimizer::PromptCostBreakdownV1;
use codex_hepta_prompt_optimizer::PromptExerciseBoundaryV1;
use codex_hepta_prompt_optimizer::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::PromptPortfolioSelectionRequestV1;
use codex_hepta_prompt_optimizer::PromptPricingEvidenceAuthenticatorV1;
use codex_hepta_prompt_optimizer::PromptPricingEvidenceV1;
use codex_hepta_prompt_optimizer::PromptRelationSourceAuthenticatorV1;
use codex_hepta_prompt_optimizer::PromptRelationSourceV1;
use codex_hepta_prompt_optimizer::enumerate_factors_v1;
use codex_hepta_prompt_optimizer::exercise_portfolio_v1;
use codex_hepta_prompt_optimizer::price_factors_v1;
use codex_hepta_prompt_optimizer::select_portfolio_v1;
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

fn admitted_registry(
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
        &factor,
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

struct AcceptPricing;

impl PromptPricingEvidenceAuthenticatorV1 for AcceptPricing {
    fn authenticate_pricing_evidence(
        &self,
        _evidence: &PromptPricingEvidenceV1,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Ok(())
    }
}

struct AcceptRelations;

impl PromptRelationSourceAuthenticatorV1 for AcceptRelations {
    fn authenticate_relation_source(
        &self,
        _source: &PromptRelationSourceV1,
        _objective_digest: Digest32,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Ok(())
    }
}

struct CanonicalSelection {
    adapter: PromptRegistryCandidateAdapterV1,
    candidate_set: PromptCandidateSetReceiptV1,
    pricing: PromptPricingReceiptV1,
    relations: PromptRelationSourceV1,
    portfolio: PromptPortfolioReceiptV1,
    exercise: PromptExerciseDecisionV1,
    exercise_request: PromptExerciseRequestV1,
}

fn canonical_selection(
    registry: &DurablePromptRegistry,
    tuple: &PromptModelTupleV2,
    now_unix_ms: u64,
) -> CanonicalSelection {
    let adapter = PromptRegistryCandidateAdapterV1::from_registry(
        registry,
        digest("generation-vector"),
        tuple,
        now_unix_ms,
        vec![id("factor:verify")],
        8,
    )
    .expect("registry owner adapts");

    let candidate_set = enumerate_factors_v1(
        PromptCandidateEnumerationRequestV1 {
            enumeration_id: id("enumeration:prompt:1"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            maximum_candidates: 8,
            now_unix_ms,
            source: adapter.source().clone(),
        },
        &adapter,
    )
    .expect("enumerate");

    let candidate = candidate_set.candidates.first().expect("candidate");
    let zero_costs = PromptCostBreakdownV1 {
        tokens: FixedQ32::ZERO,
        latency: FixedQ32::ZERO,
        context_crowding: FixedQ32::ZERO,
        instruction_interference: FixedQ32::ZERO,
        privacy: FixedQ32::ZERO,
        instability: FixedQ32::ZERO,
        future_context_option_value: FixedQ32::ZERO,
    };
    let mut evidence = PromptPricingEvidenceV1 {
        candidate_id: candidate.candidate_id.clone(),
        candidate_binding_digest: candidate.binding_digest,
        objective_digest: candidate_set.objective_digest,
        state_digest: candidate_set.state_digest,
        model_profile_digest: candidate_set.model_profile_digest,
        causal_incremental_utility: FixedQ32::ONE,
        confidence: FixedQ32::ONE,
        costs: zero_costs,
        utility_unit_digest: digest("utility-unit"),
        cost_profile_digest: digest("cost-profile"),
        support_digest: digest("pricing-support"),
        valid_until_unix_ms: now_unix_ms + 10_000,
        evidence_digest: Digest32::ZERO,
    };
    evidence.evidence_digest = evidence.compute_evidence_digest();
    let pricing = price_factors_v1(&candidate_set, vec![evidence], now_unix_ms, &AcceptPricing)
        .expect("price");

    let mut relations = PromptRelationSourceV1 {
        producer_id: id("knowledge.graph"),
        candidate_set_digest: candidate_set.candidate_set_digest,
        generation_vector_digest: candidate_set.generation_vector_digest,
        hard_constraint_completeness_digest: digest("hard-constraint-completeness"),
        interactions: Vec::new(),
        hard_constraints: Vec::new(),
        source_digest: Digest32::ZERO,
    };
    relations.source_digest = relations.compute_source_digest();

    let portfolio = select_portfolio_v1(
        &candidate_set,
        &pricing,
        PromptPortfolioSelectionRequestV1 {
            selection_id: id("selection:prompt:1"),
            token_budget: 128,
            maximum_selected_factors: 1,
            maximum_steps: 8,
            now_unix_ms,
            relations: relations.clone(),
        },
        &AcceptRelations,
    )
    .expect("select");
    assert_eq!(
        portfolio.selected_candidate_ids,
        vec![id("realization:verify")]
    );

    let exercise_request = PromptExerciseRequestV1 {
        exercise_id: id("exercise:prompt:1"),
        boundary: PromptExerciseBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: candidate_set.state_digest,
        now_unix_ms,
        current_source: adapter.source().clone(),
    };
    let exercise = exercise_portfolio_v1(
        &candidate_set,
        &pricing,
        &relations,
        &portfolio,
        exercise_request.clone(),
        &adapter,
    )
    .expect("exercise");

    CanonicalSelection {
        adapter,
        candidate_set,
        pricing,
        relations,
        portfolio,
        exercise,
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
        &selected.adapter,
        &selected.candidate_set,
        &selected.pricing,
        &selected.relations,
        &selected.portfolio,
        &selected.exercise,
        &selected.exercise_request,
        PromptRegistryCompilationRequestV2 {
            compilation_id: id("compilation:prompt:1"),
            serialization_id: id("serialization:prompt:1"),
            attachment_id: id("attachment:prompt:1"),
            registry_model_tuple: tuple.clone(),
            context_model_profile: ContextModelProfileV2 {
                model_digest: tuple.model_digest,
                tokenizer_digest: tuple.tokenizer_digest,
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
        output.compiled.receipt.selected_item_ids,
        vec![id("realization:verify")]
    );
    assert_eq!(output.selected_deliveries.len(), 1);
    assert_eq!(output.selected_deliveries[0].payload, payload);
    assert_eq!(
        output.selected_deliveries[0].binding.digest(),
        selected.candidate_set.candidates[0].registry_binding_digest
    );
    assert_eq!(
        output.exercise_receipt_digest,
        selected.exercise.receipt_digest
    );
    assert_eq!(
        output.portfolio_receipt_digest,
        selected.portfolio.receipt_digest
    );
    assert_eq!(
        Digest32::of_bytes(&output.serialized_payload),
        output.serialization.payload_digest
    );
    assert_eq!(
        output.attachment.payload_digest,
        output.serialization.payload_digest
    );
    assert!(
        output
            .serialized_payload
            .windows(payload.len())
            .any(|window| window == payload)
    );

    let factor_v1 = registry
        .registry().expect("registry")
        .factor_protocol_v1(&id("factor:verify"))
        .expect("factor projection")
        .expect("factor exists");
    assert_eq!(
        factor_v1.semantic_purpose,
        "inspect evidence before mutation"
    );
    let realization_v1 = registry
        .registry().expect("registry")
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
        .registry().expect("registry")
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
        &selected.adapter,
        &selected.candidate_set,
        &selected.pricing,
        &selected.relations,
        &selected.portfolio,
        &selected.exercise,
        &selected.exercise_request,
        PromptRegistryCompilationRequestV2 {
            compilation_id: id("compilation:prompt:2"),
            serialization_id: id("serialization:prompt:2"),
            attachment_id: id("attachment:prompt:2"),
            registry_model_tuple: tuple.clone(),
            context_model_profile: ContextModelProfileV2 {
                model_digest: tuple.model_digest,
                tokenizer_digest: tuple.tokenizer_digest,
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
        PromptRegistryCompilationErrorV2::Registry(_)
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
        &selected.adapter,
        &selected.candidate_set,
        &selected.pricing,
        &selected.relations,
        &selected.portfolio,
        &selected.exercise,
        &selected.exercise_request,
        PromptRegistryCompilationRequestV2 {
            compilation_id: id("compilation:prompt:3"),
            serialization_id: id("serialization:prompt:3"),
            attachment_id: id("attachment:prompt:3"),
            registry_model_tuple: tuple.clone(),
            context_model_profile: ContextModelProfileV2 {
                model_digest: digest("other-model"),
                tokenizer_digest: tuple.tokenizer_digest,
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
        PromptRegistryCompilationErrorV2::ProfileMismatch
    ));
}
