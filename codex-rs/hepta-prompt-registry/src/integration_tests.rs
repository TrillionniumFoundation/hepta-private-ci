use codex_hepta_context_compiler::ContextCandidateV2;
use codex_hepta_context_compiler::ContextCompilationRequestV2;
use codex_hepta_context_compiler::ContextDeliveryDispositionV2;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::ContextRoleV2;
use codex_hepta_context_compiler::TokenizationReceiptV2;
use codex_hepta_context_compiler::build_attachment;
use codex_hepta_context_compiler::compile_v2;
use codex_hepta_context_compiler::observe_delivery;
use codex_hepta_context_compiler::record_serialization;
use codex_hepta_types::FixedQ32;

use crate::FactorSource;
use crate::PromptModelTupleV2;
use crate::PromptRealizationBindingV2;
use crate::PromptRoleV2;
use crate::test_support::TestAuthority;
use crate::test_support::admit;
use crate::test_support::digest;
use crate::test_support::factor_with_id;
use crate::test_support::id;
use crate::test_support::registry;

#[test]
fn registry_payload_bytes_bind_compilation_serialization_attachment_and_delivery() {
    let mut registry = registry();
    registry
        .register_factor(factor_with_id("factor:1", FactorSource::GovernedInternal))
        .expect("register factor");
    let authority = TestAuthority::new();
    admit(&mut registry, &authority, "factor:1", 91);

    let payload = b"Always verify evidence before making the final claim.".to_vec();
    let binding = PromptRealizationBindingV2 {
        realization_id: id("realization:1"),
        factor_id: id("factor:1"),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: codex_hepta_types::Digest32::of_bytes(&payload),
        token_cost: 9,
        expires_unix_ms: None,
        predecessor_realization_id: None,
    };
    registry
        .register_realization_v2(binding.clone(), payload.clone())
        .expect("register realization with bytes");

    let tuple = PromptModelTupleV2 {
        model_digest: binding.model_digest,
        tokenizer_digest: binding.tokenizer_digest,
        template_digest: binding.template_digest,
        tool_schema_digest: binding.tool_schema_digest,
        context_profile_digest: binding.context_profile_digest,
        locale_id: binding.locale_id.clone(),
    };
    let generation = digest("generation-vector");
    let snapshot = registry.snapshot_v2(generation, &tuple).expect("snapshot");
    let resolution = registry
        .resolve_payload_v2(&snapshot, generation, &tuple, 10, &binding.realization_id)
        .expect("resolve exact payload bytes");
    assert_eq!(resolution.payload, payload);

    let tokenization = TokenizationReceiptV2::new(
        binding.realization_id.clone(),
        binding.payload_digest,
        binding.tokenizer_digest,
        u64::from(binding.token_cost),
    )
    .expect("tokenization receipt");
    let admission = registry
        .admission(&binding.factor_id)
        .expect("admission lineage");
    let compiled = compile_v2(ContextCompilationRequestV2 {
        compilation_id: id("compilation:1"),
        objective_digest: digest("objective"),
        prompt_portfolio_digest: digest("portfolio"),
        generation_vector_digest: generation,
        model_profile: ContextModelProfileV2 {
            model_digest: binding.model_digest,
            tokenizer_digest: binding.tokenizer_digest,
            template_digest: binding.template_digest,
            tool_schema_digest: binding.tool_schema_digest,
            maximum_context_tokens: 4_096,
        },
        token_budget: 128,
        truncation_policy_digest: digest("truncation-policy"),
        candidates: vec![ContextCandidateV2 {
            item_id: binding.realization_id.clone(),
            role: ContextRoleV2::TrustedInstruction,
            content_digest: resolution.payload_digest,
            source_digest: resolution.binding_digest,
            generation_vector_digest: generation,
            tokenization,
            expected_value: FixedQ32::ONE,
            trusted_admission_digest: Some(admission.admission_digest),
            contains_secret: false,
        }],
        mandatory_groups: Vec::new(),
    })
    .expect("compile resolved registry realization");

    let serialized_payload = resolution.payload.clone();
    let serialized_digest = codex_hepta_types::Digest32::of_bytes(&serialized_payload);
    assert_eq!(serialized_digest, binding.payload_digest);
    let serialization = record_serialization(&compiled, id("serialization:1"), serialized_digest)
        .expect("record exact serialized bytes");
    let attachment = build_attachment(&compiled, &serialization, id("attachment:1"))
        .expect("build model attachment");
    let delivery = observe_delivery(
        &attachment,
        id("delivery:1"),
        Some(codex_hepta_types::Digest32::of_bytes(&serialized_payload)),
        true,
        ContextDeliveryDispositionV2::Delivered,
        100,
    )
    .expect("terminal delivery observation");
    assert_eq!(delivery.expected_payload_digest, binding.payload_digest);
    assert_eq!(
        delivery.observed_payload_digest,
        Some(binding.payload_digest)
    );
}
