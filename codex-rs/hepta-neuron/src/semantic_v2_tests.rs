use super::*;

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn id(label: &str) -> StableId {
    StableId::new(label).expect("stable fixture id")
}

fn identity() -> ModelSemanticIdentityV2 {
    ModelSemanticIdentityV2 {
        model_id: id("model-v2"),
        model_manifest_digest: digest("manifest"),
        weights_digest: digest("weights"),
        tokenizer_digest: digest("tokenizer"),
        preprocessor_digest: digest("preprocessor"),
        quantization_id: id("q4-k-m"),
        quantization_digest: digest("quantization"),
        backend_id: id("laya-cpu"),
        runtime_digest: digest("runtime"),
        device_identity_digest: digest("device"),
        encoder_digest: digest("encoder"),
        head_digest: digest("head"),
        artifact_use_digest: digest("artifact-use"),
    }
}

#[test]
fn telemetry_is_not_semantic_identity() {
    let semantic = identity();
    let first = ModelExecutionObservationV1 {
        latency_micros: 10,
        queue_age_micros: 2,
        resident_bytes: 1_000,
        transient_allocation_bytes: 50,
        observed_at_monotonic_micros: 100,
    };
    let second = ModelExecutionObservationV1 {
        latency_micros: 99,
        queue_age_micros: 20,
        resident_bytes: 9_000,
        transient_allocation_bytes: 500,
        observed_at_monotonic_micros: 101,
    };
    assert_eq!(
        semantic.semantic_digest().expect("semantic digest"),
        semantic.semantic_digest().expect("semantic digest")
    );
    assert_ne!(
        first.observation_digest().expect("first observation"),
        second.observation_digest().expect("second observation")
    );
}

#[test]
fn backend_quantization_and_bundle_are_frozen() {
    let first = identity();
    let mut second = first.clone();
    second.backend_id = id("laya-cuda");
    assert_ne!(
        first.semantic_digest().expect("first semantic"),
        second.semantic_digest().expect("second semantic")
    );
    second = first.clone();
    second.quantization_id = id("q8");
    assert_ne!(
        first.semantic_digest().expect("first semantic"),
        second.semantic_digest().expect("second semantic")
    );

    let body = NeuronBodyBundleIdentityV1 {
        body_manifest_digest: digest("body-manifest"),
        body_generation: Generation::new(3).expect("generation"),
        base_bundle_digest: digest("base"),
        organ_id: id("organ-1"),
        organ_bundle_digest: digest("organ"),
        cell_slot_id: Some(id("cell-7")),
        cell_bundle_digest: Some(digest("cell")),
        effective_parameter_digest: digest("parameters"),
        source_revision_digest: digest("source-revision"),
    };
    let mut changed = body.clone();
    changed.effective_parameter_digest = digest("other-parameters");
    assert_ne!(
        body.semantic_digest().expect("body semantic"),
        changed.semantic_digest().expect("changed body semantic")
    );
}

#[test]
fn calibration_expiry_policy_is_explicit() {
    assert_eq!(
        CalibrationExpiryPolicyV1::RejectBeforeMutation
            .decide(11, 1, 10)
            .expect("decision"),
        CalibrationWindowDecisionV1::RejectNoUpdate
    );
    assert_eq!(
        CalibrationExpiryPolicyV1::StateAdvanceAbstainLegacy
            .decide(11, 1, 10)
            .expect("decision"),
        CalibrationWindowDecisionV1::StateAdvanceAbstainLegacy
    );
    assert_eq!(
        CalibrationExpiryPolicyV1::RejectBeforeMutation
            .decide(5, 1, 10)
            .expect("decision"),
        CalibrationWindowDecisionV1::Admit
    );
}

#[test]
fn disposition_is_canonical_and_round_trips() {
    let value = NeuronCommitDispositionV1::degraded(
        vec![
            DegradationReasonV1::WriteAmplificationEnvelope,
            DegradationReasonV1::LatencyEnvelope,
        ],
        vec![AbstainReasonV1::OutOfDomain],
    )
    .expect("disposition");
    let encoded = value.encode_canonical().expect("encode");
    assert_eq!(
        NeuronCommitDispositionV1::decode_canonical(&encoded).expect("decode"),
        value
    );
    assert!(matches!(
        NeuronCommitDispositionV1::degraded(
            vec![
                DegradationReasonV1::LatencyEnvelope,
                DegradationReasonV1::LatencyEnvelope,
            ],
            Vec::new(),
        ),
        Err(NeuronSemanticV2Error::DuplicateReason)
    ));
}
