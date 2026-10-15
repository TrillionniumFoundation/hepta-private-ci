use super::*;

use codex_hepta_infer_core::shared_feature_v2::SharedFeatureIdentityV2;
use crate::model_worker::SequenceAttentionPolicyV3;
use crate::model_worker::SequenceHeadBindingV3;
use crate::model_worker::SequenceHeadParametersV3;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn nonzero(text: &[u8]) -> Digest32 {
    Digest32::of_bytes(text)
}

fn profile(modality: FeatureModalityV3) -> FrozenProjectionProfileV4 {
    FrozenProjectionProfileV4 {
        input_width: 2,
        output_width: 2,
        weights_q24: vec![Q24, 0, 0, Q24],
        bias_q24: vec![0, 0],
        modality,
        tokenizer_digest: nonzero(b"tokenizer"),
        normalizer_digest: nonzero(b"normalizer"),
        quantization_digest: nonzero(b"quantizer"),
        preprocessing_digest: nonzero(b"preprocessor"),
        adapter_digest: nonzero(b"adapter"),
    }
}

fn source(
    model: &FrozenQ24ProjectionStemV4,
    modality: FeatureModalityV3,
) -> StemSourceSequenceV4 {
    let identity = FeatureSequenceIdentityV3 {
        base: SharedFeatureIdentityV2 {
            principal_id: StableId::new("principal:a").expect("principal"),
            purpose_id: StableId::new("reasoning").expect("purpose"),
            generation: Generation::new(7).expect("generation"),
            authority_epoch: 4,
            encoder_digest: model.digest(),
            tokenizer_digest: model.profile.tokenizer_digest,
            normalizer_digest: model.profile.normalizer_digest,
            quantization_digest: model.profile.quantization_digest,
            input_digest: nonzero(b"temporary input binding"),
        },
        modality,
        preprocessing_digest: model.profile.preprocessing_digest,
        adapter_digest: model.profile.adapter_digest,
    };
    let mut request = StemSourceSequenceV4 {
        identity,
        source_bytes: b"full original question and answer choices".to_vec(),
        input_width: 2,
        values_q24: vec![Q24, 0, 0, Q24],
        mask: vec![1, 1],
        coordinates: vec![FeatureCoordinatesV3::default(); 2],
        expires_at_ms: 1000,
    };
    request.identity.base.input_digest =
        canonical_stem_source_digest_v4(&request).expect("full source");
    request
}

fn head(
    model: &FrozenQ24ProjectionStemV4,
    id: &str,
    causal: bool,
    projection: Vec<i64>,
) -> Arc<SequenceCellHeadV3> {
    Arc::new(
        SequenceCellHeadV3::new(
            SequenceHeadBindingV3 {
                cell_id: StableId::new(id).expect("Cell"),
                encoder_digest: model.digest(),
                tokenizer_digest: model.profile.tokenizer_digest,
                normalizer_digest: model.profile.normalizer_digest,
                quantization_digest: model.profile.quantization_digest,
                preprocessing_digest: model.profile.preprocessing_digest,
                adapter_digest: model.profile.adapter_digest,
                modality: model.profile.modality,
                attention: if causal {
                    SequenceAttentionPolicyV3::Causal
                } else {
                    SequenceAttentionPolicyV3::Bidirectional
                },
            },
            SequenceHeadParametersV3 {
                query_q24: vec![Q24, 0],
                key_q24: vec![0, Q24],
                value_q24: projection,
                local_q24: vec![0, Q24],
                bias_q24: 0,
            },
        )
        .expect("frozen head"),
    )
}

#[test]
fn actual_single_projection_forward_feeds_two_independently_weighted_cells() {
    let mut model = FrozenQ24ProjectionStemV4::new(profile(FeatureModalityV3::Text))
        .expect("fixed weights");
    let input = source(&model, FeatureModalityV3::Text);
    let heads = vec![
        head(&model, "cell:1", true, vec![Q24, 0]),
        head(&model, "cell:2", true, vec![0, Q24]),
    ];
    let result = model.encode_and_read(&input, &heads, 10, 50).expect("physical batch");
    assert_eq!(result.encoder_forwards_this_batch, 1);
    assert_eq!(result.encoder_macs_this_batch, 8);
    assert_eq!(result.cumulative_encoder_forwards, 1);
    assert_eq!(result.cumulative_encoder_macs, 8);
    assert_eq!(result.reader.cells.len(), 2);
    assert_eq!(result.reader.cells[0].score_q24, 10_485_760);
    assert_ne!(
        result.reader.cells[0].score_q24,
        result.reader.cells[1].score_q24
    );
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(result.reader.authority, AuthorityPosture::DENY_ALL);
    assert!(!result.receipt_digest.is_zero());
    assert_eq!(model.completed_forwards(), 1);
    let repeated = model.encode_and_read(&input, &heads, 10, 50).expect("repeated");
    assert_eq!(repeated.cumulative_encoder_forwards, 2);
    assert_eq!(model.completed_macs(), 16);
    assert_ne!(result.receipt_digest, repeated.receipt_digest);
}

