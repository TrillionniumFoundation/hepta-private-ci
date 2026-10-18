use super::*;
use serde_json::json;
fn gates() -> Gates {
    Gates {
        zero_confidence_error_q24: 2 * (1 << 24),
        maximum_in_domain_error_q24: 2 * (1 << 24),
        minimum_confidence_ppm: 900_000,
        maximum_ood_ppm: 750_000,
        minimum_accuracy_ppm: 500_000,
        maximum_ece_ppm: 500_000,
        maximum_false_acceptance_ppm: 100_000,
        maximum_p99_latency_micros: 100_000,
        maximum_resident_bytes: 1 << 29,
        maximum_transient_allocation_bytes: 1 << 24,
    }
}
#[test]
fn original_max_absolute_sparse_error_controls_confidence_and_abstention() {
    let mut drive = [0_i64; 10];
    drive[0] = 1 << 24;
    drive[1] = -(1 << 24);
    let prediction = [0_i64; 10];
    let value = json!({"drive_q24":drive,"prediction_q24":prediction});
    assert_eq!(confidence(&value, &gates()).unwrap(), (500_000, true));
    let mut policy = gates();
    policy.minimum_confidence_ppm = 400_000;
    assert_eq!(confidence(&value, &policy).unwrap(), (500_000, false));
    policy.maximum_ood_ppm = 400_000;
    assert_eq!(confidence(&value, &policy).unwrap(), (500_000, true));
    assert!(confidence(&json!({"drive_q24":[1,2],"prediction_q24":[1,2]}), &policy).is_err());
    policy.zero_confidence_error_q24 = 0;
    assert!(policy.validate().is_err());
}
