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
    let delivery = prepare_prompt_delivery_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise,
            serialization_id: id("serialization:1"),
            serialized_payload: serialized_payload.clone(),
            attachment_id: id("attachment:1"),
        },
    )
    .expect("prepare delivery");
    assert_eq!(delivery.serialized_payload, serialized_payload);
    assert_eq!(delivery.materialization, prepared.materialization);
    assert_eq!(delivery.serialization.payload_digest(), payload_digest);
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
    let error = prepare_prompt_delivery_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise,
            serialization_id: id("serialization:drift"),
            serialized_payload: b"payload:a".to_vec(),
            attachment_id: id("attachment:drift"),
        },
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

    let error = prepare_prompt_delivery_v1(
        &registry,
        &portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise,
            serialization_id: id("serialization:missing-prompt"),
            serialized_payload: b"provider-request-without-selected-realization".to_vec(),
            attachment_id: id("attachment:missing-prompt"),
        },
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
    let error = prepare_prompt_delivery_v1(
        &registry,
        &selected.portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise: selected.exercise_request,
            serialization_id: id("serialization:revoked"),
            serialized_payload: b"payload:a".to_vec(),
            attachment_id: id("attachment:revoked"),
        },
    )
    .expect_err("revocation must block attachment");
    assert_eq!(
        error,
        PromptPipelineErrorV1::ExerciseRejected(
            codex_hepta_prompt_optimizer::canonical::PromptExerciseActionV1::RejectStale
        )
    );
}

// Controlled count fixtures only; these do not install a provider tokenizer.

struct SuppliedTokenizer {
    identity: Digest32,
    selected_count: u64,
    serialized_payload: Vec<u8>,
    serialized_count: u64,
}

impl ExactTokenizerV2 for SuppliedTokenizer {
    fn tokenizer_digest(&self) -> Digest32 {
        self.identity
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        if bytes == b"payload:a" {
            return Ok(self.selected_count);
        }
        if bytes == self.serialized_payload {
            return Ok(self.serialized_count);
        }
        Err(ContextCompilerV2Error::InvalidSerializedTokenCount)
    }
}

fn tokenizer_fixture(
    prepared: &PreparedPromptContextV1,
    payload: &[u8],
    serialized_count: u64,
) -> SuppliedTokenizer {
    SuppliedTokenizer {
        identity: prepared.model_profile.tokenizer_digest,
        selected_count: u64::from(prepared.materialization.payloads[0].binding.token_cost),
        serialized_payload: payload.to_vec(),
        serialized_count,
    }
}

fn tokenizer_request(
    exercise: PromptExerciseRequestV1,
    payload: &[u8],
) -> PromptDeliveryPrepareRequestV1 {
    PromptDeliveryPrepareRequestV1 {
        exercise,
        serialization_id: id("serialization:profile-tokenizer"),
        serialized_payload: payload.to_vec(),
        attachment_id: id("attachment:profile-tokenizer"),
    }
}

#[test]
fn supplied_tokenizer_counts_the_complete_serialization_and_preserves_compatibility() {
    let (_temp, registry, portfolio, exercise) = fixture();
    let prepared = compile_exercised_prompt_context_v1(
        &registry,
        &portfolio,
        compile_request(exercise.clone()),
    )
    .expect("compile");
    let payload = b"provider-prefix|payload:a|provider-suffix";
    let tokenizer = tokenizer_fixture(&prepared, payload, 41);
    let request = tokenizer_request(exercise, payload);
    let compatibility =
        prepare_prompt_delivery_v1(&registry, &portfolio, &prepared, request.clone())
            .expect("compatibility delivery");
    let exact = crate::prepare_prompt_delivery_with_tokenizer_v1(
        &registry, &portfolio, &prepared, request, &tokenizer,
    )
    .expect("profile tokenizer delivery");
    assert_eq!(
        compatibility.serialization.serialized_token_count(),
        tokenizer.selected_count
    );
    assert_eq!(exact.serialization.serialized_token_count(), 41);
    assert_eq!(exact.serialized_payload, payload);
    assert_eq!(exact.serialization_proof, compatibility.serialization_proof);
    assert_eq!(exact.materialization, compatibility.materialization);
    assert_ne!(exact.serialization, compatibility.serialization);
    assert!(!exact.attachment.authority().grants_any());
}