#[test]
fn reversed_source_changes_full_digest_and_causal_reader_prediction() {
    let mut model = FrozenQ24ProjectionStemV4::new(profile(FeatureModalityV3::Text))
        .expect("model");
    let cell = head(&model, "cell:1", true, vec![Q24, 0]);
    let a = source(&model, FeatureModalityV3::Text);
    let mut b = a.clone();
    b.values_q24 = vec![0, Q24, Q24, 0];
    b.identity.base.input_digest = canonical_stem_source_digest_v4(&b).expect("new input");
    let first = model.encode_and_read(&a, &[Arc::clone(&cell)], 10, 20)
        .expect("first");
    let second = model.encode_and_read(&b, &[cell], 10, 20).expect("second");
    assert_eq!(first.reader.cells[0].score_q24, 10_485_760);
    assert_eq!(second.reader.cells[0].score_q24, 5_592_405);
    assert_ne!(first.source_digest, second.source_digest);
    assert_ne!(first.feature_content_digest, second.feature_content_digest);
}

#[test]
fn altered_original_source_bytes_or_numeric_rows_cannot_reuse_digest() {
    let mut model = FrozenQ24ProjectionStemV4::new(profile(FeatureModalityV3::Text))
        .expect("model");
    let reference = source(&model, FeatureModalityV3::Text);
    let cell = head(&model, "cell:1", true, vec![Q24, 0]);
    let mut altered = reference.clone();
    altered.source_bytes.extend_from_slice(b" plus one word");
    assert_eq!(
        model.encode_and_read(&altered, &[Arc::clone(&cell)], 10, 20),
        Err(StemPhysicalErrorV4::SourceIdentityMismatch),
    );
    altered = reference.clone();
    altered.values_q24[0] += 1;
    assert_eq!(
        model.encode_and_read(&altered, &[cell], 10, 20),
        Err(StemPhysicalErrorV4::SourceIdentityMismatch),
    );
    assert_eq!(model.completed_forwards(), 0);
}

#[test]
fn new_preprocessor_or_model_parameters_are_not_interchangeable() {
    let original = FrozenQ24ProjectionStemV4::new(profile(FeatureModalityV3::Text))
        .expect("model");
    let mut changed = profile(FeatureModalityV3::Text);
    changed.weights_q24[0] = Q24 / 2;
    let mut other = FrozenQ24ProjectionStemV4::new(changed).expect("new weights");
    assert_ne!(original.digest(), other.digest());
    let input = source(&original, FeatureModalityV3::Text);
    let cell = head(&other, "cell:1", true, vec![Q24, 0]);
    assert_eq!(
        other.encode_and_read(&input, &[cell], 10, 20),
        Err(StemPhysicalErrorV4::IncompatibleModel),
    );
    assert_eq!(other.completed_forwards(), 0);
    let mut old = FrozenQ24ProjectionStemV4::new(profile(FeatureModalityV3::Text))
        .expect("original");
    let mut invalid = input.clone();
    invalid.identity.preprocessing_digest = nonzero(b"changed feature profile");
    let cell = head(&old, "cell:a", true, vec![Q24, 0]);
    assert_eq!(
        old.encode_and_read(&invalid, &[cell], 10, 20),
        Err(StemPhysicalErrorV4::IncompatibleModel),
    );
    assert_eq!(old.completed_forwards(), 0);
}

#[test]
fn temporal_coordinates_are_used_by_reader_and_bound_to_original_source() {
    let mut model = FrozenQ24ProjectionStemV4::new(profile(FeatureModalityV3::Audio))
        .expect("audio model");
    let original = source(&model, FeatureModalityV3::Audio);
    let mut delayed = original.clone();
    delayed.coordinates[1].time_micros = 500_000;
    delayed.identity.base.input_digest =
        canonical_stem_source_digest_v4(&delayed).expect("coordinate-bound");
    let head = head(&model, "cell:audio", false, vec![Q24, 0]);
    let a = model.encode_and_read(&original, &[Arc::clone(&head)], 10, 20)
        .expect("audio original");
    let b = model.encode_and_read(&delayed, &[head], 10, 20).expect("audio delayed");
    assert_ne!(a.reader.cells[0].score_q24, b.reader.cells[0].score_q24);
    assert_eq!(a.encoder_macs_this_batch, b.encoder_macs_this_batch);
}

#[test]
fn masked_source_and_invalid_time_order_fail_before_first_forward() {
    let mut model = FrozenQ24ProjectionStemV4::new(profile(FeatureModalityV3::Audio))
        .expect("audio model");
    let initial = source(&model, FeatureModalityV3::Audio);
    let head = head(&model, "cell:audio", true, vec![Q24, 0]);
    let mut bad_mask = initial.clone();
    bad_mask.mask[1] = 0;
    bad_mask.identity.base.input_digest =
        canonical_stem_source_digest_v4(&bad_mask).expect("rehashed");
    assert_eq!(
        model.encode_and_read(&bad_mask, &[Arc::clone(&head)], 10, 20),
        Err(StemPhysicalErrorV4::InvalidSource),
    );
    let mut bad_time = initial.clone();
    bad_time.coordinates[0].time_micros = 500_000;
    bad_time.coordinates[1].time_micros = 1;
    bad_time.identity.base.input_digest =
        canonical_stem_source_digest_v4(&bad_time).expect("rehashed");
    assert_eq!(
        model.encode_and_read(&bad_time, &[head], 10, 20),
        Err(StemPhysicalErrorV4::InvalidSource),
    );
    assert_eq!(model.completed_forwards(), 0);
}

