use super::evaluate;
use super::Q32;
use super::RECURSIVE_PROFILE;
use super::SCHEMA;
use serde_json::json;
use serde_json::Value;

fn path(candidate_id: &str, instants: &[i64]) -> Value {
    let events: Vec<_> = instants
        .iter()
        .enumerate()
        .map(|(index, instant)| {
            json!({
                "event_digest": format!("{:064x}", index + 1),
                "preference_digest": "2".repeat(64),
                "instant_q32": instant * Q32,
                "discount_q32": Q32
            })
        })
        .collect();
    json!({
        "id": candidate_id, "verified": true,
        "verification_digest": "3".repeat(64), "support_digest": "4".repeat(64),
        "resource_cost_q32": 0, "risk_q32": 0, "uncertainty_q32": 0,
        "terminal_q32": 0, "events": events
    })
}

fn request(mut candidates: Vec<Value>) -> Value {
    candidates.push(path("abstain", &[0]));
    json!({
        "schema": SCHEMA, "recursive_profile": RECURSIVE_PROFILE, "objective_digest": "2".repeat(64),
        "snapshot_digest": "5".repeat(64), "generation": 1,
        "utility_unit": "task-return", "resource_unit": "task-cost",
        "risk_unit": "probability", "resource_budget_q32": 10 * Q32,
        "risk_ceiling_q32": Q32 / 2, "candidates": candidates
    })
}

fn response(request: &Value) -> Value {
    evaluate(&serde_json::to_vec(request).expect("serialize the protocol fixture"))
        .expect("evaluate the bounded fixture with the original NDU")
}

#[test]
fn original_recursive_utility_keeps_later_value_and_refusal_cost() {
    let first = path("immediate", &[5, 0]);
    let second = path("continue", &[-3, 20]);
    let result = response(&request(vec![first.clone(), second]));
    assert_eq!(result["advisory_candidate_id"], json!("continue"));
    assert_eq!(
        result["paths"][1]["values_q32"],
        json!([17 * Q32, 20 * Q32, 0])
    );
    assert_eq!(result["authority"], json!("DENY_ALL"));
    assert_eq!(result["safety_certificate"], json!(false));

    // An actually refused continuation cannot keep its unrealized reward.
    let refused = path("continue", &[-3, -2]);
    let result = response(&request(vec![first, refused]));
    assert_eq!(result["advisory_candidate_id"], json!("immediate"));
    assert_eq!(
        result["paths"][1]["values_q32"],
        json!([-5 * Q32, -2 * Q32, 0])
    );
}

#[test]
fn native_feasibility_rejects_hard_resource_and_risk_violations_before_value() {
    let mut hard = path("unverified", &[100]);
    hard["verified"] = json!(false);
    let mut resource = path("over-budget", &[90]);
    resource["resource_cost_q32"] = json!(11 * Q32);
    let mut risk = path("over-risk", &[80]);
    risk["risk_q32"] = json!(Q32);
    let result = response(&request(vec![hard, resource, risk, path("valid", &[1])]));
    assert_eq!(result["advisory_candidate_id"], json!("valid"));
    assert_eq!(
        result["rejected"],
        json!([
            {"id": "over-budget", "reasons": ["ResourceCeilingExceeded"]},
            {"id": "over-risk", "reasons": ["RiskCeilingExceeded"]},
            {"id": "unverified", "reasons": ["HardConstraintViolation"]}
        ])
    );
}

#[test]
fn missing_evidence_duplicate_events_and_unknown_fields_fail_closed() {
    let mut missing = request(vec![path("candidate", &[2])]);
    missing["candidates"][0]["verification_digest"] = json!("0".repeat(64));
    assert!(evaluate(&serde_json::to_vec(&missing).expect("serialize missing evidence")).is_err());
    let mut duplicate = request(vec![path("candidate", &[2, 3])]);
    duplicate["candidates"][0]["events"][1]["event_digest"] =
        duplicate["candidates"][0]["events"][0]["event_digest"].clone();
    assert!(evaluate(&serde_json::to_vec(&duplicate).expect("serialize duplicate event")).is_err());
    let mut unknown = request(vec![path("candidate", &[2])]);
    unknown["grant_deployment"] = json!(true);
    assert!(evaluate(&serde_json::to_vec(&unknown).expect("serialize unknown field")).is_err());
}

#[test]
fn abstention_and_equal_frontiers_remain_explicit_without_arbitrary_authority() {
    let result = response(&request(vec![path("negative", &[-2])]));
    assert_eq!(result["advisory_candidate_id"], json!("abstain"));
    let result = response(&request(vec![path("one", &[3]), path("two", &[3])]));
    assert_eq!(result["advisory_candidate_id"], Value::Null);
    assert_eq!(result["pareto_candidate_ids"], json!(["one", "two"]));
}

#[test]
fn exact_request_snapshot_and_objective_bind_native_receipt_identity() {
    let mut payload = request(vec![path("candidate", &[2])]);
    let original = response(&payload);
    payload["snapshot_digest"] = json!("6".repeat(64));
    let moved = response(&payload);
    assert_ne!(original["evaluation_digest"], moved["evaluation_digest"]);
    assert_ne!(original["request_digest"], moved["request_digest"]);
    payload["objective_digest"] = json!("7".repeat(64));
    let changed_goal = response(&payload);
    assert_ne!(
        moved["evaluation_digest"],
        changed_goal["evaluation_digest"]
    );
}

#[test]
fn unregistered_recursive_profile_or_unit_is_rejected() {
    let mut payload = request(vec![path("candidate", &[2])]);
    payload["recursive_profile"] = json!("hepta.entropic.unregistered");
    assert!(evaluate(&serde_json::to_vec(&payload).expect("serialize wrong profile")).is_err());
    let mut payload = request(vec![path("candidate", &[2])]);
    payload["utility_unit"] = json!("nanoseconds");
    assert!(evaluate(&serde_json::to_vec(&payload).expect("serialize wrong unit")).is_err());
}
