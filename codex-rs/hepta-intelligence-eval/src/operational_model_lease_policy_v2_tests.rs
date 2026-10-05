#![allow(clippy::unwrap_used)]
use super::*;
use serde_json::Value;
use serde_json::json;
fn policy() -> Value {
    let pin = Digest32::of_bytes(b"original protected material").to_string();
    let profile = json!({"input_feature_dimension":512,"state_width":10,"modulator_dimension":1,"maximum_inflight":1,"maximum_load_bytes":1000000,
        "p95_latency_micros":50000,"p99_latency_micros":100000,"transient_allocation_bytes":1000000,"checkpoint_bytes":1000000,"write_amplification_ppm":4000000,
        "calibration_gates":{"zero_confidence_error_q24":33554432,"maximum_in_domain_error_q24":33554432,"minimum_confidence_ppm":900000,"maximum_ood_ppm":750000,"minimum_accuracy_ppm":500000,"maximum_ece_ppm":500000,"maximum_false_acceptance_ppm":100000,"maximum_p99_latency_micros":100000,"maximum_resident_bytes":536870912,"maximum_transient_allocation_bytes":16777216}});
    let profile_digest = serde_json::from_value::<ConservativeCpuRuntimeProfileV2>(profile.clone())
        .unwrap()
        .semantic_digest()
        .unwrap();
    json!({"schema":"hepta.cpu-neuron.operational-model-lease-policy.v2","scope_digest":pin,"binding":{
        "model_generation":1,"model_manifest_digest":pin,"weights_digest":pin,"normalization_digest":pin,"encoder_manifest_digest":pin,"tokenizer_digest":pin,"training_code_digest":pin,"source_training_digest":pin,"preregistration_digest":pin,"body_implementation_digest":pin,"model_runtime_profile_digest":profile_digest.to_string(),"purpose":"ConservativeCpuAbstentionOnlyV1"},
        "runtime_profile":profile,"material":{
            "normalization":{"path":"/unused/norm","digest":pin},"encoder_manifest":{"path":"/unused/manifest","digest":pin},"encoder_gguf":{"path":"/unused/gguf","digest":pin},"training_code":{"path":"/unused/training","digest":pin},"body_implementation":{"path":"/unused/body","digest":pin}},
        "frozen_at_ms":100,"expires_at_ms":10000,"calibration_rows":90,"ood_rows":69})
}
#[test]
fn stable_policy_binding_preserves_exclusive_expiry_and_original_day_cap() {
    let original = policy();
    let parsed: Policy = serde_json::from_value(original.clone()).unwrap();
    let binding = parsed.validate(101).unwrap();
    let native = parsed.native_policy(&binding).unwrap();
    assert_eq!(
        native.objective_digest,
        binding.binding_digest().unwrap().to_string()
    );
    assert!(parsed.validate(99).is_err());
    assert!(parsed.validate(10000).is_err());
    for (pointer, value) in [
        ("/expires_at_ms", json!(86400101)),
        ("/binding/model_generation", json!(2)),
        (
            "/binding/body_implementation_digest",
            json!(Digest32::ZERO.to_string()),
        ),
        ("/runtime_profile/write_amplification_ppm", json!(4000001)),
        (
            "/material/normalization/digest",
            json!(Digest32::of_bytes(b"substitution").to_string()),
        ),
    ] {
        let mut changed = original.clone();
        *changed.pointer_mut(pointer).unwrap() = value;
        assert!(
            serde_json::from_value::<Policy>(changed)
                .unwrap()
                .validate(101)
                .is_err()
        );
    }
}
#[test]
fn goal_promotion_or_unknown_material_cannot_be_added_to_the_v2_policy() {
    for (field, value) in [
        (
            "goal_digest",
            json!(Digest32::of_bytes(b"goal").to_string()),
        ),
        ("qualified", json!(true)),
        ("qualified_predecessor", json!(null)),
    ] {
        let mut changed = policy();
        changed[field] = value;
        assert!(serde_json::from_value::<Policy>(changed).is_err());
    }
    let mut changed = policy();
    changed["binding"]["purpose"] = json!("AcceptCpuAnswers");
    assert!(serde_json::from_value::<Policy>(changed).is_err());
}
#[test]
fn a_new_policy_window_does_not_change_the_stable_model_class() {
    let original: Policy = serde_json::from_value(policy()).unwrap();
    let mut changed = policy();
    changed["frozen_at_ms"] = json!(1000);
    changed["expires_at_ms"] = json!(2000);
    changed["scope_digest"] = json!(Digest32::of_bytes(b"new scope").to_string());
    let renewed: Policy = serde_json::from_value(changed).unwrap();
    assert_eq!(
        original.validate(101).unwrap().binding_digest().unwrap(),
        renewed.validate(1001).unwrap().binding_digest().unwrap()
    );
    assert_eq!(original.runtime_profile, renewed.runtime_profile);
}
