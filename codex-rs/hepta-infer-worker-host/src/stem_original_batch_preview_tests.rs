use super::*;

use codex_hepta_infer_core::SharedFeatureBufferV1;
use codex_hepta_infer_core::bind_stem_feature_request_v1;
use codex_hepta_infer_core::stem_encoder_pipeline_digest_v1;
use codex_hepta_infer_core::stem_feature_vector_digest_v1;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable fixture ID")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

struct Fixture {
    source: StemFeatureRefV1,
    access: StemAccessContextV1,
    head: StemHeadBindingV1,
    generic: SharedFeatureBufferV1,
    stem: SharedStemQ24BufferV1,
    key: MicrobatchKeyV1,
    authorization: WorkerRequest,
}

fn fixture(width: usize) -> Fixture {
    let q24 = 1_i64 << 24;
    let features = (0..width)
        .map(|n| if n % 2 == 0 { q24 / 2 } else { -(q24 / 4) })
        .collect::<Vec<_>>();
    let generic = SharedFeatureBufferV1::from_vec(features.clone())
        .expect("original generic Q24 buffer");
    let generation = Generation::new(3).expect("generation");
    let source = StemFeatureRefV1 {
        scope_id: id("scope.1"),
        principal_id: id("principal.1"),
        stem_model_id: id("stem.1"),
        stem_generation: generation,
        authority_epoch: 2,
        lease_expires_at_ms: 1_000,
        stem_weights_digest: digest(b"pinned stem weights"),
        tokenizer_digest: digest(b"pinned tokenizer"),
        preprocessor_digest: digest(b"pinned preprocessor"),
        projection_digest: digest(b"pinned projection"),
        input_digest: digest(b"original scoped input"),
        feature_digest: stem_feature_vector_digest_v1(&features)
            .expect("separate Stem domain feature hash"),
        feature_width: width,
    };
    let access = StemAccessContextV1 {
        scope_id: source.scope_id.clone(),
        principal_id: source.principal_id.clone(),
        stem_generation: generation,
        authority_epoch: 2,
        now_ms: 100,
        revocation_observed: false,
    };
    let head = StemHeadBindingV1 {
        request_id: id("request.1"),
        head_model_id: id("head.1"),
        head_digest: digest(b"selected Head configuration"),
        head_weights_digest: digest(b"selected Head weights"),
        required_stem_model_id: source.stem_model_id.clone(),
        required_stem_generation: generation,
        required_encoder_digest: stem_encoder_pipeline_digest_v1(&source),
        required_tokenizer_digest: source.tokenizer_digest,
        required_preprocessor_digest: source.preprocessor_digest,
        required_projection_digest: source.projection_digest,
        required_feature_width: width,
        expected_output_width: 5,
    };
    let key = MicrobatchKeyV1 {
        scope_id: source.scope_id.clone(),
        model_digest: digest(b"actual loaded model"),
        generation,
        route_fence: 42,
        authority_epoch: 2,
    };
    let mut authorization = WorkerRequest {
        request_id: head.request_id.to_string(),
        reservation_id: "reservation.1".to_string(),
        model_digest: key.model_digest.to_string(),
        payload_digest: digest(b"test initial payload").to_string(),
        maximum_tokens: 4,
        deadline_ms: 900,
        lease_payload_digest: digest(b"test initial payload").to_string(),
        reservation_model_digest: key.model_digest.to_string(),
        reservation_maximum_tokens: 4,
        cancelled: false,
    };

    // This digest is generated only by the *test fixture*. The actual
    // adapter MUST NOT rewrite caller-supplied lease/payload hashes.
    let owned = bind_stem_feature_request_v1(
        &source,
        &access,
        head.clone(),
        &features,
    )
    .expect("exact canonical typed Stem source");
    let scoped_input = Digest32::of_parts(&[
        b"hepta.infer-worker.scoped-stem-input.v1",
        source.input_digest.as_array(),
        owned.feature_ref_digest.as_array(),
    ]);
    let request = NeuronFeatureRequest {
        authorization: authorization.clone(),
        encoder_digest: owned.request.encoder_digest.to_string(),
        head_digest: owned.request.head_digest.to_string(),
        weights_digest: owned.request.weights_digest.to_string(),
        input_digest: scoped_input.to_string(),
        feature_vector_q24: owned.request.feature_vector_q24,
        expected_output_width: owned.request.expected_output_width,
    };
    let expected_payload = canonical_neuron_feature_payload_digest(&request);
    authorization.payload_digest = expected_payload.clone();
    authorization.lease_payload_digest = expected_payload;
    let stem = SharedStemQ24BufferV1::from_unverified_arc(
        source.clone(),
        generic.shared_arc(),
    )
    .expect("same allocation under separate validated Stem hash");
    Fixture {
        source,
        access,
        head,
        generic,
        stem,
        key,
        authorization,
    }
}

