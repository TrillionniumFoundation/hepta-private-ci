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
    let generic =
        SharedFeatureBufferV1::from_vec(features.clone()).expect("original generic Q24 buffer");
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
    let owned = bind_stem_feature_request_v1(&source, &access, head.clone(), &features)
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
    let stem = SharedStemQ24BufferV1::from_unverified_arc(source.clone(), generic.shared_arc())
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
    let original_binding =
        neuron_batch_final_use_binding_v1("worker.1", &fx.key, &original_request)
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
    assert_ne!(
        preview.request.input_digest,
        fx.source.input_digest.to_string()
    );
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
            "worker.1", &fx.source, &fx.access, &fx.head, &fx.stem, &fx.key, &bad_lease,
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
            "worker.1", &fx.source, &fx.access, &fx.head, &fx.stem, &fx.key, &expired,
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
            "worker.1", &fx.source, &fx.access, &fx.head, &fx.stem, &fx.key, &cancelled,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidIdentity)
    ));
}

#[test]
fn two_logical_cells_retain_one_stem_source_but_distinct_original_signed_bindings() {
    let fx = fixture(512);
    let mut second_head = fx.head.clone();
    second_head.request_id = id("request.cell.two");
    let mut second_authorization = fx.authorization.clone();
    second_authorization.request_id = second_head.request_id.to_string();
    second_authorization.reservation_id = "reservation.cell.two".to_string();

    // Both logical Cells use the SAME frozen Stem bytes and physical Head
    // model identity. This remains only a prospective signed batch request,
    // not a proof that the backend physically executed both in one call.
    let first = prepare_stem_original_batch_preview_v1(
        "worker.1",
        &fx.source,
        &fx.access,
        &fx.head,
        &fx.stem,
        &fx.key,
        &fx.authorization,
    )
    .expect("first logical Cell admission preview");
    let second = prepare_stem_original_batch_preview_v1(
        "worker.1",
        &fx.source,
        &fx.access,
        &second_head,
        &fx.stem,
        &fx.key,
        &second_authorization,
    )
    .expect("second logical Cell admission preview");

    assert_eq!(first.model_id, second.model_id);
    assert_eq!(
        first.request.feature_vector_q24,
        second.request.feature_vector_q24
    );
    assert_eq!(first.request.input_digest, second.request.input_digest);
    assert_ne!(
        first.request.authorization.request_id,
        second.request.authorization.request_id
    );
    assert_ne!(
        first.exact_final_use_binding.request_sha256, second.exact_final_use_binding.request_sha256,
        "original signed Final-use also binds each independent request/reservation"
    );
    assert_eq!(
        first.exact_final_use_binding.scope_sha256,
        second.exact_final_use_binding.scope_sha256
    );
    assert!(!first.authority.grants_any());
    assert!(!second.authority.grants_any());

    let first_view = fx
        .stem
        .borrow_for_head(&fx.access, &fx.head)
        .expect("source still current for first logical Cell");
    let second_view = fx
        .stem
        .borrow_for_head(&fx.access, &second_head)
        .expect("source still current for second logical Cell");
    assert_eq!(
        first_view.feature_vector_q24().as_ptr(),
        second_view.feature_vector_q24().as_ptr()
    );
    assert_eq!(
        first_view.feature_vector_q24().as_ptr(),
        fx.generic.as_slice().as_ptr()
    );
}

#[test]
fn no_copy_preview_matches_exact_legacy_v1_binding_and_original_arc_allocation() {
    let fx = fixture(512);
    let owned = prepare_stem_original_batch_preview_v1(
        "worker.1",
        &fx.source,
        &fx.access,
        &fx.head,
        &fx.stem,
        &fx.key,
        &fx.authorization,
    )
    .expect("legacy typed owned V1 preview");
    let shared = prepare_stem_original_shared_batch_preview_v1(
        "worker.1",
        &fx.source,
        &fx.access,
        &fx.head,
        &fx.stem,
        &fx.generic,
        &fx.key,
        &fx.authorization,
    )
    .expect("exact immutable Arc-backed original Batch preview");

    assert_eq!(
        shared.exact_final_use_binding,
        owned.exact_final_use_binding
    );
    assert_eq!(shared.model_id, owned.model_id);
    assert!(shared.request.feature_vector_q24.is_empty());
    assert_eq!(shared.request.authorization, owned.request.authorization);
    assert_eq!(shared.request.input_digest, owned.request.input_digest);
    assert_eq!(shared.request.encoder_digest, owned.request.encoder_digest);
    assert_eq!(shared.request.head_digest, owned.request.head_digest);
    assert_eq!(shared.request.weights_digest, owned.request.weights_digest);
    assert_eq!(
        shared.request.expected_output_width,
        owned.request.expected_output_width
    );
    assert!(shared.shared_features.shares_allocation_with(&fx.generic));
    assert_eq!(
        shared.shared_features.as_slice(),
        owned.request.feature_vector_q24
    );
    assert!(!shared.authority.grants_any());
}