#[test]
fn expired_and_overbudget_inputs_cannot_run_the_encoder() {
    let mut model = FrozenQ24ProjectionStemV4::new(profile(FeatureModalityV3::Text))
        .expect("model");
    let input = source(&model, FeatureModalityV3::Text);
    let cell = head(&model, "cell:1", true, vec![Q24, 0]);
    assert_eq!(
        model.encode_and_read(&input, &[Arc::clone(&cell)], 1000, 20),
        Err(StemPhysicalErrorV4::Expired),
    );
    assert_eq!(
        model.encode_and_read(&input, &[], 10, 20),
        Err(StemPhysicalErrorV4::BudgetExceeded),
    );
    assert_eq!(model.completed_forwards(), 0);
}

#[test]
fn q24_ties_to_even_and_saturation_run_on_real_cpu_arithmetic() {
    let mut config = profile(FeatureModalityV3::Text);
    config.input_width = 1;
    config.output_width = 1;
    config.weights_q24 = vec![Q24 / 2];
    config.bias_q24 = vec![0];
    let mut model = FrozenQ24ProjectionStemV4::new(config).expect("half model");
    let mut src = source(&model, FeatureModalityV3::Text);
    src.input_width = 1;
    src.values_q24 = vec![1, 3, -3];
    src.mask = vec![1, 1, 1];
    src.coordinates = vec![FeatureCoordinatesV3::default(); 3];
    src.identity.base.input_digest = canonical_stem_source_digest_v4(&src).expect("rows");
    let (snapshot, _, macs) = model.encode(&src, 10).expect("real Q24 forward");
    assert_eq!(snapshot.values_q24(), &[0, 2, -2]);
    assert_eq!(macs, 3);
    assert_eq!(model.completed_forwards(), 1);

    let mut config = profile(FeatureModalityV3::Text);
    config.input_width = 1;
    config.output_width = 1;
    config.weights_q24 = vec![Q24];
    config.bias_q24 = vec![Q24];
    let mut saturated = FrozenQ24ProjectionStemV4::new(config).expect("saturating model");
    let mut src = source(&saturated, FeatureModalityV3::Text);
    src.input_width = 1;
    src.values_q24 = vec![MAX_Q24, -MAX_Q24];
    src.identity.base.input_digest = canonical_stem_source_digest_v4(&src).expect("saturation source");
    let (features, _, _) = saturated.encode(&src, 10).expect("saturating forward");
    assert_eq!(features.values_q24(), &[MAX_Q24, -7 * Q24]);
}

#[test]
fn invalid_head_duplicate_and_work_budget_preflight_spend_zero_encoder_forwards() {
    let mut model = FrozenQ24ProjectionStemV4::new(profile(FeatureModalityV3::Text))
        .expect("frozen model");
    let input = source(&model, FeatureModalityV3::Text);
    let matched = head(&model, "cell:1", true, vec![Q24, 0]);
    assert_eq!(
        model.encode_and_read(&input, &[Arc::clone(&matched)], 10, 2),
        Err(StemPhysicalErrorV4::BudgetExceeded),
    );
    assert_eq!(
        model.encode_and_read(
            &input,
            &[Arc::clone(&matched), Arc::clone(&matched)],
            10,
            20,
        ),
        Err(StemPhysicalErrorV4::ReaderRejected),
    );
    let mut altered = profile(FeatureModalityV3::Text);
    altered.adapter_digest = nonzero(b"another adapter");
    let second_model = FrozenQ24ProjectionStemV4::new(altered).expect("other");
    let foreign = head(&second_model, "cell:foreign", true, vec![Q24, 0]);
    assert_eq!(
        model.encode_and_read(&input, &[foreign], 10, 20),
        Err(StemPhysicalErrorV4::ReaderRejected),
    );
    assert_eq!(model.completed_forwards(), 0);
    assert_eq!(model.completed_macs(), 0);
}

#[test]
fn frozen_projection_weights_digest_binds_every_numeric_coefficient() {
    let a = FrozenQ24ProjectionStemV4::new(profile(FeatureModalityV3::Text))
        .expect("original");
    let mut other = profile(FeatureModalityV3::Text);
    other.bias_q24[0] = 1;
    let b = FrozenQ24ProjectionStemV4::new(other).expect("changed bias");
    assert_ne!(a.digest(), b.digest());
    let mut other = profile(FeatureModalityV3::Text);
    other.weights_q24[0] = Q24 - 1;
    let c = FrozenQ24ProjectionStemV4::new(other).expect("changed weight");
    assert_ne!(a.digest(), c.digest());
    assert_ne!(b.digest(), c.digest());
}