#[test]
fn original_signed_batch_binding_matches_typed_stem_request_at_512d() {
    let fx = fixture(512);
    assert_ne!(fx.generic.digest(), fx.source.feature_digest);
    let view = fx
        .stem
        .borrow_for_head(&fx.access, &fx.head)
        .expect("pure typed buffer with current claims");
    assert_eq!(
        view.feature_vector_q24().as_ptr(),
        fx.generic.as_slice().as_ptr()
    );
    let expected = bind_stem_feature_request_v1(
        &fx.source,
        &fx.access,
        fx.head.clone(),
        fx.generic.as_slice(),
    )
    .expect("old typed V1 source");
    let scoped_input = Digest32::of_parts(&[
        b"hepta.infer-worker.scoped-stem-input.v1",
        fx.source.input_digest.as_array(),
        expected.feature_ref_digest.as_array(),
    ]);
    let original_request = NeuronFeatureRequest {
        authorization: fx.authorization.clone(),
        encoder_digest: expected.request.encoder_digest.to_string(),
        head_digest: expected.request.head_digest.to_string(),
        weights_digest: expected.request.weights_digest.to_string(),
        input_digest: scoped_input.to_string(),
        feature_vector_q24: expected.request.feature_vector_q24,
        expected_output_width: expected.request.expected_output_width,
    };
    let original_binding = neuron_batch_final_use_binding_v1(
        "worker.1",
        &fx.key,
        &original_request,
    )
    .expect("original signed Worker prepares exact expected binding");
    let preview = prepare_stem_original_batch_preview_v1(
        "worker.1",
        &fx.source,
        &fx.access,
        &fx.head,
        &fx.stem,
        &fx.key,
        &fx.authorization,
    )
    .expect("same canonical source mapped into original signed batch ABI");

    assert_eq!(preview.request, original_request);
    assert_eq!(preview.exact_final_use_binding, original_binding);
    assert_eq!(preview.model_id, fx.head.head_model_id.to_string());
    assert!(!preview.authority.grants_any());
    assert_ne!(preview.request.input_digest, fx.source.input_digest.to_string());
    assert_eq!(
        canonical_neuron_feature_payload_digest(&preview.request),
        fx.authorization.payload_digest
    );
}

#[test]
fn preview_does_not_repair_forged_leases_or_cross_scope_identity() {
    let fx = fixture(8);
    let mut bad_lease = fx.authorization.clone();
    bad_lease.lease_payload_digest = digest(b"mismatched lease").to_string();
    assert!(matches!(
        prepare_stem_original_batch_preview_v1(
            "worker.1",
            &fx.source,
            &fx.access,
            &fx.head,
            &fx.stem,
            &fx.key,
            &bad_lease,
        ),
        Err(StemOriginalBatchPreviewErrorV1::PayloadMismatch)
    ));

    let mut foreign_key = fx.key.clone();
    foreign_key.scope_id = id("scope.other");
    assert!(matches!(
        prepare_stem_original_batch_preview_v1(
            "worker.1",
            &fx.source,
            &fx.access,
            &fx.head,
            &fx.stem,
            &foreign_key,
            &fx.authorization,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidScopeFence)
    ));

    let mut wrong_model = fx.authorization.clone();
    wrong_model.model_digest = digest(b"another loaded model").to_string();
    assert!(matches!(
        prepare_stem_original_batch_preview_v1(
            "worker.1",
            &fx.source,
            &fx.access,
            &fx.head,
            &fx.stem,
            &fx.key,
            &wrong_model,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidHead)
    ));
}

#[test]
fn preview_rechecks_lease_epoch_and_stem_digest_not_just_same_arc_pointer() {
    let fx = fixture(512);
    let mut revoked = fx.access.clone();
    revoked.revocation_observed = true;
    assert!(matches!(
        prepare_stem_original_batch_preview_v1(
            "worker.1",
            &fx.source,
            &revoked,
            &fx.head,
            &fx.stem,
            &fx.key,
            &fx.authorization,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidLease)
    ));

    let mut expired = fx.authorization.clone();
    expired.deadline_ms = fx.source.lease_expires_at_ms + 1;
    assert!(matches!(
        prepare_stem_original_batch_preview_v1(
            "worker.1",
            &fx.source,
            &fx.access,
            &fx.head,
            &fx.stem,
            &fx.key,
            &expired,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidLease)
    ));

    let mut stale = fx.key.clone();
    stale.authority_epoch += 1;
    assert!(matches!(
        prepare_stem_original_batch_preview_v1(
            "worker.1",
            &fx.source,
            &fx.access,
            &fx.head,
            &fx.stem,
            &stale,
            &fx.authorization,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidGeneration)
    ));

    // Generic neuron.runtime feature digests cannot be reused as if the
    // independent Stem-domain contents had been verified.
    let mut forged_source = fx.source.clone();
    forged_source.feature_digest = fx.generic.digest();
    assert!(matches!(
        prepare_stem_original_batch_preview_v1(
            "worker.1",
            &forged_source,
            &fx.access,
            &fx.head,
            &fx.stem,
            &fx.key,
            &fx.authorization,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidSource)
    ));

    // A new caller-controlled lease expiry is not a renewed original Stem
    // source. The canonical full Stem reference hash includes this field,
    // even if Scope, model ID, Q24 values and all weights are unchanged.
    let mut longer_lease = fx.source.clone();
    longer_lease.lease_expires_at_ms += 500;
    assert!(matches!(
        prepare_stem_original_batch_preview_v1(
            "worker.1",
            &longer_lease,
            &fx.access,
            &fx.head,
            &fx.stem,
            &fx.key,
            &fx.authorization,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidSource)
    ));
}

#[test]
fn preview_refuses_unfenced_or_cancelled_original_batch_requests() {
    let fx = fixture(4);
    let mut no_fence = fx.key.clone();
    no_fence.route_fence = 0;
    assert!(matches!(
        prepare_stem_original_batch_preview_v1(
            "worker.1",
            &fx.source,
            &fx.access,
            &fx.head,
            &fx.stem,
            &no_fence,
            &fx.authorization,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidScopeFence)
    ));
    let mut cancelled = fx.authorization.clone();
    cancelled.cancelled = true;
    assert!(matches!(
        prepare_stem_original_batch_preview_v1(
            "worker.1",
            &fx.source,
            &fx.access,
            &fx.head,
            &fx.stem,
            &fx.key,
            &cancelled,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidIdentity)
    ));
}
