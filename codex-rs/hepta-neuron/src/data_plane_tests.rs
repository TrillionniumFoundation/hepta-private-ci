use std::sync::Arc;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;

const Q: i64 = 1 << 24;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn identity(label: &str) -> FeatureSnapshotIdentityV1 {
    FeatureSnapshotIdentityV1::new_with_question_options(
        id(&format!("scope-{label}")),
        id(&format!("workspace-{label}")),
        id(&format!("purpose-{label}")),
        digest(&format!("question-{label}")),
        digest(&format!("options-{label}")),
        digest(&format!("frontier-{label}")),
        digest(&format!("model-{label}")),
        digest(&format!("adapter-{label}")),
        digest(&format!("tokenizer-{label}")),
        digest(&format!("normalizer-{label}")),
        digest(&format!("calibration-{label}")),
    )
    .expect("identity")
}

fn snapshot_with_identity(encoder_generation: u64, label: &str) -> FeatureSnapshotV1 {
    let features = vec![Q / 2, -Q / 4];
    FeatureSnapshotV1::new_with_identity(
        digest("shared-encoder"),
        generation(encoder_generation),
        canonical_feature_vector_digest_v1(&features),
        features,
        identity(label),
    )
    .expect("snapshot")
}

fn snapshot(encoder_generation: u64) -> FeatureSnapshotV1 {
    let features = vec![Q / 2, -Q / 4];
    FeatureSnapshotV1::new(
        digest("shared-encoder"),
        generation(encoder_generation),
        canonical_feature_vector_digest_v1(&features),
        features,
    )
    .expect("snapshot")
}

fn head(digest_value: &str, bias: i64) -> LightweightHeadV1 {
    LightweightHeadV1 {
        head_digest: digest(digest_value),
        feature_width: 2,
        output_width: 2,
        weights_q24: vec![vec![Q, 0], vec![0, Q]],
        bias_q24: vec![bias, bias],
    }
}

#[test]
fn snapshots_are_immutable_and_clones_share_feature_storage() {
    let original = snapshot(1);
    let clone = original.clone();
    assert!(Arc::ptr_eq(&original.features_q24, &clone.features_q24));
    assert_eq!(original.features_q24(), &[Q / 2, -Q / 4]);
    assert_ne!(original.semantic_digest(), Digest32::ZERO);
}

#[test]
fn compatibility_secondary_index_finds_only_exact_encoder_and_shape() {
    let shared = snapshot(1);
    let next_generation = snapshot(2);
    let mut index = CompatibleModelIndexV1::new();
    index
        .register(
            id("head-a"),
            generation(1),
            digest("shared-encoder"),
            head("a", 0),
        )
        .expect("register a");
    index
        .register(
            id("head-b"),
            generation(1),
            digest("shared-encoder"),
            head("b", 1),
        )
        .expect("register b");
    index
        .register(
            id("head-c"),
            generation(1),
            digest("other-encoder"),
            head("c", 0),
        )
        .expect("register c");
    index
        .register(
            id("head-next"),
            generation(2),
            digest("shared-encoder"),
            head("next", 0),
        )
        .expect("register next");

    assert_eq!(
        index.compatible_models(&shared, 2),
        vec![id("head-a"), id("head-b")]
    );
    assert!(index.compatible_models(&shared, 1).is_empty());
    assert_eq!(
        index.compatible_models(&next_generation, 2),
        vec![id("head-next")]
    );
}

#[test]
fn cache_generation_invalidation_makes_old_snapshot_unservable() {
    let mut cache = FeatureSnapshotCacheV1::new(generation(1), 2).expect("cache");
    let old = snapshot_with_identity(1, "old");
    cache.insert(old.clone()).expect("insert");
    assert_eq!(
        cache.get_with_identity(
            old.encoder_digest(),
            old.input_digest(),
            generation(1),
            old.identity(),
        ),
        Some(old.clone())
    );
    cache
        .invalidate_generation(generation(2))
        .expect("invalidate");
    assert!(
        cache
            .get_with_identity(
                old.encoder_digest(),
                old.input_digest(),
                generation(1),
                old.identity(),
            )
            .is_none()
    );
    assert!(cache.insert(old).is_err());
    let fresh = snapshot_with_identity(2, "fresh");
    cache.insert(fresh.clone()).expect("fresh insert");
    assert_eq!(
        cache.get_with_identity(
            fresh.encoder_digest(),
            fresh.input_digest(),
            generation(2),
            fresh.identity(),
        ),
        Some(fresh)
    );
}

