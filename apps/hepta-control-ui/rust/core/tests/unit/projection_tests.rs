use super::*;

fn fixture() -> Value {
    serde_json::from_str(include_str!("../fixtures/javascript-reference.json")).unwrap()
}

fn outcome<T: Serialize>(result: Result<T, ControlError>) -> Value {
    match result {
        Ok(value) => json!({ "ok": value }),
        Err(error) => json!({ "error": error.code.as_str(), "retryable": error.retryable }),
    }
}

#[test]
fn projections_and_hash_domains_match_actual_javascript() {
    let fixture = fixture();
    let runtime = project_runtime(&fixture["runtime"]["input"]).unwrap();
    assert_eq!(json!(runtime), fixture["runtime"]["projection"]);
    assert_eq!(
        digest_runtime_projection(&runtime).unwrap(),
        fixture["runtime"]["digest"]
    );
    let intent = build_operation_intent(&fixture["operation"]["input"]).unwrap();
    assert_eq!(json!(intent), fixture["operation"]["intent"]);
    assert_eq!(
        digest_operation_intent(&intent).unwrap(),
        fixture["operation"]["digest"]
    );
    let session = normalize_session(&fixture["session"]["input"], PROTOCOL_VERSION, 1000).unwrap();
    assert_eq!(json!(session), fixture["session"]["normalized"]);
    let snapshot = normalize_snapshot(&fixture["snapshot"]["input"], &session).unwrap();
    assert_eq!(json!(snapshot), fixture["snapshot"]["normalized"]);
    let canonical =
        canonical_json(&fixture["runtime"]["input"], &runtime_canonical_limits()).unwrap();
    assert_eq!(
        project_runtime_from_local_canonical_json(&canonical).unwrap(),
        runtime
    );
    let canonical =
        canonical_json(&fixture["operation"]["input"], &CanonicalLimits::default()).unwrap();
    assert_eq!(
        build_local_operation_proposal_from_canonical_json(&canonical).unwrap(),
        intent
    );
}

#[test]
fn snapshot_transitions_match_javascript_including_observation_retention() {
    let fixture = fixture();
    let session = normalize_session(&fixture["session"]["input"], PROTOCOL_VERSION, 1000).unwrap();
    let previous = normalize_snapshot(&fixture["snapshot"]["input"], &session).unwrap();
    for case in fixture["transitions"].as_array().unwrap() {
        let mut next = previous.clone();
        if let Some(changes) = case["change"].as_object() {
            for (key, value) in changes {
                match key.as_str() {
                    "sessionId" => next.session_id = value.as_str().unwrap().to_owned(),
                    "connectionGeneration" => next.connection_generation = value.as_u64().unwrap(),
                    "generation" => next.generation = value.as_u64().unwrap(),
                    "revision" => next.revision = value.as_u64().unwrap(),
                    "semanticDigest" => next.semantic_digest = value.as_str().unwrap().to_owned(),
                    "observedAt" => next.observed_at = value.as_str().map(str::to_owned),
                    _ => panic!("unknown fixture transition"),
                }
            }
        }
        let prior = (!case["change"].is_null()).then_some(&previous);
        assert_eq!(
            outcome(validate_snapshot_transition(prior, &next)),
            case["result"],
            "{}",
            case["name"]
        );
    }
}

#[test]
fn normalization_owns_session_snapshot_and_runtime_content() {
    let fixture = fixture();
    let mut session_input = fixture["session"]["input"].clone();
    let mut snapshot_input = fixture["snapshot"]["input"].clone();
    let session = normalize_session(&session_input, PROTOCOL_VERSION, 1000).unwrap();
    let snapshot = normalize_snapshot(&snapshot_input, &session).unwrap();
    let retained = snapshot.clone();
    session_input["permissions"][0] = json!("untrusted");
    session_input["identityId"] = json!("changed");
    snapshot_input["modules"][0]["semanticDigest"] = json!("c".repeat(64));
    snapshot_input["observedAt"] = json!("changed");
    assert_eq!(json!(session), fixture["session"]["normalized"]);
    assert_eq!(json!(snapshot), fixture["snapshot"]["normalized"]);
    assert_eq!(retained, snapshot);
}

