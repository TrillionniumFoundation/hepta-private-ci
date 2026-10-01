use super::*;
use crate::prompt_delivery::tests::admitted_registry_with_token_cost;
use crate::prompt_delivery::tests::canonical_selection;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("fixture ID: {error:?}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn request(exercise: PromptExerciseRequestV1) -> PromptContextCompileRequestV1 {
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
            maximum_context_tokens: 20_000,
        },
        exercise,
        compilation_id: id("compilation:public-fragment-bound"),
        token_budget: 20_000,
        truncation_policy_digest: digest("truncation"),
        base_candidates: Vec::new(),
        mandatory_groups: Vec::new(),
    }
}

#[test]
fn public_prompt_compiler_enforces_declared_fragment_bound_before_compilation() {
    for token_cost in [10_000, 10_001] {
        let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error:?}"));
        let (registry, tuple, _authority, _key, _now) = admitted_registry_with_token_cost(
            &temporary.path().join("registry"),
            b"Verify before mutation.",
            token_cost,
        );
        let selected = canonical_selection(&registry, &tuple, /*now*/ 100);
        let result = compile_exercised_prompt_context_v1(
            &registry,
            &selected.portfolio,
            request(selected.exercise_request.clone()),
        );
        if token_cost == 10_001 {
            assert_eq!(result, Err(PromptPipelineErrorV1::PromptFragmentTokenLimit));
            continue;
        }
        let prepared = result.unwrap_or_else(|error| panic!("item at declared cap: {error:?}"));
        prepared
            .compiled
            .validate()
            .unwrap_or_else(|error| panic!("valid context at cap: {error:?}"));
        let delivered = prepare_prompt_delivery_v1(
            &registry,
            &selected.portfolio,
            &prepared,
            PromptDeliveryPrepareRequestV1 {
                exercise: selected.exercise_request,
                serialization_id: id("serialization:public-fragment-bound"),
                serialized_payload: b"Verify before mutation.".to_vec(),
                attachment_id: id("attachment:public-fragment-bound"),
            },
        )
        .unwrap_or_else(|error| panic!("public delivery at declared cap: {error:?}"));
        assert_eq!(delivered.materialization, prepared.materialization);
    }
}

#[test]
fn public_prompt_delivery_checks_fragment_bound_before_receipt_rebinding() {
    let source = tempfile::tempdir().unwrap_or_else(|error| panic!("source tempdir: {error:?}"));
    let (registry, tuple, _authority, _key, _now) = admitted_registry_with_token_cost(
        &source.path().join("registry"),
        b"Verify before mutation.",
        /*token_cost*/ 10_000,
    );
    let selected = canonical_selection(&registry, &tuple, /*now*/ 100);
    let prepared = compile_exercised_prompt_context_v1(
        &registry,
        &selected.portfolio,
        request(selected.exercise_request),
    )
    .unwrap_or_else(|error| panic!("source context at cap: {error:?}"));
    let replacement =
        tempfile::tempdir().unwrap_or_else(|error| panic!("replacement tempdir: {error:?}"));
    let (replacement_registry, replacement_tuple, _authority, _key, _now) =
        admitted_registry_with_token_cost(
            &replacement.path().join("registry"),
            b"Verify before mutation.",
            /*token_cost*/ 10_001,
        );
    let replacement_selection =
        canonical_selection(&replacement_registry, &replacement_tuple, /*now*/ 100);
    assert_eq!(
        prepare_prompt_delivery_v1(
            &replacement_registry,
            &replacement_selection.portfolio,
            &prepared,
            PromptDeliveryPrepareRequestV1 {
                exercise: replacement_selection.exercise_request,
                serialization_id: id("serialization:oversized-replacement"),
                serialized_payload: b"Verify before mutation.".to_vec(),
                attachment_id: id("attachment:oversized-replacement"),
            },
        ),
        Err(PromptPipelineErrorV1::PromptFragmentTokenLimit)
    );
}

