use super::*;

use codex_hepta_infer_core::sequence_feature_v3::FeatureCoordinatesV3;
use codex_hepta_infer_core::shared_feature_v2::SharedFeatureIdentityV2;
use codex_hepta_types::Generation;

fn identity(modality: FeatureModalityV3) -> FeatureSequenceIdentityV3 {
    FeatureSequenceIdentityV3 {
        base: SharedFeatureIdentityV2 {
            principal_id: StableId::new("principal:a").expect("principal"),
            purpose_id: StableId::new("reasoning").expect("purpose"),
            generation: Generation::new(5).expect("generation"),
            authority_epoch: 3,
            encoder_digest: Digest32::of_bytes(b"real-frozen-encoder-contract"),
            tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
            normalizer_digest: Digest32::of_bytes(b"normalizer"),
            quantization_digest: Digest32::of_bytes(b"q24"),
            input_digest: Digest32::of_bytes(b"complete input including choices"),
        },
        modality,
        preprocessing_digest: Digest32::of_bytes(b"preprocess"),
        adapter_digest: Digest32::of_bytes(b"modality-adapter"),
    }
}

fn snapshot(
    id: FeatureSequenceIdentityV3,
    features: Vec<i64>,
    mask: Vec<u8>,
    coords: Vec<FeatureCoordinatesV3>,
) -> Arc<ImmutableFeatureSequenceV3> {
    let rows = mask.len();
    Arc::new(
        ImmutableFeatureSequenceV3::build(
            id,
            1000,
            rows,
            2,
            Arc::from(features),
            Arc::from(mask),
            Arc::from(coords),
        )
        .expect("immutable source"),
    )
}

fn head(
    id: &FeatureSequenceIdentityV3,
    cell: &str,
    policy: SequenceAttentionPolicyV3,
    value: Vec<i64>,
) -> Arc<SequenceCellHeadV3> {
    Arc::new(
        SequenceCellHeadV3::new(
            SequenceHeadBindingV3 {
                cell_id: StableId::new(cell).expect("cell"),
                encoder_digest: id.base.encoder_digest,
                tokenizer_digest: id.base.tokenizer_digest,
                normalizer_digest: id.base.normalizer_digest,
                quantization_digest: id.base.quantization_digest,
                preprocessing_digest: id.preprocessing_digest,
                adapter_digest: id.adapter_digest,
                modality: id.modality,
                attention: policy,
            },
            SequenceHeadParametersV3 {
                query_q24: vec![Q24, 0],
                key_q24: vec![0, Q24],
                value_q24: value,
                local_q24: vec![0, Q24],
                bias_q24: 0,
            },
        )
        .expect("head"),
    )
}

fn fence(snapshot: &ImmutableFeatureSequenceV3) -> SequenceReadFenceV3 {
    SequenceReadFenceV3 {
        now_ms: 10,
        expected_identity: snapshot.identity().clone(),
        expected_content_digest: snapshot.content_digest(),
        maximum_attention_pairs: MAX_ATTENTION_PAIRS,
    }
}

fn two_rows(id: FeatureSequenceIdentityV3) -> Arc<ImmutableFeatureSequenceV3> {
    snapshot(
        id,
        vec![Q24, 0, 0, Q24],
        vec![1, 1],
        vec![FeatureCoordinatesV3::default(); 2],
    )
}

