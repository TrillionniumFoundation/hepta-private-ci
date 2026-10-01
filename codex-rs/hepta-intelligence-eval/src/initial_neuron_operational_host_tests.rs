use super::*;
#[test]
fn initial_anchor_never_reinterprets_generation_or_primary_qualification() {
    let digest = Digest32::of_bytes(b"a real frozen source").to_string();
    let original = json!({"schema":"hepta.cpu-neuron.initial-operational-policy.v1",
        "generation":1,"qualified_predecessor":null,"scope_digest":digest,"objective_digest":digest,
        "baseline_manifest_digest":digest,"baseline_weights_digest":digest,"source_training_digest":digest,
        "preregistration_digest":digest,"frozen_at_ms":100,"expires_at_ms":10000,
        "calibration_rows":90,"ood_rows":69,
        "claim_scope":"initial-operational;training-source-reused;no-unseen-holdout;no-primary-superiority",
        "gates":{"zero_confidence_error_q24":33554432,"maximum_in_domain_error_q24":33554432,
            "minimum_confidence_ppm":900000,"maximum_ood_ppm":750000,"minimum_accuracy_ppm":500000,
            "maximum_ece_ppm":500000,"maximum_false_acceptance_ppm":100000,
            "maximum_p99_latency_micros":100000,"maximum_resident_bytes":536870912,
            "maximum_transient_allocation_bytes":16777216}});
    serde_json::from_value::<Policy>(original.clone())
        .unwrap()
        .validate(101)
        .unwrap();
    for (field, value) in [
        ("generation", json!(2)),
        ("qualified_predecessor", json!(digest)),
        ("claim_scope", json!("primary_superiority")),
        ("frozen_at_ms", json!(102)),
        ("expires_at_ms", json!(101)),
    ] {
        let mut changed = original.clone();
        changed[field] = value;
        assert!(
            serde_json::from_value::<Policy>(changed)
                .unwrap()
                .validate(101)
                .is_err()
        );
    }
    let actual = payload(&json!({"measured":true})).unwrap();
    let paired = crate::calibration_preflight_signing_payload_v1(
        b"measured",
        codex_hepta_types::FixedQ32::ZERO,
    )
    .unwrap();
    assert_ne!(actual, paired);
}