#[test]
fn cache_identity_dimensions_prevent_cross_scope_reuse() {
    let mut cache = FeatureSnapshotCacheV1::new(generation(1), 2).expect("cache");
    let first = snapshot_with_identity(1, "first");
    let second = snapshot_with_identity(1, "second");
    assert_eq!(first.input_digest(), second.input_digest());
    cache.insert(first.clone()).expect("first insert");
    cache.insert(second.clone()).expect("second insert");
    assert_eq!(
        cache.get_with_identity(
            first.encoder_digest(),
            first.input_digest(),
            generation(1),
            first.identity(),
        ),
        Some(first.clone())
    );
    assert_eq!(
        cache.get_with_identity(
            second.encoder_digest(),
            second.input_digest(),
            generation(1),
            second.identity(),
        ),
        Some(second.clone())
    );
    assert_ne!(first.identity(), second.identity());
}

#[test]
fn legacy_snapshot_constructor_and_cache_lookup_remain_compatible() {
    let mut cache = FeatureSnapshotCacheV1::new(generation(1), 1).expect("cache");
    let legacy = snapshot(1);
    cache.insert(legacy.clone()).expect("insert");
    assert_eq!(
        cache.get(
            legacy.encoder_digest(),
            legacy.input_digest(),
            generation(1)
        ),
        Some(legacy)
    );
}

#[test]
fn reference_backend_executes_shared_snapshot_for_multiple_heads() {
    let shared = snapshot(1);
    let mut index = CompatibleModelIndexV1::new();
    index
        .register(
            id("head-a"),
            generation(1),
            digest("shared-encoder"),
            head("a", 0),
        )
        .expect("register a");
    index
        .register(
            id("head-b"),
            generation(1),
            digest("shared-encoder"),
            head("b", Q / 8),
        )
        .expect("register b");
    let backend = ReferenceBackendBatchV1::new(index, RetiredIdRegistryV1::new());
    let requests = vec![
        HeadExecutionRequestV1 {
            request_id: id("request-a"),
            model_id: id("head-a"),
            generation: generation(1),
            snapshot: shared.clone(),
        },
        HeadExecutionRequestV1 {
            request_id: id("request-b"),
            model_id: id("head-b"),
            generation: generation(1),
            snapshot: shared,
        },
    ];
    let outputs = backend.execute(&requests).expect("batch execution");
    assert_eq!(outputs.len(), 2);
    assert_eq!(outputs[0].output_q24, vec![Q / 2, -Q / 4]);
    assert_eq!(outputs[1].output_q24, vec![Q / 2 + Q / 8, -Q / 4 + Q / 8]);
    assert_eq!(outputs[0].authority, AuthorityPosture::DENY_ALL);
    assert_ne!(outputs[0].output_digest, outputs[1].output_digest);
}

#[test]
fn retired_id_rollover_rejects_old_route_and_reuse() {
    let shared = snapshot(2);
    let mut index = CompatibleModelIndexV1::new();
    index
        .register(
            id("old-head"),
            generation(1),
            digest("shared-encoder"),
            head("old", 0),
        )
        .expect("register old");
    index
        .register(
            id("new-head"),
            generation(2),
            digest("shared-encoder"),
            head("new", 0),
        )
        .expect("register new");
    let mut retired = RetiredIdRegistryV1::new();
    let receipt = retired
        .retire(id("old-head"), generation(1), id("new-head"), generation(2))
        .expect("retire");
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(
        retired.replacement(&id("old-head")),
        Some((&id("new-head"), generation(2)))
    );
    assert_eq!(
        retired.retire(
            id("old-head"),
            generation(1),
            id("other-head"),
            generation(3)
        ),
        Err(DataPlaneError::InvalidRollover)
    );

    let backend = ReferenceBackendBatchV1::new(index, retired);
    assert_eq!(backend.compatible_models(&shared, 2), vec![id("new-head")]);
    let request = HeadExecutionRequestV1 {
        request_id: id("request-old"),
        model_id: id("old-head"),
        generation: generation(1),
        snapshot: shared,
    };
    assert_eq!(
        backend.execute(&[request]),
        Err(DataPlaneError::ModelRetired)
    );
}

