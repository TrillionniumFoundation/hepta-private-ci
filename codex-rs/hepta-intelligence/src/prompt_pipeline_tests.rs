use super::*;

use codex_hepta_context_compiler::ContextDeliveryDispositionV2;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

use crate::prompt_delivery::tests::ByteTokenizer;
use crate::prompt_delivery::tests::admitted_registry;
use crate::prompt_delivery::tests::canonical_selection;
use crate::prompt_delivery::tests::revoke_registry;

fn fixture() -> (
    tempfile::TempDir,
    DurablePromptRegistry,
    SelectedPromptPortfolioV1,
    PromptExerciseRequestV1,
) {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, tuple, _, _, _) = admitted_registry(&temp.path().join("registry"), b"payload:a");
    let selected = canonical_selection(&registry, &tuple, 100);
    (
        temp,
        registry,
        selected.portfolio,
        selected.exercise_request,
    )
}

fn compile_request(exercise: PromptExerciseRequestV1) -> PromptContextCompileRequestV1 {
    let tuple = &exercise.model_tuple;
    PromptContextCompileRequestV1 {
        model_profile: ContextModelProfileV2 {
            model_digest: tuple.model_digest,
            provider_id_digest: digest("provider"),
            provider_model_digest: tuple.model_digest,
            tokenizer_digest: tuple.tokenizer_digest,
            serializer_digest: digest("serializer"),
            template_digest: tuple.template_digest,
            tool_schema_digest: tuple.tool_schema_digest,
            maximum_context_tokens: 4096,
        },
        exercise,
        compilation_id: id("compilation:1"),
        token_budget: 128,
        truncation_policy_digest: digest("truncation"),
        base_candidates: Vec::new(),
        mandatory_groups: Vec::new(),
    }
}

#[test]
fn exercised_portfolio_compiles_attaches_and_observes_exact_delivery() {
    let (_temp, registry, portfolio, exercise) = fixture();
    let prepared = compile_exercised_prompt_context_v1(
        &registry,
        &portfolio,
        compile_request(exercise.clone()),
    )
    .expect("compile exercised portfolio");
    assert_eq!(
        prepared.compiled.receipt().selected_item_ids(),
        vec![id("realization:verify")]
    );
    assert!(!prepared.compiled.receipt().authority().grants_any());
    assert_eq!(prepared.materialization.payloads.len(), 1);
    assert_eq!(
        prepared.materialization.payloads[0].payload,
        b"payload:a".to_vec()
    );
    assert!(!prepared.materialization.authority.grants_any());

    let serialized_payload = b"provider-prefix|payload:a|provider-suffix".to_vec();
    let payload_digest = Digest32::of_bytes(&serialized_payload);
    let delivery = prepare_prompt_delivery_with_tokenizer_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise,
            serialization_id: id("serialization:1"),
            serialized_payload: serialized_payload.clone(),
            attachment_id: id("attachment:1"),
        },
        &ByteTokenizer(prepared.model_profile.tokenizer_digest),
    )
    .expect("prepare delivery");
    delivery.validate().expect("complete owner lineage");
    let mut changed = delivery.clone();
    changed.exercise.policy_digest = digest("substituted-policy");
    assert!(changed.validate().is_err());
    let mut changed = delivery.clone();
    changed.serialized_payload[0] ^= 1;
    assert!(changed.validate().is_err());
    let mut changed = delivery.clone();
    changed.serialization_proof.occurrences[0].start_offset += 1;
    changed.serialization_proof.proof_digest =
        prompt_serialization_proof_digest(&changed.serialization_proof);
    changed
        .serialization_proof
        .validate()
        .expect("internally consistent forged proof");
    assert!(changed.validate().is_err());
    assert_eq!(delivery.serialized_payload, serialized_payload);
    assert_eq!(delivery.materialization, prepared.materialization);
    assert_eq!(delivery.serialization.payload_digest(), payload_digest);
    assert_eq!(
        delivery.serialization.serialized_token_count(),
        u64::try_from(serialized_payload.len()).expect("payload length"),
    );
    assert_eq!(delivery.serialization_proof.occurrences.len(), 1);
    assert_eq!(
        delivery.serialization_proof.occurrences[0].realization_id,
        id("realization:verify")
    );
    assert!(!delivery.serialization_proof.authority.grants_any());
    assert!(!delivery.attachment.authority().grants_any());

    let observation = observe_prompt_delivery_v1(
        &delivery,
        id("delivery-observation:1"),
        Some(payload_digest),
        true,
        ContextDeliveryDispositionV2::Delivered,
        102,
    );
    assert_eq!(
        observation,
        Err(PromptPipelineErrorV1::ProviderEvidenceRequired)
    );
}

#[test]
fn materialization_drift_after_compilation_blocks_attachment_preparation() {
    let (_temp, registry, portfolio, exercise) = fixture();
    let mut prepared = compile_exercised_prompt_context_v1(
        &registry,
        &portfolio,
        compile_request(exercise.clone()),
    )
    .expect("compile");
    prepared.materialization.payloads[0].payload = b"tampered".to_vec();
    let error = prepare_prompt_delivery_with_tokenizer_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise,
            serialization_id: id("serialization:drift"),
            serialized_payload: b"payload:a".to_vec(),
            attachment_id: id("attachment:drift"),
        },
        &ByteTokenizer(prepared.model_profile.tokenizer_digest),
    )
    .expect_err("materialization drift");
    assert_eq!(error, PromptPipelineErrorV1::PayloadMaterializationDrift);
}

