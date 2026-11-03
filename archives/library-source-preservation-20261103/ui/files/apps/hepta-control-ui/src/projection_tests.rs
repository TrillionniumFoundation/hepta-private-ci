use super::*;
use crate::contract::{UI_CONTROL_PROTOCOL_VERSION, normalize_session};
use pretty_assertions::assert_eq;

fn runtime() -> Value {
    json!({"generation":2,"revision":3,"modules":[
        {"id":"z.module","status":"ready","revision":1,"semanticDigest":"a".repeat(64)},
        {"id":"a.module","status":"degraded","revision":2,"semanticDigest":"b".repeat(64)}]})
}

fn session() -> Session {
    normalize_session(
        &json!({"authenticated":true,"protocolVersion":UI_CONTROL_PROTOCOL_VERSION,
        "sessionId":"session-1","identityId":"operator-1","connectionGeneration":5,
        "permissionRevision":1,"expiresAt":10000,"revoked":false,
        "permissions":["hepta://ui.control/runtime.read"]}),
        UI_CONTROL_PROTOCOL_VERSION,
        /*now*/ 1,
    )
    .unwrap()
}

fn snapshot() -> Value {
    let mut value = runtime();
    value["sessionId"] = json!("session-1");
    value["connectionGeneration"] = json!(5);
    value
}

#[test]
fn projection_and_snapshot_digests_match_javascript_oracle() {
    let projected = project_runtime(&runtime()).unwrap();
    let mut expected = runtime();
    expected["modules"].as_array_mut().unwrap().reverse();
    assert_eq!(serde_json::to_value(&projected).unwrap(), expected);
    assert_eq!(
        digest_runtime_projection(&projected),
        Ok("8a849b772411bf14fd4156d18f1805f5c3a334dcf0b722b47343d501c7f4bb2b".to_owned())
    );
    let normalized = normalize_snapshot(&snapshot(), &session()).unwrap();
    expected["sessionId"] = json!("session-1");
    expected["connectionGeneration"] = json!(5);
    expected["observedAt"] = Value::Null;
    expected["semanticDigest"] =
        json!("134c020d0e703ab97b4a55fd5d14ca48b064be65e7b3dd0578d1287091f7c6df");
    assert_eq!(serde_json::to_value(normalized).unwrap(), expected);
}

#[test]
fn rejects_duplicate_ids_unknown_fields_unknown_statuses_and_bounds() {
    let mut invalid_cases = Vec::new();
    let mut duplicate = runtime();
    duplicate["modules"][1] = duplicate["modules"][0].clone();
    invalid_cases.push(duplicate);
    let mut extra = runtime();
    extra["criticalAuthority"] = json!(true);
    invalid_cases.push(extra);
    let mut extra_module = runtime();
    extra_module["modules"][0]["canExecute"] = json!(true);
    invalid_cases.push(extra_module);
    let mut unknown = runtime();
    unknown["modules"][0]["status"] = json!("authorized");
    invalid_cases.push(unknown);
    let mut zero = runtime();
    zero["generation"] = json!(0);
    invalid_cases.push(zero);
    let mut unsafe_integer = runtime();
    unsafe_integer["revision"] = json!(9_007_199_254_740_992_u64);
    invalid_cases.push(unsafe_integer);
    let mut oversized = runtime();
    oversized["modules"] = json!(vec![runtime()["modules"][0].clone(); 1001]);
    invalid_cases.push(oversized);
    for value in invalid_cases {
        assert_eq!(
            project_runtime(&value),
            Err(ControlError::new(ErrorCode::InvalidInput))
        );
    }
}

#[test]
fn maximum_module_count_remains_supported_and_order_independent() {
    let mut value = runtime();
    value["modules"] = json!(
        (0..1000)
            .rev()
            .map(|index| json!({"id":format!("module-{index:04}"),
        "status":"ready","revision":1,"semanticDigest":"a".repeat(64)}))
            .collect::<Vec<_>>()
    );
    let projected = project_runtime(&value).unwrap();
    assert_eq!(
        project_runtime(&serde_json::to_value(&projected).unwrap()),
        Ok(projected)
    );
}

#[test]
fn binds_session_and_connection_and_checks_declared_digest() {
    let mut wrong_session = snapshot();
    wrong_session["sessionId"] = json!("other");
    assert_eq!(
        normalize_snapshot(&wrong_session, &session()),
        Err(ControlError::new(ErrorCode::InvalidInput))
    );
    let mut wrong_generation = snapshot();
    wrong_generation["connectionGeneration"] = json!(4);
    assert_eq!(
        normalize_snapshot(&wrong_generation, &session()),
        Err(ControlError::new(ErrorCode::StaleGeneration))
    );
    let mut wrong_digest = snapshot();
    wrong_digest["semanticDigest"] = json!("a".repeat(64));
    assert_eq!(
        normalize_snapshot(&wrong_digest, &session()),
        Err(ControlError::new(ErrorCode::SnapshotDrift))
    );
    let mut null_digest = snapshot();
    null_digest["semanticDigest"] = Value::Null;
    assert_eq!(
        normalize_snapshot(&null_digest, &session()),
        Err(ControlError::new(ErrorCode::InvalidInput))
    );
}

#[test]
fn transitions_preserve_prior_same_revision_and_reject_regression_and_drift() {
    let previous = normalize_snapshot(&snapshot(), &session()).unwrap();
    let mut timestamp_only = previous.clone();
    timestamp_only.observed_at = Some("later".to_owned());
    assert_eq!(
        validate_snapshot_transition(Some(&previous), timestamp_only),
        Ok(previous.clone())
    );
    for (next, error) in [
        (
            Snapshot {
                session_id: "other".to_owned(),
                ..previous.clone()
            },
            ErrorCode::StaleGeneration,
        ),
        (
            Snapshot {
                connection_generation: 4,
                ..previous.clone()
            },
            ErrorCode::StaleGeneration,
        ),
        (
            Snapshot {
                generation: 1,
                ..previous.clone()
            },
            ErrorCode::StaleGeneration,
        ),
        (
            Snapshot {
                revision: 2,
                ..previous.clone()
            },
            ErrorCode::StaleRevision,
        ),
        (
            Snapshot {
                semantic_digest: "b".repeat(64),
                ..previous.clone()
            },
            ErrorCode::SnapshotDrift,
        ),
    ] {
        assert_eq!(
            validate_snapshot_transition(Some(&previous), next),
            Err(ControlError::new(error))
        );
    }
    for next in [
        Snapshot {
            connection_generation: 6,
            generation: 1,
            revision: 1,
            ..previous.clone()
        },
        Snapshot {
            generation: 3,
            revision: 1,
            ..previous.clone()
        },
        Snapshot {
            revision: 4,
            ..previous.clone()
        },
    ] {
        assert_eq!(
            validate_snapshot_transition(Some(&previous), next.clone()),
            Ok(next)
        );
    }
}

#[test]
fn optional_snapshot_envelope_fields_do_not_change_semantics() {
    let normal = normalize_snapshot(&snapshot(), &session()).unwrap();
    let mut extended = snapshot();
    extended["diagnostic"] = json!("healthy");
    extended["observedAt"] = json!(123);
    assert_eq!(normalize_snapshot(&extended, &session()), Ok(normal));
    let mut integral_float = runtime();
    integral_float["generation"] = json!(2.0);
    assert_eq!(
        project_runtime(&integral_float),
        project_runtime(&runtime())
    );
}
