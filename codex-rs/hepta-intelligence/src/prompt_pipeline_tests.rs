use std::fmt::Debug;

use super::*;
use codex_hepta_context_compiler::{ContextDeliveryDispositionV2, observe_delivery};
use codex_hepta_prompt_optimizer::canonical::{
    CandidateEvidenceV1, PortfolioBudgetV1,
};
use codex_hepta_prompt_registry::{
    FactorSource, Lifecycle, PromptFactor, PromptRealizationBindingV2, PromptRoleV2,
};
use codex_hepta_types::FixedQ32;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("test fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

#[test]
fn canonical_caller_compiles_exercised_prompt_portfolio() {
    let mut registry = must(PromptRegistry::new(64));
    let prompt_model = PromptModelTupleV2 {
        model_digest: digest(b"model"),
        tokenizer_digest: digest(b"tokenizer"),
        template_digest: digest(b"template"),
        tool_schema_digest: digest(b"tools"),
        locale_id: id("en-US"),
    };
    for index in 0..2 {
        let factor_id = id(&format!("factor:{index}"));
        must(registry.register_factor(PromptFactor {
            factor_id: factor_id.clone(),
            proposer_id: id(&format!("proposer:{index}")),
            semantic_version: id("v1"),
            content_digest: digest(format!("factor:{index}").as_bytes()),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        }));
        must(registry.admit_factor(
            &factor_id,
            &id(&format!("reviewer:{index}")),
            digest(format!("review:{index}").as_bytes()),
        ));
        must(registry.register_realization_v2(PromptRealizationBindingV2 {
            realization_id: id(&format!("realization:{index}")),
            factor_id,
            model_digest: prompt_model.model_digest,
            tokenizer_digest: prompt_model.tokenizer_digest,
            template_digest: prompt_model.template_digest,
            tool_schema_digest: prompt_model.tool_schema_digest,
            locale_id: prompt_model.locale_id.clone(),
            role: if index == 0 {
                PromptRoleV2::DeveloperInstruction
            } else {
                PromptRoleV2::ToolSchemaFragment
            },
            payload_digest: digest(format!("payload:{index}").as_bytes()),
            token_cost: 2,
            expires_unix_ms: None,
        }));
    }
    let generation = digest(b"generation");
    let snapshot = must(registry.snapshot_v2(generation, &prompt_model));
    let compatible = must(registry.read_compatible_v2(
        &snapshot,
        generation,
        &prompt_model,
        10,
        Vec::new(),
        128,
    ));
    let evidence = compatible
        .bindings
        .iter()
        .map(|binding| CandidateEvidenceV1 {
            candidate_id: binding.realization_id.clone(),
            causal_utility: FixedQ32::from_raw(10),
            token_shadow_cost: FixedQ32::ZERO,
            latency_cost: FixedQ32::ZERO,
            crowding_cost: FixedQ32::ZERO,
            interference_cost: FixedQ32::ZERO,
            privacy_cost: FixedQ32::ZERO,
            instability_cost: FixedQ32::ZERO,
            future_option_cost: FixedQ32::ZERO,
            resource_cost: FixedQ32::ZERO,
            support_digest: digest(binding.realization_id.as_str().as_bytes()),
            confidence_digest: digest(b"confidence"),
            applicability_digest: digest(b"applicability"),
        })
        .collect();

    let receipt = must(run_canonical_prompt_context_v1(
        CanonicalPromptContextRequestV1 {
            registry: &registry,
            expected_registry_snapshot: &snapshot,
            generation_vector_digest: generation,
            prompt_model: &prompt_model,
            context_model: ContextModelProfileV2 {
                model_digest: prompt_model.model_digest,
                tokenizer_digest: prompt_model.tokenizer_digest,
                template_digest: prompt_model.template_digest,
                tool_schema_digest: prompt_model.tool_schema_digest,
                maximum_context_tokens: 32,
            },
            decision_id: id("decision"),
            compilation_id: id("compilation"),
            objective_digest: digest(b"objective"),
            generator_digest: digest(b"generator"),
            hard_filter_digest: digest(b"filter"),
            prompt_truncation_digest: digest(b"prompt-truncation"),
            context_truncation_digest: digest(b"context-truncation"),
            now_unix_ms: 10,
            evidence,
            relations: Vec::new(),
            portfolio_budget: PortfolioBudgetV1 {
                token_budget: 4,
                maximum_selected: 2,
            },
            context_token_budget: 4,
            additional_context: Vec::new(),
            mandatory_groups: Vec::new(),
        },
    ));

    assert_eq!(receipt.portfolio.selected_candidate_ids.len(), 2);
    assert_eq!(receipt.context.receipt.selected_item_ids.len(), 2);
    assert_eq!(
        receipt.context.receipt.prompt_portfolio_digest,
        receipt.portfolio.receipt_digest
    );
    assert!(!receipt.context.receipt.authority.grants_any());

    let handoff = must(prepare_canonical_prompt_attachment_v1(
        &receipt,
        id("serialization"),
        id("attachment"),
        digest(b"serialized-payload"),
    ));
    let delivery = must(observe_delivery(
        &handoff.attachment,
        id("delivery"),
        Some(handoff.attachment.payload_digest),
        true,
        ContextDeliveryDispositionV2::Delivered,
        20,
    ));
    let exposure = must(admit_canonical_prompt_delivery_v1(
        &receipt,
        &handoff,
        &delivery,
        id("exposure"),
        id("episode"),
    ));
    assert_eq!(exposure.selected_count, 2);
    assert!(!exposure.exposure_digest.is_zero());
    assert!(!exposure.authority.grants_any());
}
