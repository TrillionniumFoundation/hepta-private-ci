use super::*;

use codex_hepta_prompt_registry::AdmissionAuthority;
use codex_hepta_prompt_registry::AdmissionBindingV1;
use codex_hepta_prompt_registry::AdmissionGrantV1;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::SignedAdmissionGrantV1;
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
) -> (DurablePromptRegistry, PromptModelTupleV2) {
    let mut registry =
        DurablePromptRegistry::open_state_dir(root, 64).expect("open durable registry");
    let factor = PromptFactor {
        factor_id: id("factor:verify"),
        proposer_id: id("proposer:1"),
        semantic_version: id("v1"),
        content_digest: digest("factor:verify"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    registry
        .register_factor(factor.clone())
        .expect("register factor");

    let signing_key = SigningKey::from_bytes(&[23; 32]);
    let authority = AdmissionAuthority::new(
        id("review-authority:prompt"),
        signing_key.verifying_key().to_bytes(),
    )
    .expect("admission authority");
    let grant = AdmissionGrantV1 {
        schema_version: 1,
        signer_id: "review-authority:prompt".to_owned(),
        grant_id: "admission:prompt:1".to_owned(),
        binding: AdmissionBindingV1 {
            factor_id: factor.factor_id.to_string(),
            factor_content_sha256: factor.content_digest.into_array(),
            reviewer_id: "reviewer:1".to_owned(),
            reviewed_scope_sha256: digest("scope:prompt").into_array(),
            evidence_sha256: digest("evidence:prompt").into_array(),
        },
        not_before_unix_ms: 10,
        expires_at_unix_ms: 1_000,
    };
    let signature = signing_key
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let verified = authority
        .verify(
            &SignedAdmissionGrantV1 { grant, signature },
            &factor,
            digest("scope:prompt"),
            20,
        )
        .expect("verify admission");
    registry
        .admit_factor_verified(verified, 20)
        .expect("admit factor");

    let tuple = PromptModelTupleV2 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
    };
    let binding = PromptRealizationBindingV2 {
        realization_id: id("realization:verify"),
        factor_id: factor.factor_id,
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
    registry
        .register_realization_payload_v2(binding, payload.to_vec(), None)
        .expect("register actual payload");
    (registry, tuple)
}

#[test]
fn durable_registry_payload_is_the_context_compiler_candidate() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-registry");
    let payload = b"Inspect evidence before mutation.";
    let (registry, tuple) = admitted_registry(&root, payload);
    let vector = digest("generation-vector");
    let snapshot = registry.snapshot_v2(vector, &tuple).expect("snapshot");

    let output = compile_prompt_registry_v2(
        &registry,
        PromptRegistryCompilationRequestV2 {
            compilation_id: id("compilation:prompt:1"),
            serialization_id: id("serialization:prompt:1"),
            attachment_id: id("attachment:prompt:1"),
            objective_digest: digest("objective"),
            prompt_portfolio_digest: digest("portfolio"),
            generation_vector_digest: vector,
            expected_registry_snapshot: snapshot,
            registry_model_tuple: tuple.clone(),
            context_model_profile: ContextModelProfileV2 {
                model_digest: tuple.model_digest,
                tokenizer_digest: tuple.tokenizer_digest,
                template_digest: tuple.template_digest,
                tool_schema_digest: tuple.tool_schema_digest,
                maximum_context_tokens: 128,
            },
            now_unix_ms: 30,
            required_factor_ids: vec![id("factor:verify")],
            maximum_realizations: 8,
            token_budget: 128,
            truncation_policy_digest: digest("truncation"),
        },
    )
    .expect("compile prompt registry context");

    assert_eq!(
        output.compiled.receipt.selected_item_ids,
        vec![id("realization:verify")]
    );
    assert_eq!(output.selected_deliveries.len(), 1);
    assert_eq!(output.selected_deliveries[0].payload, payload);
    assert_eq!(
        output.compiled.selected_candidates[0].content_digest,
        Digest32::of_bytes(payload)
    );
    assert_eq!(
        output.compiled.selected_candidates[0].trusted_admission_digest,
        registry.registry().admission_event_digest(&id("factor:verify"))
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
    output.validate().expect("compiled delivery validates");
}

#[test]
fn compiler_rejects_registry_and_context_model_drift() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-registry");
    let (registry, tuple) = admitted_registry(&root, b"Bound instruction");
    let vector = digest("generation-vector");
    let snapshot = registry.snapshot_v2(vector, &tuple).expect("snapshot");
    let error = compile_prompt_registry_v2(
        &registry,
        PromptRegistryCompilationRequestV2 {
            compilation_id: id("compilation:prompt:2"),
            serialization_id: id("serialization:prompt:2"),
            attachment_id: id("attachment:prompt:2"),
            objective_digest: digest("objective"),
            prompt_portfolio_digest: digest("portfolio"),
            generation_vector_digest: vector,
            expected_registry_snapshot: snapshot,
            registry_model_tuple: tuple.clone(),
            context_model_profile: ContextModelProfileV2 {
                model_digest: digest("other-model"),
                tokenizer_digest: tuple.tokenizer_digest,
                template_digest: tuple.template_digest,
                tool_schema_digest: tuple.tool_schema_digest,
                maximum_context_tokens: 128,
            },
            now_unix_ms: 30,
            required_factor_ids: vec![id("factor:verify")],
            maximum_realizations: 8,
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
