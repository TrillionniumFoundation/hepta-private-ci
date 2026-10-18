#![allow(clippy::unwrap_used)]
use super::*;

fn profile() -> ConservativeCpuRuntimeProfileV2 {
    ConservativeCpuRuntimeProfileV2 {
        input_feature_dimension: 10,
        state_width: 10,
        modulator_dimension: 2,
        maximum_inflight: 1,
        maximum_load_bytes: 1 << 26,
        p95_latency_micros: 500,
        p99_latency_micros: 1_000,
        transient_allocation_bytes: 1 << 20,
        checkpoint_bytes: 1 << 20,
        write_amplification_ppm: 4_000_000,
        calibration_gates: OperationalCalibrationGatesV2 {
            zero_confidence_error_q24: 1 << 24,
            maximum_in_domain_error_q24: 2 << 24,
            minimum_confidence_ppm: 500_000,
            maximum_ood_ppm: 500_000,
            minimum_accuracy_ppm: 500_000,
            maximum_ece_ppm: 500_000,
            maximum_false_acceptance_ppm: 500_000,
            maximum_p99_latency_micros: 10_000,
            maximum_resident_bytes: 1 << 28,
            maximum_transient_allocation_bytes: 1 << 24,
        },
    }
}
fn binding() -> OperationalModelLeaseBindingV2 {
    let pin = Digest32::of_bytes(b"frozen-model-input");
    OperationalModelLeaseBindingV2 {
        model_generation: 1,
        model_manifest_digest: pin,
        weights_digest: pin,
        normalization_digest: pin,
        encoder_manifest_digest: pin,
        tokenizer_digest: pin,
        training_code_digest: pin,
        source_training_digest: pin,
        preregistration_digest: pin,
        body_implementation_digest: pin,
        model_runtime_profile_digest: profile().semantic_digest().unwrap(),
        purpose: OperationalModelUseV2::ConservativeCpuAbstentionOnlyV1,
    }
}

#[test]
fn altered_model_source_body_or_profile_cannot_reuse_the_stable_binding() {
    let original = binding();
    let digest = original.binding_digest().unwrap();
    let changes: [fn(&mut OperationalModelLeaseBindingV2); 10] = [
        |v| v.model_manifest_digest = Digest32::of_bytes(b"new manifest"),
        |v| v.weights_digest = Digest32::of_bytes(b"new weights"),
        |v| v.normalization_digest = Digest32::of_bytes(b"new normalization"),
        |v| v.encoder_manifest_digest = Digest32::of_bytes(b"new encoder"),
        |v| v.tokenizer_digest = Digest32::of_bytes(b"new tokenizer"),
        |v| v.training_code_digest = Digest32::of_bytes(b"new training code"),
        |v| v.source_training_digest = Digest32::of_bytes(b"new source"),
        |v| v.preregistration_digest = Digest32::of_bytes(b"new registration"),
        |v| v.body_implementation_digest = Digest32::of_bytes(b"new body"),
        |v| v.model_runtime_profile_digest = Digest32::of_bytes(b"new profile"),
    ];
    for change in changes {
        let mut changed = original.clone();
        change(&mut changed);
        assert_ne!(changed.binding_digest().unwrap(), digest);
    }
}

#[test]
fn future_generation_and_missing_pins_do_not_enter_bootstrap_scope() {
    let mut changed = binding();
    changed.model_generation = 2;
    assert!(changed.binding_digest().is_err());
    changed = binding();
    changed.body_implementation_digest = Digest32::ZERO;
    assert!(changed.binding_digest().is_err());
}

#[test]
fn original_exclusive_resource_bounds_remain_closed() {
    let mut changed = profile();
    changed.write_amplification_ppm = 4_000_001;
    assert!(changed.semantic_digest().is_err());
    changed = profile();
    changed.input_feature_dimension = 513;
    assert!(changed.semantic_digest().is_err());
    changed = profile();
    changed.state_width = 4;
    assert!(changed.semantic_digest().is_err());
}

#[test]
fn declared_ceiling_cannot_exceed_frozen_measured_gate() {
    let mut changed = profile();
    changed.p99_latency_micros = changed.calibration_gates.maximum_p99_latency_micros + 1;
    assert!(changed.semantic_digest().is_err());
    changed = profile();
    changed.transient_allocation_bytes =
        changed.calibration_gates.maximum_transient_allocation_bytes + 1;
    assert!(changed.semantic_digest().is_err());
}

#[test]
fn changed_runtime_ceiling_requires_a_different_stable_profile() {
    let original = profile();
    let mut changed = original.clone();
    changed.maximum_inflight = 2;
    assert_ne!(
        original.semantic_digest().unwrap(),
        changed.semantic_digest().unwrap()
    );
    changed = original.clone();
    changed.checkpoint_bytes *= 2;
    assert_ne!(
        original.semantic_digest().unwrap(),
        changed.semantic_digest().unwrap()
    );
    changed = original.clone();
    changed.calibration_gates.minimum_accuracy_ppm += 1;
    assert_ne!(
        original.semantic_digest().unwrap(),
        changed.semantic_digest().unwrap()
    );
}