#[test]
fn full_thousand_module_ceiling_includes_projection_and_snapshot_envelopes() {
    let fixture = fixture();
    let session = normalize_session(&fixture["session"]["input"], PROTOCOL_VERSION, 1000).unwrap();
    let modules: Vec<_> = (0..1000).rev().map(|index| json!({
        "id": format!("module.{index:04}"), "status": "ready", "revision": 1, "semanticDigest": "a".repeat(64),
    })).collect();
    let input = json!({"generation":1,"revision":1,"modules":modules});
    let projection = project_runtime(&input).unwrap();
    assert_eq!(projection.modules().len(), 1000);
    assert_eq!(projection.modules()[0].id(), "module.0000");
    digest_runtime_projection(&projection).unwrap();
    let snapshot_input = json!({"sessionId":session.session_id(),"connectionGeneration":1,"generation":1,"revision":1,"modules":modules});
    let snapshot = normalize_snapshot(&snapshot_input, &session).unwrap();
    assert_eq!(snapshot.modules(), projection.modules());
    let mut over_limit = input;
    over_limit["modules"]
        .as_array_mut()
        .unwrap()
        .push(json!({"id":"over","status":"ready","revision":1,"semanticDigest":"a".repeat(64)}));
    assert_eq!(
        project_runtime(&over_limit).unwrap_err().code,
        ErrorCode::InvalidInput
    );
}

#[test]
fn snapshot_digest_and_generation_declarations_fail_closed() {
    let fixture = fixture();
    let session = normalize_session(&fixture["session"]["input"], PROTOCOL_VERSION, 1000).unwrap();
    let input = &fixture["snapshot"]["input"];
    for (field, value, code) in [
        (
            "semanticDigest",
            json!("c".repeat(64)),
            ErrorCode::SnapshotDrift,
        ),
        ("semanticDigest", Value::Null, ErrorCode::InvalidInput),
        ("connectionGeneration", json!(2), ErrorCode::StaleGeneration),
        ("sessionId", json!("other"), ErrorCode::InvalidInput),
    ] {
        let mut changed = input.clone();
        changed[field] = value;
        assert_eq!(
            normalize_snapshot(&changed, &session).unwrap_err().code,
            code
        );
    }
    let mut declared = input.clone();
    declared["semanticDigest"] = fixture["snapshot"]["normalized"]["semanticDigest"].clone();
    assert_eq!(
        json!(normalize_snapshot(&declared, &session).unwrap()),
        fixture["snapshot"]["normalized"]
    );
}

#[test]
fn operation_domain_binds_every_field_and_local_proposal_rejects_extras() {
    let fixture = fixture();
    let baseline = &fixture["operation"]["input"];
    for (field, value) in [
        ("action", json!("request_stop")),
        ("targetId", json!("z.module")),
        ("generation", json!(3)),
        ("displayedRevision", json!(4)),
        ("reason", json!("Changed")),
    ] {
        let mut changed = baseline.clone();
        changed[field] = value;
        let intent = build_operation_intent(&changed).unwrap();
        assert_ne!(
            digest_operation_intent(&intent).unwrap(),
            fixture["operation"]["digest"]
        );
    }
    let mut extra = baseline.clone();
    extra["ignored"] = json!(true);
    assert_eq!(
        json!(build_operation_intent(&extra).unwrap()),
        fixture["operation"]["intent"]
    );
    let encoded = canonical_json(&extra, &CanonicalLimits::default()).unwrap();
    assert_eq!(
        build_local_operation_proposal_from_canonical_json(&encoded)
            .unwrap_err()
            .code,
        ErrorCode::InvalidInput
    );
}

#[test]
fn session_normalization_checks_authentication_expiry_permissions_and_protocol() {
    let fixture = fixture();
    let original = &fixture["session"]["input"];
    for (field, value, code) in [
        ("authenticated", json!(1), ErrorCode::PermissionDenied),
        ("revoked", json!(true), ErrorCode::SessionRevoked),
        ("expiresAt", json!(1000), ErrorCode::SessionExpired),
        (
            "protocolVersion",
            json!("wrong"),
            ErrorCode::ProtocolMismatch,
        ),
        ("permissions", json!([]), ErrorCode::InvalidInput),
        (
            "permissions",
            json!([PERMISSIONS[0], PERMISSIONS[0]]),
            ErrorCode::InvalidInput,
        ),
        ("permissions", json!(["unknown"]), ErrorCode::InvalidInput),
    ] {
        let mut input = original.clone();
        input[field] = value;
        assert_eq!(
            normalize_session(&input, PROTOCOL_VERSION, 1000)
                .unwrap_err()
                .code,
            code
        );
    }
}
