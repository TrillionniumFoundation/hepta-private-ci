use super::*;

use codex_hepta_context_compiler::{ContextDeliveryDispositionV2, ContextModelProfileV2};
use codex_hepta_prompt_optimizer::canonical::{
    PromptCandidateBindingV1, PromptDecisionBoundaryV1, PromptExerciseRequestV1,
    PromptOptimalityDisclosureV1, PromptPortfolioReceiptV1, PromptSelectionMethodV1,
    SelectedPromptPortfolioV1,
};
use codex_hepta_prompt_registry::{
    FactorSource, Lifecycle, PromptFactor, PromptModelTupleV2, PromptRealizationBindingV2,
    PromptRoleV2,
};
use codex_hepta_types::{AuthorityPosture, Digest32, FixedQ32, StableId};

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        locale_id: id("locale:en-US"),
    }
}

fn profile() -> ContextModelProfileV2 {
    let tuple = tuple();
    ContextModelProfileV2 {
        model_digest: tuple.model_digest,
        tokenizer_digest: tuple.tokenizer_digest,
        template_digest: tuple.template_digest,
        tool_schema_digest: tuple.tool_schema_digest,
        maximum_context_tokens: 4096,
    }
}

fn registry_and_binding_with_payload(
    register_payload: bool,
) -> (PromptRegistry, PromptRealizationBindingV2) {
    let mut registry = PromptRegistry::new(64).expect("registry");
    registry
        .register_factor(PromptFactor {
            factor_id: id("factor:a"),
            proposer_id: id("proposer:a"),
            semantic_version: id("v1"),
            content_digest: digest("factor:a"),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        })
        .expect("register factor");
    registry
        .admit_factor(&id("factor:a"), &id("reviewer:a"), digest("admission"))
        .expect("admit factor");
    let tuple = tuple();
    let payload = b"payload:a".to_vec();
    let binding = PromptRealizationBindingV2 {
        realization_id: id("realization:a"),
        factor_id: id("factor:a"),
        model_digest: tuple.model_digest,
        tokenizer_digest: tuple.tokenizer_digest,
        template_digest: tuple.template_digest,
        tool_schema_digest: tuple.tool_schema_digest,
        locale_id: tuple.locale_id,
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: Digest32::of_bytes(&payload),
        token_cost: 8,
        expires_unix_ms: Some(10_000),
    };
    if register_payload {
        registry
            .register_realization_with_payload_v2(binding.clone(), payload)
            .expect("register realization with payload");
    } else {
        registry
            .register_realization_v2(binding.clone())
            .expect("register realization");
    }
    (registry, binding)
}

fn registry_and_binding() -> (PromptRegistry, PromptRealizationBindingV2) {
    registry_and_binding_with_payload(true)
}

fn portfolio(binding: PromptRealizationBindingV2) -> SelectedPromptPortfolioV1 {
    let tuple = tuple();
    SelectedPromptPortfolioV1 {
        receipt: PromptPortfolioReceiptV1 {
            portfolio_id: id("portfolio:1"),
            candidate_set_digest: digest("candidate-set"),
            factor_ids: vec![id("factor:a")],
            interaction_digest: digest("interaction"),
            expected_utility_q32: FixedQ32::from_raw(10),
            total_token_upper_bound: 8,
            valid_until_unix_ms: 9_000,
            receipt_digest: digest("portfolio-receipt"),
            authority: AuthorityPosture::DENY_ALL,
        },
        selected: vec![PromptCandidateBindingV1 {
            factor_id: id("factor:a"),
            binding_digest: binding.digest(),
            realization: binding,
        }],
        objective_digest: digest("objective"),
        state_digest: digest("state"),
        model_tuple: tuple.clone(),
        model_tuple_digest: tuple.digest(),
        generation_vector_digest: digest("generation-vector"),
        pricing_set_digest: digest("pricing-set"),
        graph_generation_digest: digest("graph-generation"),
        selection_method: PromptSelectionMethodV1::GreedyPrerequisiteBundleV1,
        optimality: PromptOptimalityDisclosureV1::HeuristicNoCertificate,
    }
}

fn exercise(now: u64) -> PromptExerciseRequestV1 {
    PromptExerciseRequestV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: digest("state"),
        generation_vector_digest: digest("generation-vector"),
        model_tuple: tuple(),
        now_unix_ms: now,
        wait_value_q32: FixedQ32::ZERO,
        policy_digest: digest("exercise-policy"),
    }
}

