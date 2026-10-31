use super::Q32;
use super::SCHEMA;
use super::evaluate;
use serde_json::Value;
use serde_json::json;

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
        "schema": SCHEMA, "objective_digest": "2".repeat(64),
        "snapshot_digest": "5".repeat(64), "generation": 1,
        "utility_unit": "fixture-points", "resource_unit": "microseconds",
        "risk_unit": "probability", "resource_budget_q32": 10 * Q32,
        "risk_ceiling_q32": Q32 / 2, "candidates": candidates
    })
}

fn response(request: &Value) -> Value {
    evaluate(&serde_json::to_vec(request).expect("serialize the protocol fixture"))
        .expect("evaluate the bounded fixture with the original NDU")
}

#[test]
fn stream_preserves_native_results_and_exact_request_identity() {
    let first = serde_json::to_vec(&request(vec![path("first", &[3, 7])]))
        .expect("encode the first actual request");
    let second = serde_json::to_vec(&request(vec![path("second", &[-5, 19])]))
        .expect("encode the second actual request");
    let mut input = first.clone();
    input.push(b'\n');
    input.extend_from_slice(&second);
    input.push(b'\n');
    let mut output = Vec::new();
    super::stream::run(std::io::Cursor::new(input), &mut output)
        .expect("evaluate both requests in the bounded stream");
    let lines: Vec<Value> = output
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty())
        .map(|line| serde_json::from_slice(line).expect("decode the actual stream result"))
        .collect();
    assert_eq!(lines.len(), 3);
    assert_eq!(lines[0]["identity"], super::identity());
    for (index, raw) in [first, second].iter().enumerate() {
        assert_eq!(lines[index + 1]["sequence"], json!(index + 1));
        assert_eq!(
            lines[index + 1]["response"],
            evaluate(raw).expect("compare with the same original native evaluator")
        );
    }
}

#[test]
fn stream_refuses_partial_oversized_and_invalid_frames_without_a_later_result() {
    let valid =
        serde_json::to_vec(&request(vec![path("valid", &[1])])).expect("encode a valid request");
    for invalid in [valid.clone(), vec![b' '; 1_048_578], b"{}\n".to_vec()] {
        let mut output = Vec::new();
        assert!(super::stream::run(std::io::Cursor::new(invalid), &mut output).is_err());
        assert_eq!(output.iter().filter(|byte| **byte == b'\n').count(), 1);
    }
    let mut input = b"{}\n".to_vec();
    input.extend_from_slice(&valid);
    input.push(b'\n');
    let mut output = Vec::new();
    assert!(super::stream::run(std::io::Cursor::new(input), &mut output).is_err());
    assert_eq!(output.iter().filter(|byte| **byte == b'\n').count(), 1);
}

#[test]
fn stream_request_limit_is_a_hard_stop() {
    let mut line = serde_json::to_vec(&request(vec![path("bounded", &[1])]))
        .expect("encode a bounded request");
    line.push(b'\n');
    let input = line.repeat(257);
    let mut output = Vec::new();
    let failure = super::stream::run(std::io::Cursor::new(input), &mut output);
    assert_eq!(
        failure,
        Err("stream request budget of 256 exhausted".into())
    );
    assert_eq!(output.iter().filter(|byte| **byte == b'\n').count(), 257);
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
fn mandatory_zero_abstain_guards_negative_only_plans() {
    let mut missing = request(vec![path("negative", &[-10])]);
    missing["candidates"]
        .as_array_mut()
        .expect("candidate array in fixture")
        .retain(|candidate| candidate["id"] != "abstain");
    let absent_wire = serde_json::to_vec(&missing).expect("encode missing-abstain fixture");
    assert_eq!(
        evaluate(&absent_wire),
        Err("missing mandatory abstain candidate".into())
    );

    // The action-set guard runs before expensive or invalid path evaluation.
    let mut malformed_path = missing;
    malformed_path["candidates"][0]["events"][0]["discount_q32"] = json!(-1);
    let malformed_wire = serde_json::to_vec(&malformed_path).expect("encode bad path");
    assert_eq!(
        evaluate(&malformed_wire),
        Err("missing mandatory abstain candidate".into())
    );

    let mut uncertain = request(vec![path("negative", &[-10])]);
    uncertain["candidates"][1]["uncertainty_q32"] = json!(Q32 / 2);
    let uncertain_wire = serde_json::to_vec(&uncertain).expect("encode invalid abstain");
    assert_eq!(
        evaluate(&uncertain_wire),
        Err("abstain must be an exact zero-effect, zero-cost alternative".into())
    );

    let valid = request(vec![path("negative", &[-10])]);
    assert_eq!(response(&valid)["advisory_candidate_id"], json!("abstain"));
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