#[test]
fn one_immutable_sequence_feeds_independent_cells_without_reencoding_or_authority() {
    let id = identity(FeatureModalityV3::Text);
    let sequence = two_rows(id.clone());
    let heads = [
        head(
            &id,
            "cell:a",
            SequenceAttentionPolicyV3::Causal,
            vec![Q24, 0],
        ),
        head(
            &id,
            "cell:b",
            SequenceAttentionPolicyV3::Causal,
            vec![0, Q24],
        ),
    ];
    assert_eq!(heads[0].parameter_count(), 9);
    let original_count = Arc::strong_count(&sequence);
    let one = evaluate_sequence_heads_v3(&fence(&sequence), &sequence, &heads).expect("batch");
    let two = evaluate_sequence_heads_v3(&fence(&sequence), &sequence, &heads).expect("replay");
    assert_eq!(one, two);
    assert_eq!(one.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(one.cells.len(), 2);
    assert_ne!(one.cells[0].score_q24, one.cells[1].score_q24);
    assert_ne!(one.cells[0].head_digest, one.cells[1].head_digest);
    assert_eq!(one.attention_pairs, 6);
    assert_eq!(Arc::strong_count(&sequence), original_count);
    assert_eq!(sequence.values_q24(), &[Q24, 0, 0, Q24]);
}

#[test]
fn reversing_two_facts_changes_a_causal_readout_not_just_its_digest() {
    let id = identity(FeatureModalityV3::Text);
    let a = two_rows(id.clone());
    let b = snapshot(
        id.clone(),
        vec![0, Q24, Q24, 0],
        vec![1, 1],
        vec![FeatureCoordinatesV3::default(); 2],
    );
    let cell = head(
        &id,
        "cell:a",
        SequenceAttentionPolicyV3::Causal,
        vec![Q24, 0],
    );
    let first = evaluate_sequence_heads_v3(&fence(&a), &a, &[Arc::clone(&cell)]).expect("a");
    let reversed = evaluate_sequence_heads_v3(&fence(&b), &b, &[cell]).expect("b");
    assert_eq!(first.cells[0].score_q24, 10_485_760);
    assert_eq!(reversed.cells[0].score_q24, 5_592_405);
    assert_ne!(first.observation_digest, reversed.observation_digest);
}

#[test]
fn masked_padding_never_adds_context_or_changes_the_numeric_readout() {
    let id = identity(FeatureModalityV3::Text);
    let original = two_rows(id.clone());
    let padded = snapshot(
        id.clone(),
        vec![Q24, 0, 0, Q24, 0, 0],
        vec![1, 1, 0],
        vec![FeatureCoordinatesV3::default(); 3],
    );
    let cell = head(
        &id,
        "cell:a",
        SequenceAttentionPolicyV3::Causal,
        vec![Q24, 0],
    );
    let before = evaluate_sequence_heads_v3(&fence(&original), &original, &[Arc::clone(&cell)])
        .expect("original");
    let after = evaluate_sequence_heads_v3(&fence(&padded), &padded, &[cell]).expect("padded");
    assert_eq!(before.cells[0].score_q24, after.cells[0].score_q24);
    assert_eq!(before.attention_pairs, after.attention_pairs);
    assert_ne!(before.feature_content_digest, after.feature_content_digest);
}

#[test]
fn patch_and_time_coordinates_change_relational_scores() {
    let image = identity(FeatureModalityV3::Image);
    let same_place = two_rows(image.clone());
    let moved_patch = snapshot(
        image.clone(),
        vec![Q24, 0, 0, Q24],
        vec![1, 1],
        vec![
            FeatureCoordinatesV3::default(),
            FeatureCoordinatesV3 {
                x: 1024,
                ..FeatureCoordinatesV3::default()
            },
        ],
    );
    let image_head = head(
        &image,
        "cell:image",
        SequenceAttentionPolicyV3::Bidirectional,
        vec![Q24, 0],
    );
    let result_a =
        evaluate_sequence_heads_v3(&fence(&same_place), &same_place, &[Arc::clone(&image_head)])
            .expect("nearby");
    let result_b = evaluate_sequence_heads_v3(&fence(&moved_patch), &moved_patch, &[image_head])
        .expect("distant");
    assert_eq!(result_a.attention_pairs, 4);
    assert_ne!(result_a.cells[0].score_q24, result_b.cells[0].score_q24);

    let audio = identity(FeatureModalityV3::Audio);
    let close = two_rows(audio.clone());
    let late = snapshot(
        audio.clone(),
        vec![Q24, 0, 0, Q24],
        vec![1, 1],
        vec![
            FeatureCoordinatesV3::default(),
            FeatureCoordinatesV3 {
                time_micros: 500_000,
                ..FeatureCoordinatesV3::default()
            },
        ],
    );
    let audio_head = head(
        &audio,
        "cell:audio",
        SequenceAttentionPolicyV3::Bidirectional,
        vec![Q24, 0],
    );
    let first = evaluate_sequence_heads_v3(&fence(&close), &close, &[Arc::clone(&audio_head)])
        .expect("close");
    let last = evaluate_sequence_heads_v3(&fence(&late), &late, &[audio_head]).expect("late");
    assert_ne!(first.cells[0].score_q24, last.cells[0].score_q24);
}

#[test]
fn stale_source_cross_principal_and_changed_full_input_are_rejected() {
    let id = identity(FeatureModalityV3::Text);
    let sequence = two_rows(id.clone());
    let cell = head(
        &id,
        "cell:a",
        SequenceAttentionPolicyV3::Causal,
        vec![Q24, 0],
    );
    let mut request = fence(&sequence);

    request.now_ms = sequence.expires_at_ms();
    assert_eq!(
        evaluate_sequence_heads_v3(&request, &sequence, &[Arc::clone(&cell)]),
        Err(SequenceReadErrorV3::StaleFeature),
    );
    request = fence(&sequence);
    request.expected_identity.base.principal_id =
        StableId::new("principal:b").expect("other principal");
    assert_eq!(
        evaluate_sequence_heads_v3(&request, &sequence, &[Arc::clone(&cell)]),
        Err(SequenceReadErrorV3::InvalidFeatureIdentity),
    );
    request = fence(&sequence);
    request.expected_identity.base.input_digest = Digest32::of_bytes(b"new choices");
    assert_eq!(
        evaluate_sequence_heads_v3(&request, &sequence, &[Arc::clone(&cell)]),
        Err(SequenceReadErrorV3::InvalidFeatureIdentity),
    );
    request = fence(&sequence);
    request.expected_content_digest = Digest32::of_bytes(b"stale cache entry");
    assert_eq!(
        evaluate_sequence_heads_v3(&request, &sequence, &[cell]),
        Err(SequenceReadErrorV3::ContentMismatch),
    );
}

#[test]
fn invalid_tensor_model_binding_duplicate_cell_and_work_budget_fail_closed() {
    let id = identity(FeatureModalityV3::Text);
    let seq = two_rows(id.clone());
    let cell = head(
        &id,
        "cell:a",
        SequenceAttentionPolicyV3::Causal,
        vec![Q24, 0],
    );
    let duplicate = vec![Arc::clone(&cell), Arc::clone(&cell)];
    assert_eq!(
        evaluate_sequence_heads_v3(&fence(&seq), &seq, &duplicate),
        Err(SequenceReadErrorV3::DuplicateCell),
    );

    let mut request = fence(&seq);
    request.maximum_attention_pairs = 2;
    assert_eq!(
        evaluate_sequence_heads_v3(&request, &seq, &[Arc::clone(&cell)]),
        Err(SequenceReadErrorV3::BudgetExceeded),
    );
    request.maximum_attention_pairs = MAX_ATTENTION_PAIRS + 1;
    assert_eq!(
        evaluate_sequence_heads_v3(&request, &seq, &[Arc::clone(&cell)]),
        Err(SequenceReadErrorV3::BudgetExceeded),
    );
    assert!(matches!(
        SequenceCellHeadV3::new(
            SequenceHeadBindingV3 {
                cell_id: StableId::new("bad-cell").expect("cell"),
                encoder_digest: id.base.encoder_digest,
                tokenizer_digest: id.base.tokenizer_digest,
                normalizer_digest: id.base.normalizer_digest,
                quantization_digest: id.base.quantization_digest,
                preprocessing_digest: id.preprocessing_digest,
                adapter_digest: id.adapter_digest,
                modality: id.modality,
                attention: SequenceAttentionPolicyV3::Causal,
            },
            SequenceHeadParametersV3 {
                query_q24: vec![Q24 + 1, 0],
                key_q24: vec![0, Q24],
                value_q24: vec![Q24, 0],
                local_q24: vec![0, Q24],
                bias_q24: 0,
            },
        ),
        Err(SequenceReadErrorV3::InvalidHead)
    ));

    let mut wrong_adapter = id.clone();
    wrong_adapter.adapter_digest = Digest32::of_bytes(b"different adapter");
    let wrong_head = head(
        &wrong_adapter,
        "cell:wrong",
        SequenceAttentionPolicyV3::Causal,
        vec![Q24, 0],
    );
    assert_eq!(
        evaluate_sequence_heads_v3(&fence(&seq), &seq, &[wrong_head]),
        Err(SequenceReadErrorV3::IncompatibleHead),
    );
    let mut changed_profile = id.clone();
    changed_profile.base.tokenizer_digest = Digest32::of_bytes(b"changed-tokenization");
    let mismatched = head(
        &changed_profile,
        "cell:new-profile",
        SequenceAttentionPolicyV3::Causal,
        vec![Q24, 0],
    );
    assert_eq!(
        evaluate_sequence_heads_v3(&fence(&seq), &seq, &[mismatched]),
        Err(SequenceReadErrorV3::IncompatibleHead),
    );
    assert_eq!(
        evaluate_sequence_heads_v3(&fence(&seq), &seq, &[]),
        Err(SequenceReadErrorV3::BudgetExceeded),
    );
}

#[test]
fn extreme_q24_inputs_saturate_and_receipt_remains_deterministic() {
    let id = identity(FeatureModalityV3::Text);
    let seq = snapshot(
        id.clone(),
        vec![Q24_BOUND, Q24_BOUND, -Q24_BOUND, -Q24_BOUND],
        vec![1, 1],
        vec![FeatureCoordinatesV3::default(); 2],
    );
    let cell = head(
        &id,
        "cell:extreme",
        SequenceAttentionPolicyV3::Causal,
        vec![Q24, 0],
    );
    let report = evaluate_sequence_heads_v3(&fence(&seq), &seq, &[cell]).expect("bounded");
    assert!(report.cells[0].score_q24.abs() <= Q24_BOUND);
    assert!(!report.observation_digest.is_zero());
    assert_eq!(report.attention_pairs, 3);
}

#[test]
fn same_feature_bytes_with_extended_expiry_cannot_reuse_prior_result_receipt() {
    let id = identity(FeatureModalityV3::Text);
    let first = two_rows(id.clone());
    let extended = Arc::new(
        ImmutableFeatureSequenceV3::build(
            id.clone(),
            2000,
            2,
            2,
            Arc::from(vec![Q24, 0, 0, Q24]),
            Arc::from(vec![1_u8, 1]),
            Arc::from(vec![FeatureCoordinatesV3::default(); 2]),
        )
        .expect("extended snapshot"),
    );
    assert_eq!(first.content_digest(), extended.content_digest());
    let cell = head(
        &id,
        "cell:a",
        SequenceAttentionPolicyV3::Causal,
        vec![Q24, 0],
    );
    let a = evaluate_sequence_heads_v3(&fence(&first), &first, &[Arc::clone(&cell)])
        .expect("short-lived");
    let b = evaluate_sequence_heads_v3(&fence(&extended), &extended, &[cell]).expect("extended");
    assert_eq!(a.cells, b.cells);
    assert_ne!(a.observation_digest, b.observation_digest);
}