fn compile_request(now: u64) -> PromptContextCompileRequestV1 {
    PromptContextCompileRequestV1 {
        exercise: exercise(now),
        compilation_id: id("compilation:1"),
        model_profile: profile(),
        token_budget: 128,
        truncation_policy_digest: digest("truncation"),
        base_candidates: Vec::new(),
        mandatory_groups: Vec::new(),
    }
}

#[test]
fn exercised_portfolio_compiles_attaches_and_observes_exact_delivery() {
    let (registry, binding) = registry_and_binding();
    let portfolio = portfolio(binding);
    let prepared = compile_exercised_prompt_context_v1(&registry, &portfolio, compile_request(100))
        .expect("compile exercised portfolio");
    assert_eq!(
        prepared.compiled.receipt.selected_item_ids,
        vec![id("realization:a")]
    );
    assert!(!prepared.compiled.receipt.authority.grants_any());
    assert_eq!(prepared.materialization.payloads.len(), 1);
    assert_eq!(
        prepared.materialization.payloads[0].payload,
        b"payload:a".to_vec()
    );
    assert!(!prepared.materialization.authority.grants_any());

    let serialized_payload = b"provider-prefix|payload:a|provider-suffix".to_vec();
    let payload_digest = Digest32::of_bytes(&serialized_payload);
    let delivery = prepare_prompt_delivery_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise: exercise(101),
            serialization_id: id("serialization:1"),
            serialized_payload: serialized_payload.clone(),
            attachment_id: id("attachment:1"),
        },
    )
    .expect("prepare delivery");
    assert_eq!(delivery.serialized_payload, serialized_payload);
    assert_eq!(delivery.materialization, prepared.materialization);
    assert_eq!(delivery.serialization.payload_digest, payload_digest);
    assert_eq!(delivery.serialization_proof.occurrences.len(), 1);
    assert_eq!(
        delivery.serialization_proof.occurrences[0].realization_id,
        id("realization:a")
    );
    assert!(!delivery.serialization_proof.authority.grants_any());
    assert!(!delivery.attachment.authority.grants_any());

    let observation = observe_prompt_delivery_v1(
        &delivery,
        id("delivery-observation:1"),
        Some(payload_digest),
        true,
        ContextDeliveryDispositionV2::Delivered,
        102,
    )
    .expect("observe delivery");
    assert_eq!(observation.observed_payload_digest, Some(payload_digest));
    assert!(!observation.authority.grants_any());
}

#[test]
fn revocation_after_compilation_blocks_attachment_preparation() {
    let (mut registry, binding) = registry_and_binding();
    let portfolio = portfolio(binding);
    let prepared = compile_exercised_prompt_context_v1(&registry, &portfolio, compile_request(100))
        .expect("compile exercised portfolio");

    registry
        .revoke_factor(&id("factor:a"))
        .expect("revoke after compile");
    let error = prepare_prompt_delivery_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise: exercise(101),
            serialization_id: id("serialization:stale"),
            serialized_payload: b"payload:stale".to_vec(),
            attachment_id: id("attachment:stale"),
        },
    )
    .expect_err("revocation must block delivery");
    assert_eq!(
        error,
        PromptPipelineErrorV1::ExerciseRejected(
            codex_hepta_prompt_optimizer::canonical::PromptExerciseActionV1::RejectStale
        )
    );
}

#[test]
fn selected_realization_without_registry_payload_fails_closed() {
    let (registry, binding) = registry_and_binding_with_payload(false);
    let portfolio = portfolio(binding);
    let error = compile_exercised_prompt_context_v1(&registry, &portfolio, compile_request(100))
        .expect_err("selected realization without exact payload must fail");
    assert!(matches!(
        error,
        PromptPipelineErrorV1::Registry(message) if message.contains("PayloadMissing")
    ));
}

#[test]
fn serialization_without_selected_prompt_bytes_fails_closed() {
    let (registry, binding) = registry_and_binding();
    let portfolio = portfolio(binding);
    let prepared = compile_exercised_prompt_context_v1(&registry, &portfolio, compile_request(100))
        .expect("compile exercised portfolio");

    let error = prepare_prompt_delivery_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise: exercise(101),
            serialization_id: id("serialization:missing-prompt"),
            serialized_payload: b"provider-request-without-selected-realization".to_vec(),
            attachment_id: id("attachment:missing-prompt"),
        },
    )
    .expect_err("missing selected prompt bytes must fail");
    assert_eq!(
        error,
        PromptPipelineErrorV1::SerializedPayloadMissing("realization:a".to_string())
    );
}