#[test]
fn retired_id_rollover_requires_a_loaded_replacement_generation() {
    let mut index = CompatibleModelIndexV1::new();
    index
        .register(
            id("old-head"),
            generation(1),
            digest("shared-encoder"),
            head("old", 0),
        )
        .expect("register old");
    let mut retired = RetiredIdRegistryV1::new();
    retired
        .retire(
            id("old-head"),
            generation(1),
            id("missing-head"),
            generation(2),
        )
        .expect("retire");
    assert_eq!(
        ReferenceBackendBatchV1::try_new(index, retired),
        Err(DataPlaneError::InvalidRollover)
    );
}

#[test]
fn feature_digest_and_generation_fences_reject_bad_input() {
    let features = vec![Q, 0];
    assert_eq!(
        FeatureSnapshotV1::new(
            digest("encoder"),
            generation(1),
            digest("wrong-input"),
            features,
        ),
        Err(DataPlaneError::FeatureDigestMismatch)
    );
    let stale = snapshot(1);
    let mut cache = FeatureSnapshotCacheV1::new(generation(2), 1).expect("cache");
    assert_eq!(
        cache.insert(stale),
        Err(DataPlaneError::StaleCacheGeneration)
    );
}

#[test]
fn reference_backend_rejects_snapshot_generation_drift() {
    let mut index = CompatibleModelIndexV1::new();
    index
        .register(
            id("head"),
            generation(1),
            digest("shared-encoder"),
            head("head", 0),
        )
        .expect("register");
    let backend = ReferenceBackendBatchV1::new(index, RetiredIdRegistryV1::new());
    let request = HeadExecutionRequestV1 {
        request_id: id("generation-drift"),
        model_id: id("head"),
        generation: generation(1),
        snapshot: snapshot(2),
    };
    assert_eq!(
        backend.execute(&[request]),
        Err(DataPlaneError::ModelGenerationMismatch)
    );
}

#[test]
fn reference_backend_rejects_head_output_outside_neuron_q24_range() {
    let mut oversized = head("oversized", 8 * Q);
    oversized.weights_q24 = vec![vec![8 * Q, 8 * Q], vec![8 * Q, 8 * Q]];
    let mut index = CompatibleModelIndexV1::new();
    index
        .register(
            id("oversized"),
            generation(1),
            digest("shared-encoder"),
            oversized,
        )
        .expect("register");
    let backend = ReferenceBackendBatchV1::new(index, RetiredIdRegistryV1::new());
    let request = HeadExecutionRequestV1 {
        request_id: id("overflow"),
        model_id: id("oversized"),
        generation: generation(1),
        snapshot: snapshot(1),
    };
    assert_eq!(
        backend.execute(&[request]),
        Err(DataPlaneError::OutputOutOfRange)
    );
}

