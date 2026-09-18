use serde_json::json;

use super::*;

fn digest(byte: char) -> String {
    byte.to_string().repeat(64)
}

fn resource(name: &str, class: &str, suffix: usize) -> serde_json::Value {
    json!({
        "constraintId": format!("resource.{name}.{suffix}"),
        "axis": format!("resource.{name}"),
        "class": class,
        "q32PerSourceUnit": 1,
        "evidenceSource": "profile.resource"
    })
}

fn resources() -> serde_json::Value {
    json!({
        "timeMicros": resource("time", "task", 1),
        "tokenCount": resource("tokens", "task", 2),
        "computeMicros": resource("compute", "environment", 3),
        "memoryBytes": resource("memory", "environment", 4),
        "networkBytes": resource("network", "principal", 5),
        "externalEffectCount": resource("effects", "principal", 6)
    })
}

fn risk() -> serde_json::Value {
    json!({
        "evidenceSource": "profile.risk",
        "class": "principal",
        "riskConstraintId": "risk.class",
        "riskAxis": "risk.value",
        "lowValueQ32": 0,
        "mediumValueQ32": 1,
        "highValueQ32": 2,
        "criticalValueQ32": 3,
        "rollbackConstraintId": "risk.rollback",
        "rollbackAxis": "risk.rollback.value",
        "rollbackNoneValueQ32": 0,
        "rollbackReversibleValueQ32": 1,
        "rollbackCompensatableValueQ32": 2,
        "rollbackIrreversibleValueQ32": 3,
        "compensationConstraintId": "risk.compensation",
        "compensationAxis": "risk.compensation.value",
        "compensationFalseValueQ32": 0,
        "compensationTrueValueQ32": 1,
        "abstentionConstraintId": "risk.abstention",
        "abstentionAxis": "risk.abstention.value",
        "abstentionRules": [{ "sourceRule": "ask", "valueQ32": 1 }]
    })
}

fn profile_json() -> Vec<u8> {
    let mut profile = serde_json::Map::new();
    profile.insert("profileId".into(), json!("objective.profile.production.v1"));
    profile.insert("profileRevision".into(), json!(1));
    profile.insert("expectedInputSchemaDigest".into(), json!(digest('1')));
    profile.insert(
        "expectedNormalizationProfileDigest".into(),
        json!(digest('2')),
    );
    profile.insert("principalScopeDigest".into(), json!(digest('3')));
    profile.insert("principalScope".into(), json!("principal.production"));
    profile.insert("allowedLocales".into(), json!(["en-US"]));
    profile.insert("maximumSourceAgeMicros".into(), json!(60_000_000));
    profile.insert("maximumFutureSkewMicros".into(), json!(1_000_000));
    profile.insert("deadlineRequired".into(), json!(true));
    profile.insert(
        "allowedTrustedSourceIdentities".into(),
        json!(["issuer.production"]),
    );
    profile.insert(
        "constraints".into(),
        json!([{
            "sourceConstraintId": "latency.ceiling",
            "expectedUnit": "micros",
            "class": "task",
            "axis": "latency.micros"
        }]),
    );
    profile.insert(
        "predicates".into(),
        json!([{
            "sourcePredicateId": "task.success",
            "expectedUnit": "ratio",
            "axis": "task.success.ratio"
        }]),
    );
    profile.insert(
        "actions".into(),
        json!([{
            "sourceActionClass": "read",
            "actionId": "action.read"
        }]),
    );
    profile.insert(
        "softDimensions".into(),
        json!([{
            "sourceDimensionId": "quality",
            "expectedUnit": "ratio",
            "expectedDirection": "maximize",
            "dimension": "quality.ratio",
            "baselineWeightQ32": 2147483648_i64
        }]),
    );
    profile.insert(
        "evidenceRequirements".into(),
        json!([{
            "sourceRequirementId": "evidence.quality",
            "axis": "evidence.confidence"
        }]),
    );
    profile.insert("resources".into(), resources());
    profile.insert("risk".into(), risk());

    serde_json::to_vec(&serde_json::Value::Object(profile)).expect("profile json")
}

#[test]
fn strict_profile_json_decodes_and_validates_digest_semantics() {
    let profile = decode_admission_profile_json_v1(&profile_json()).expect("profile");
    assert_eq!(profile.profile_id.as_str(), "objective.profile.production.v1");
    assert_eq!(profile.allowed_trusted_source_identities[0].as_str(), "issuer.production");
    assert!(!profile.digest().expect("digest").is_zero());
}

#[test]
fn profile_json_rejects_unknown_fields_and_oversize_input() {
    let mut value: serde_json::Value = serde_json::from_slice(&profile_json()).expect("json");
    value.as_object_mut().expect("object").insert("unknown".into(), json!(true));
    let bytes = serde_json::to_vec(&value).expect("bytes");
    assert!(matches!(
        decode_admission_profile_json_v1(&bytes),
        Err(ObjectiveAdmissionProfileJsonError::InvalidJson { .. })
    ));
    let oversized = vec![b' '; MAX_OBJECTIVE_ADMISSION_PROFILE_JSON_BYTES + 1];
    assert!(matches!(
        decode_admission_profile_json_v1(&oversized),
        Err(ObjectiveAdmissionProfileJsonError::InputTooLarge { .. })
    ));
}

#[test]
fn profile_json_rejects_unregistered_risk_ordering() {
    let mut value: serde_json::Value = serde_json::from_slice(&profile_json()).expect("json");
    value["risk"]["mediumValueQ32"] = json!(-1);
    let bytes = serde_json::to_vec(&value).expect("bytes");
    assert!(matches!(
        decode_admission_profile_json_v1(&bytes),
        Err(ObjectiveAdmissionProfileJsonError::Admission(
            ObjectiveAdmissionError::InvalidProfile("risk ordering")
        ))
    ));
}
