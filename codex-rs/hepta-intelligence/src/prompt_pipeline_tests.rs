use super::*;

use codex_hepta_context_compiler::ContextDeliveryDispositionV2;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

/// Deterministic byte tokenizer supplied only by these unit fixtures. Product
/// callers must provide the real backend for the selected model profile.
struct ByteTokenizer;

impl codex_hepta_context_compiler::ExactTokenizerV2 for ByteTokenizer {
    fn tokenizer_digest(&self) -> Digest32 {
        digest("tokenizer")
    }

    fn count_tokens(
        &self,
        bytes: &[u8],
    ) -> Result<u64, codex_hepta_context_compiler::ContextCompilerV2Error> {
        Ok(u64::try_from(bytes.len()).unwrap_or(u64::MAX))
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

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
    let prepared = compile_exercised_prompt_context_with_tokenizer_v1(
        &registry,
        &portfolio,
        compile_request(exercise.clone()),
        &ByteTokenizer,
    )
    .expect("compile exercised portfolio");
    assert_eq!(
        prepared.compiled.receipt().selected_item_ids(),
        vec![id("realization:verify")]
    );
    assert!(!prepared.compiled.receipt().authority().grants_any());
    // The registry fixture declares cost 4; exact bytes contain 9 tokens.
    assert_eq!(prepared.compiled.receipt().used_tokens(), 9);
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
        &ByteTokenizer,
    )
    .expect("prepare delivery");
    assert_eq!(delivery.serialized_payload, serialized_payload);
    assert_eq!(delivery.materialization, prepared.materialization);
    assert_eq!(delivery.serialization.payload_digest(), payload_digest);
    assert_eq!(
        delivery.serialization.serialized_token_count(),
        serialized_payload.len() as u64
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
    let mut prepared = compile_exercised_prompt_context_with_tokenizer_v1(
        &registry,
        &portfolio,
        compile_request(exercise.clone()),
        &ByteTokenizer,
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
        &ByteTokenizer,
    )
    .expect_err("materialization drift");
    assert_eq!(error, PromptPipelineErrorV1::PayloadMaterializationDrift);
}

#[test]
fn serialization_without_selected_prompt_bytes_fails_closed() {
    let (_temp, registry, portfolio, exercise) = fixture();
    let prepared = compile_exercised_prompt_context_with_tokenizer_v1(
        &registry,
        &portfolio,
        compile_request(exercise.clone()),
        &ByteTokenizer,
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
        &ByteTokenizer,
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
    let prepared = compile_exercised_prompt_context_with_tokenizer_v1(
        &registry,
        &selected.portfolio,
        compile_request(selected.exercise_request.clone()),
        &ByteTokenizer,
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
        &ByteTokenizer,
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
fn serialized_framing_is_counted_by_the_exact_backend() {
    let (_temp, registry, portfolio, exercise) = fixture();
    let mut request = compile_request(exercise.clone());
    request.token_budget = 9;
    let prepared = compile_exercised_prompt_context_with_tokenizer_v1(
        &registry,
        &portfolio,
        request,
        &ByteTokenizer,
    )
    .expect("the exact selected bytes fit");
    let mut payload = b"payload:a".to_vec();
    payload.extend(std::iter::repeat_n(b'!', 100_000));
    let error = prepare_prompt_delivery_with_tokenizer_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise,
            serialization_id: id("serialization:framing"),
            serialized_payload: payload,
            attachment_id: id("attachment:framing"),
        },
        &ByteTokenizer,
    )
    .expect_err("framing cannot bypass the exact final budget");
    assert_eq!(
        error,
        PromptPipelineErrorV1::ContextCompiler(format!(
            "{:?}",
            codex_hepta_context_compiler::ContextCompilerV2Error::SerializedTokenBudgetExceeded {
                serialized_tokens: 100_009,
                token_budget: 9,
            }
        ))
    );
}

#[test]
fn compatibility_entries_require_an_exact_tokenizer_capability() {
    let (_temp, registry, portfolio, exercise) = fixture();
    assert_eq!(
        compile_exercised_prompt_context_v1(
            &registry,
            &portfolio,
            compile_request(exercise.clone()),
        ),
        Err(PromptPipelineErrorV1::ExactTokenizerUnavailable)
    );
    let prepared = compile_exercised_prompt_context_with_tokenizer_v1(
        &registry,
        &portfolio,
        compile_request(exercise.clone()),
        &ByteTokenizer,
    )
    .expect("explicit fixture backend");
    assert_eq!(
        prepare_prompt_delivery_v1(
            &registry,
            &portfolio,
            &prepared,
            PromptDeliveryPrepareRequestV1 {
                exercise,
                serialization_id: id("serialization:no-backend"),
                serialized_payload: b"payload:a".to_vec(),
                attachment_id: id("attachment:no-backend"),
            },
        ),
        Err(PromptPipelineErrorV1::ExactTokenizerUnavailable)
    );
}