#[test]
fn public_prompt_delivery_rejects_oversized_payload_before_occurrence_scanning() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error:?}"));
    let (registry, tuple, _authority, _key, _now) = admitted_registry_with_token_cost(
        &temporary.path().join("registry"),
        b"Verify before mutation.",
        /*token_cost*/ 4,
    );
    let selected = canonical_selection(&registry, &tuple, /*now*/ 100);
    let prepared = compile_exercised_prompt_context_v1(
        &registry,
        &selected.portfolio,
        request(selected.exercise_request.clone()),
    )
    .unwrap_or_else(|error| panic!("genuine source compilation: {error:?}"));
    assert_eq!(
        prepare_prompt_delivery_v1(
            &registry,
            &selected.portfolio,
            &prepared,
            PromptDeliveryPrepareRequestV1 {
                exercise: selected.exercise_request,
                serialization_id: id("serialization:oversized-payload"),
                // No selected bytes occur. The size gate must run before the
                // occurrence scan could report SerializedPayloadMissing.
                serialized_payload: vec![0; MAX_SERIALIZED_PAYLOAD_BYTES_V2 + 1],
                attachment_id: id("attachment:oversized-payload"),
            },
        ),
        Err(PromptPipelineErrorV1::ContextCompiler(
            ContextCompilerV2Error::SerializedPayloadTooLarge.to_string(),
        ))
    );
}

#[test]
fn public_prompt_delivery_handles_maximum_repeated_prefix_missing_occurrence() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error:?}"));
    let mut source = vec![b'A'; codex_hepta_prompt_registry::MAX_REALIZATION_PAYLOAD_BYTES];
    let last = source.len() - 1;
    source[last] = b'B';
    let (registry, tuple, _authority, _key, _now) = admitted_registry_with_token_cost(
        &temporary.path().join("registry"),
        &source,
        /*token_cost*/ 4,
    );
    let selected = canonical_selection(&registry, &tuple, /*now*/ 100);
    let prepared = compile_exercised_prompt_context_v1(
        &registry,
        &selected.portfolio,
        request(selected.exercise_request.clone()),
    )
    .unwrap_or_else(|error| panic!("genuine repeated-prefix compilation: {error:?}"));
    assert_eq!(
        prepare_prompt_delivery_v1(
            &registry,
            &selected.portfolio,
            &prepared,
            PromptDeliveryPrepareRequestV1 {
                exercise: selected.exercise_request,
                serialization_id: id("serialization:repeated-prefix"),
                serialized_payload: vec![b'A'; MAX_SERIALIZED_PAYLOAD_BYTES_V2],
                attachment_id: id("attachment:repeated-prefix"),
            },
        ),
        Err(PromptPipelineErrorV1::SerializedPayloadMissing(
            "realization:verify".to_owned(),
        ))
    );
}

#[test]
fn public_prompt_delivery_records_the_first_of_multiple_source_occurrences() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error:?}"));
    let (registry, tuple, _authority, _key, _now) = admitted_registry_with_token_cost(
        &temporary.path().join("registry"),
        b"aba",
        /*token_cost*/ 4,
    );
    let selected = canonical_selection(&registry, &tuple, /*now*/ 100);
    let prepared = compile_exercised_prompt_context_v1(
        &registry,
        &selected.portfolio,
        request(selected.exercise_request.clone()),
    )
    .unwrap_or_else(|error| panic!("genuine source compilation: {error:?}"));
    let delivered = prepare_prompt_delivery_v1(
        &registry,
        &selected.portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise: selected.exercise_request,
            serialization_id: id("serialization:first-occurrence"),
            serialized_payload: b"first|aba|second|aba".to_vec(),
            attachment_id: id("attachment:first-occurrence"),
        },
    )
    .unwrap_or_else(|error| panic!("genuine ordered source delivery: {error:?}"));
    assert_eq!(
        delivered.serialization_proof.occurrences,
        vec![PromptSerializationOccurrenceV1 {
            realization_id: id("realization:verify"),
            payload_digest: Digest32::of_bytes(b"aba"),
            start_offset: 6,
            end_offset: 9,
        }]
    );
}