#[test]
fn supplied_tokenizer_rejects_framing_overflow_even_when_registered_fragments_fit() {
    let (_temp, registry, portfolio, exercise) = fixture();
    let mut compilation = compile_request(exercise.clone());
    compilation.token_budget = 16;
    let prepared = compile_exercised_prompt_context_v1(&registry, &portfolio, compilation)
        .expect("selected fragments fit");
    let payload = b"provider-prefix|payload:a|provider-suffix";
    let tokenizer = tokenizer_fixture(&prepared, payload, 17);
    let request = tokenizer_request(exercise, payload);
    assert!(prepare_prompt_delivery_v1(&registry, &portfolio, &prepared, request.clone()).is_ok());
    let result = crate::prepare_prompt_delivery_with_tokenizer_v1(
        &registry, &portfolio, &prepared, request, &tokenizer,
    );
    assert!(
        matches!(result, Err(PromptPipelineErrorV1::ContextCompiler(error))
        if error.contains("SerializedTokenBudgetExceeded"))
    );
}

#[test]
fn supplied_tokenizer_rejects_registered_item_count_drift_and_profile_drift() {
    let (_temp, registry, portfolio, exercise) = fixture();
    let prepared = compile_exercised_prompt_context_v1(
        &registry,
        &portfolio,
        compile_request(exercise.clone()),
    )
    .expect("compile");
    let payload = b"provider-prefix|payload:a|provider-suffix";
    let mut tokenizer = tokenizer_fixture(&prepared, payload, 41);
    let registered = tokenizer.selected_count;
    tokenizer.selected_count += 1;
    let request = tokenizer_request(exercise, payload);
    let result = crate::prepare_prompt_delivery_with_tokenizer_v1(
        &registry,
        &portfolio,
        &prepared,
        request.clone(),
        &tokenizer,
    );
    assert_eq!(
        result,
        Err(PromptPipelineErrorV1::SelectedTokenCountMismatch {
            realization_id: "realization:verify".to_string(),
            registered,
            observed: registered + 1,
        })
    );
    tokenizer.selected_count = registered;
    tokenizer.identity = digest("different-tokenizer");
    let result = crate::prepare_prompt_delivery_with_tokenizer_v1(
        &registry, &portfolio, &prepared, request, &tokenizer,
    );
    assert!(
        matches!(result, Err(PromptPipelineErrorV1::ContextCompiler(error))
        if error.contains("TokenizerProfileMismatch"))
    );
}

#[test]
fn supplied_tokenizer_keeps_registry_revocation_and_selected_byte_checks() {
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
    let payload = b"provider-prefix|payload:a|provider-suffix";
    let tokenizer = tokenizer_fixture(&prepared, payload, 41);
    let absent = crate::prepare_prompt_delivery_with_tokenizer_v1(
        &registry,
        &selected.portfolio,
        &prepared,
        tokenizer_request(
            selected.exercise_request.clone(),
            b"no-selected-realization",
        ),
        &tokenizer,
    );
    assert_eq!(
        absent,
        Err(PromptPipelineErrorV1::SerializedPayloadMissing(
            "realization:verify".to_string(),
        ))
    );
    revoke_registry(&mut registry, &authority, &signing_key, now);
    let revoked = crate::prepare_prompt_delivery_with_tokenizer_v1(
        &registry,
        &selected.portfolio,
        &prepared,
        tokenizer_request(selected.exercise_request, payload),
        &tokenizer,
    );
    assert_eq!(
        revoked,
        Err(PromptPipelineErrorV1::ExerciseRejected(
            codex_hepta_prompt_optimizer::canonical::PromptExerciseActionV1::RejectStale,
        ))
    );
}