#[test]
fn serialization_without_selected_prompt_bytes_fails_closed() {
    let (_temp, registry, portfolio, exercise) = fixture();
    let prepared = compile_exercised_prompt_context_v1(
        &registry,
        &portfolio,
        compile_request(exercise.clone()),
    )
    .expect("compile exercised portfolio");

    let error = prepare_prompt_delivery_with_tokenizer_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise,
            serialization_id: id("serialization:missing-prompt"),
            serialized_payload: b"provider-request-without-selected-realization".to_vec(),
            attachment_id: id("attachment:missing-prompt"),
        },
        &ByteTokenizer(prepared.model_profile.tokenizer_digest),
    )
    .expect_err("missing selected prompt bytes must fail");
    assert_eq!(
        error,
        PromptPipelineErrorV1::SerializedPayloadMissing("realization:verify".to_string())
    );
}

#[test]
fn revocation_after_compilation_blocks_attachment_preparation() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, tuple, authority, signing_key, now) =
        admitted_registry(&temp.path().join("registry"), b"payload:a");
    let selected = canonical_selection(&registry, &tuple, 100);
    let prepared = compile_exercised_prompt_context_v1(
        &registry,
        &selected.portfolio,
        compile_request(selected.exercise_request.clone()),
    )
    .expect("compile");
    revoke_registry(&mut registry, &authority, &signing_key, now);
    let error = prepare_prompt_delivery_with_tokenizer_v1(
        &registry,
        &selected.portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise: selected.exercise_request,
            serialization_id: id("serialization:revoked"),
            serialized_payload: b"payload:a".to_vec(),
            attachment_id: id("attachment:revoked"),
        },
        &ByteTokenizer(prepared.model_profile.tokenizer_digest),
    )
    .expect_err("revocation must block attachment");
    assert_eq!(
        error,
        PromptPipelineErrorV1::ExerciseRejected(
            codex_hepta_prompt_optimizer::canonical::PromptExerciseActionV1::RejectStale
        )
    );
}

#[test]
fn legacy_delivery_and_registry_compilation_require_an_exact_tokenizer() {
    let (_temp, registry, portfolio, exercise) = fixture();
    let context_request = compile_request(exercise.clone());
    let prepared =
        compile_exercised_prompt_context_v1(&registry, &portfolio, context_request.clone())
            .expect("compile");
    let error = prepare_prompt_delivery_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise: exercise.clone(),
            serialization_id: id("serialization:legacy"),
            serialized_payload: b"provider-prefix|payload:a|provider-suffix".to_vec(),
            attachment_id: id("attachment:legacy"),
        },
    )
    .expect_err("registry costs cannot attest serialized token count");
    assert_eq!(error, PromptPipelineErrorV1::MissingExactTokenizer);

    let error = crate::compile_prompt_registry_v2(
        &registry,
        &portfolio,
        &exercise,
        crate::PromptRegistryCompilationRequestV2 {
            compilation_id: id("compilation:legacy"),
            serialization_id: id("serialization:legacy"),
            attachment_id: id("attachment:legacy"),
            registry_model_tuple: portfolio.model_tuple.clone(),
            context_model_profile: context_request.model_profile,
            now_unix_ms: exercise.now_unix_ms,
            token_budget: context_request.token_budget,
            truncation_policy_digest: context_request.truncation_policy_digest,
        },
    )
    .expect_err("legacy registry compilation cannot attest serialized count");
    assert!(matches!(
        error,
        crate::PromptRegistryCompilationErrorV2::Pipeline(
            PromptPipelineErrorV1::MissingExactTokenizer
        )
    ));
}

#[test]
fn exact_delivery_tokenizer_counts_framing_against_the_budget() {
    let (_temp, registry, portfolio, exercise) = fixture();
    let prepared = compile_exercised_prompt_context_v1(
        &registry,
        &portfolio,
        compile_request(exercise.clone()),
    )
    .expect("compile");
    let mut serialized_payload = vec![b'x'; 200];
    serialized_payload.extend_from_slice(b"payload:a");
    let error = prepare_prompt_delivery_with_tokenizer_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise,
            serialization_id: id("serialization:over-budget"),
            serialized_payload,
            attachment_id: id("attachment:over-budget"),
        },
        &ByteTokenizer(prepared.model_profile.tokenizer_digest),
    )
    .expect_err("physical framing exceeds the 128-token budget");
    assert!(matches!(
        error,
        PromptPipelineErrorV1::ContextCompiler(ref message)
            if message.contains("SerializedTokenBudgetExceeded")
    ));
}

#[test]
fn exact_delivery_rejects_tokenizer_profile_substitution() {
    let (_temp, registry, portfolio, exercise) = fixture();
    let prepared = compile_exercised_prompt_context_v1(
        &registry,
        &portfolio,
        compile_request(exercise.clone()),
    )
    .expect("compile");
    let error = prepare_prompt_delivery_with_tokenizer_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise,
            serialization_id: id("serialization:wrong-tokenizer"),
            serialized_payload: b"payload:a".to_vec(),
            attachment_id: id("attachment:wrong-tokenizer"),
        },
        &ByteTokenizer(digest("unrelated-tokenizer")),
    )
    .expect_err("an unrelated tokenizer cannot attest this model profile");
    assert!(matches!(
        error,
        PromptPipelineErrorV1::ContextCompiler(ref message)
            if message.contains("TokenizerProfileMismatch")
    ));
}