#[test]
fn original_shared_preview_denies_equal_bytes_in_different_allocations_and_forged_stem() {
    let fx = fixture(8);
    let copied = SharedFeatureBufferV1::from_vec(fx.generic.as_slice().to_vec())
        .expect("same numeric bytes in DIFFERENT Arc allocation");
    assert_eq!(copied.digest(), fx.generic.digest());
    assert!(!copied.shares_allocation_with(&fx.generic));
    assert_eq!(
        prepare_stem_original_shared_batch_preview_v1(
            "worker.1",
            &fx.source,
            &fx.access,
            &fx.head,
            &fx.stem,
            &copied,
            &fx.key,
            &fx.authorization,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidSource)
    );

    let mut forged = fx.source.clone();
    forged.lease_expires_at_ms += 250;
    assert_eq!(
        prepare_stem_original_shared_batch_preview_v1(
            "worker.1",
            &forged,
            &fx.access,
            &fx.head,
            &fx.stem,
            &fx.generic,
            &fx.key,
            &fx.authorization,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidSource)
    );

    let mut forged_digest = fx.source.clone();
    forged_digest.feature_digest = fx.generic.digest();
    assert_eq!(
        prepare_stem_original_shared_batch_preview_v1(
            "worker.1",
            &forged_digest,
            &fx.access,
            &fx.head,
            &fx.stem,
            &fx.generic,
            &fx.key,
            &fx.authorization,
        ),
        Err(StemOriginalBatchPreviewErrorV1::InvalidSource)
    );

    let mut bad_payload = fx.authorization.clone();
    bad_payload.lease_payload_digest = digest(b"wrong authorization bytes").to_string();
    assert_eq!(
        prepare_stem_original_shared_batch_preview_v1(
            "worker.1",
            &fx.source,
            &fx.access,
            &fx.head,
            &fx.stem,
            &fx.generic,
            &fx.key,
            &bad_payload,
        ),
        Err(StemOriginalBatchPreviewErrorV1::PayloadMismatch)
    );
}

#[test]
fn two_cells_share_exact_q24_arc_but_keep_distinct_original_signed_request_identities() {
    let fx = fixture(512);
    let mut head_two = fx.head.clone();
    head_two.request_id = id("request.cell.two");
    let mut auth_two = fx.authorization.clone();
    auth_two.request_id = head_two.request_id.to_string();
    auth_two.reservation_id = "reservation.cell.two".to_string();

    let first = prepare_stem_original_shared_batch_preview_v1(
        "worker.1",
        &fx.source,
        &fx.access,
        &fx.head,
        &fx.stem,
        &fx.generic,
        &fx.key,
        &fx.authorization,
    )
    .expect("first independently signed original pending intent");
    let second = prepare_stem_original_shared_batch_preview_v1(
        "worker.1",
        &fx.source,
        &fx.access,
        &head_two,
        &fx.stem,
        &fx.generic,
        &fx.key,
        &auth_two,
    )
    .expect("second independently signed original pending intent");

    assert!(
        first
            .shared_features
            .shares_allocation_with(&second.shared_features)
    );
    assert!(first.shared_features.shares_allocation_with(&fx.generic));
    assert_eq!(
        first.shared_features.as_slice().as_ptr(),
        second.shared_features.as_slice().as_ptr()
    );
    assert!(first.request.feature_vector_q24.is_empty());
    assert!(second.request.feature_vector_q24.is_empty());
    assert_eq!(first.request.input_digest, second.request.input_digest);
    assert_ne!(
        first.exact_final_use_binding.request_sha256,
        second.exact_final_use_binding.request_sha256
    );
    assert_eq!(
        first.exact_final_use_binding.scope_sha256,
        second.exact_final_use_binding.scope_sha256
    );
    assert!(!first.authority.grants_any());
    assert!(!second.authority.grants_any());
}
