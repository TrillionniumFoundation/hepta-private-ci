use super::*;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn id(label: &str) -> StableId {
    checked(StableId::new(label))
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
        checked(semantic.semantic_digest()),
        checked(semantic.semantic_digest())
    );
    assert_ne!(
        checked(first.observation_digest()),
        checked(second.observation_digest())
    );
}

#[test]
fn backend_quantization_and_bundle_are_frozen() {
    let first = identity();
    let mut second = first.clone();
    second.backend_id = id("laya-cuda");
    assert_ne!(
        checked(first.semantic_digest()),
        checked(second.semantic_digest())
    );
    second = first.clone();
    second.quantization_id = id("q8");
    assert_ne!(
        checked(first.semantic_digest()),
        checked(second.semantic_digest())
    );

    let body = NeuronBodyBundleIdentityV1 {
        body_manifest_digest: digest("body-manifest"),
        body_generation: checked(Generation::new(3)),
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
        checked(body.semantic_digest()),
        checked(changed.semantic_digest())
    );
}

#[test]
fn calibration_expiry_policy_is_explicit() {
    assert_eq!(
        checked(CalibrationExpiryPolicyV1::RejectBeforeMutation.decide(11, 1, 10)),
        CalibrationWindowDecisionV1::RejectNoUpdate
    );
    assert_eq!(
        checked(CalibrationExpiryPolicyV1::StateAdvanceAbstainLegacy.decide(11, 1, 10)),
        CalibrationWindowDecisionV1::StateAdvanceAbstainLegacy
    );
    assert_eq!(
        checked(CalibrationExpiryPolicyV1::RejectBeforeMutation.decide(5, 1, 10)),
        CalibrationWindowDecisionV1::Admit
    );
}

#[test]
fn disposition_is_canonical_and_round_trips() {
    let value = checked(NeuronCommitDispositionV1::degraded(
        vec![
            DegradationReasonV1::WriteAmplificationEnvelope,
            DegradationReasonV1::LatencyEnvelope,
        ],
        vec![AbstainReasonV1::OutOfDomain],
    ));
    let encoded = checked(value.encode_canonical());
    assert_eq!(
        checked(NeuronCommitDispositionV1::decode_canonical(&encoded)),
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
