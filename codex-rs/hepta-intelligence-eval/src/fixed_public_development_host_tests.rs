//! Synthetic request guards only; actual G/encoder qualification is separate.
#![allow(clippy::unwrap_used)]
use super::*;
use crate::paired_supervised_test_support::digest;

fn input() -> serde_json::Value {
    serde_json::json!({
        "schema":"hepta.eval.public-development.measurement-inputs.v1",
        "purpose":PURPOSE,"batch_id":"public-development-fixture",
        "trust":{"root_id":"fixture-root","root_verifying_key_hex":"00".repeat(32),
          "root_valid_from":1,"root_expires_at":1000,"distribution_id":"fixture-distribution",
          "generation":1,"effective_at":1,"issued_at":1,"expires_at":800,
          "scope_digest":digest("fixture-scope").to_string(),"objective_digest":digest("fixture-objective").to_string(),
          "authority_epoch":1,"signers":[],"signature_hex":"00".repeat(64)},
        "encoder":{"socket":"/fixture/encoder.sock","config":{"path":"/fixture/config","digest":digest("config").to_string()},
          "normalization":digest("norm").to_string(),"tokenizer":digest("tokenizer").to_string(),
          "weights":digest("physical-weights").to_string(),"manifest":digest("physical-manifest").to_string()},
        "pairs":[{"pair_id":"first","source_row_sha256":digest("row-one").to_string()},
                  {"pair_id":"second","source_row_sha256":digest("row-two").to_string()}],
        "timeout_ms":1000,
    })
}
#[test]
fn first_measurement_requires_complete_distinct_public_feature_rows() {
    let original = input();
    assert!(
        serde_json::from_value::<Inputs>(original.clone())
            .unwrap()
            .validate()
            .is_ok()
    );
    for field in ["pair_id", "source_row_sha256"] {
        let mut repeated = original.clone();
        repeated["pairs"][1][field] = repeated["pairs"][0][field].clone();
        assert!(
            serde_json::from_value::<Inputs>(repeated)
                .unwrap()
                .validate()
                .is_err()
        );
    }
    let mut zero = original;
    zero["pairs"][0]["source_row_sha256"] = serde_json::json!(Digest32::ZERO.to_string());
    assert!(
        serde_json::from_value::<Inputs>(zero)
            .unwrap()
            .validate()
            .is_err()
    );
}
#[test]
fn public_measurement_has_no_goal_plan_or_arbitrary_text_ingress() {
    for (key, value) in [
        ("run_tuple", serde_json::json!({"run_id":"ordinary-goal"})),
        ("plan_inputs_hex", serde_json::json!("00")),
        ("private_key_path", serde_json::json!("/fixture/key")),
        ("claim_text", serde_json::json!("caller-chosen text")),
    ] {
        let mut value_with_authority = input();
        value_with_authority[key] = value;
        assert!(serde_json::from_value::<Inputs>(value_with_authority).is_err());
    }
    let mut ordinary = input();
    ordinary["purpose"] = serde_json::json!("OrdinaryGoalV2");
    assert!(
        serde_json::from_value::<Inputs>(ordinary)
            .unwrap()
            .validate()
            .is_err()
    );
}
#[test]
fn over_budget_empty_and_unbounded_batch_reject_before_transport() {
    for timeout in [0, 120_001] {
        let mut value = input();
        value["timeout_ms"] = serde_json::json!(timeout);
        assert!(
            serde_json::from_value::<Inputs>(value)
                .unwrap()
                .validate()
                .is_err()
        );
    }
    let mut empty = input();
    empty["pairs"] = serde_json::json!([]);
    assert!(
        serde_json::from_value::<Inputs>(empty)
            .unwrap()
            .validate()
            .is_err()
    );
    let mut unbounded = input();
    unbounded["pairs"] = serde_json::json!((0..257).map(|i| serde_json::json!({
        "pair_id":format!("pair-{i}"),"source_row_sha256":digest(&format!("row-{i}")).to_string(),
    })).collect::<Vec<_>>());
    assert!(
        serde_json::from_value::<Inputs>(unbounded)
            .unwrap()
            .validate()
            .is_err()
    );
}