#[test]
fn microbatch_plan_freezes_shared_snapshot_and_rejects_empty_or_mixed_batches() {
    let shared = snapshot(1);
    let request = |request_id: &str, model_id: &str| HeadExecutionRequestV1 {
        request_id: id(request_id),
        model_id: id(model_id),
        generation: generation(1),
        snapshot: shared.clone(),
    };
    assert_eq!(
        plan_microbatch_v1(id("worker"), generation(1), 10, 100, Vec::new()),
        Err(DataPlaneError::InvalidMicrobatchPlan)
    );
    let plan = plan_microbatch_v1(
        id("worker"),
        generation(1),
        10,
        100,
        vec![
            request("request-a", "head-a"),
            request("request-b", "head-b"),
        ],
    )
    .expect("plan");
    assert_eq!(plan.requests().len(), 2);
    assert_ne!(plan.plan_digest(), Digest32::ZERO);
    plan.validate(99).expect("valid before deadline");
    assert_eq!(
        plan.validate(100),
        Err(DataPlaneError::InvalidMicrobatchPlan)
    );
    let mixed = HeadExecutionRequestV1 {
        request_id: id("request-c"),
        model_id: id("head-c"),
        generation: generation(1),
        snapshot: snapshot_with_identity(1, "different-scope"),
    };
    assert_eq!(
        plan_microbatch_v1(
            id("worker"),
            generation(1),
            10,
            100,
            vec![request("request-a", "head-a"), mixed]
        ),
        Err(DataPlaneError::InvalidMicrobatchPlan)
    );
}

#[test]
fn microbatch_plan_rejects_duplicate_request_ids_and_generation_drift() {
    let shared = snapshot(1);
    let duplicate = HeadExecutionRequestV1 {
        request_id: id("request-a"),
        model_id: id("head-b"),
        generation: generation(1),
        snapshot: shared.clone(),
    };
    let duplicate_again = HeadExecutionRequestV1 {
        request_id: id("request-a"),
        model_id: id("head-c"),
        generation: generation(1),
        snapshot: shared,
    };
    assert_eq!(
        plan_microbatch_v1(
            id("worker"),
            generation(1),
            10,
            100,
            vec![duplicate, duplicate_again],
        ),
        Err(DataPlaneError::InvalidMicrobatchPlan)
    );
}

#[test]
fn wire_compatibility_rejects_hidden_width_above_existing_runtime_limit() {
    let oversized = LightweightHeadV1 {
        head_digest: digest("wire-oversized"),
        feature_width: NEURON_WIRE_MAX_FEATURES_V1 + 1,
        output_width: 1,
        weights_q24: vec![vec![0; NEURON_WIRE_MAX_FEATURES_V1 + 1]],
        bias_q24: vec![0],
    };
    assert_eq!(
        oversized.validate_neuron_wire_compatibility(),
        Err(DataPlaneError::WireDimensionMismatch)
    );
}

#[test]
fn microbatch_plan_freezes_shared_snapshot_and_deadline() {
    let shared = snapshot(1);
    let requests = vec![
        HeadExecutionRequestV1 {
            request_id: id("plan-request-a"),
            model_id: id("head-a"),
            generation: generation(1),
            snapshot: shared.clone(),
        },
        HeadExecutionRequestV1 {
            request_id: id("plan-request-b"),
            model_id: id("head-b"),
            generation: generation(1),
            snapshot: shared,
        },
    ];
    let plan = plan_microbatch_v1(id("worker"), generation(1), 10, 20, requests).expect("plan");
    assert_eq!(plan.requests().len(), 2);
    assert_ne!(plan.plan_digest(), Digest32::ZERO);
    plan.validate(19).expect("before deadline");
    assert_eq!(
        plan.validate(20),
        Err(DataPlaneError::InvalidMicrobatchPlan)
    );
}

#[test]
fn microbatch_plan_rejects_mixed_snapshot_identity_or_generation() {
    let requests = vec![
        HeadExecutionRequestV1 {
            request_id: id("mixed-request-a"),
            model_id: id("head-a"),
            generation: generation(1),
            snapshot: snapshot_with_identity(1, "a"),
        },
        HeadExecutionRequestV1 {
            request_id: id("mixed-request-b"),
            model_id: id("head-b"),
            generation: generation(1),
            snapshot: snapshot_with_identity(1, "b"),
        },
    ];
    assert_eq!(
        plan_microbatch_v1(id("worker"), generation(1), 10, 20, requests),
        Err(DataPlaneError::InvalidMicrobatchPlan)
    );
}
