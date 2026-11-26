use super::*;
use codex_hepta_agent_components::objective::canonical_objective_intent_digest_v1;
use pretty_assertions::assert_eq;

fn source() -> Value {
    serde_json::json!({
        "requestId": "cpu-readonly.first",
        "principalScopeDigest": "1".repeat(64), "intentDigest": "0".repeat(64),
        "structuredIntent": {
            "successPredicates": [{"predicateId":"evidence.answer", "unit":"ratio", "comparator":"gte", "boundQ32":4294967296_i64, "evidenceSourceId":"published.evidence", "terminal":false}],
            "terminalConditions": [{"predicateId":"execution.completed", "unit":"count", "comparator":"eq", "boundQ32":1, "evidenceSourceId":"runtime.receipt", "terminal":true}],
            "legalActionClasses": ["read", "abstain"], "forbiddenActionClasses":["write", "network"], "confirmationActionClasses":[],
            "constraints":[{"constraintId":"latency.ceiling", "unit":"micros", "comparator":"lte", "boundQ32":100000, "evidenceSourceId":"runtime.clock", "terminal":false}], "softDimensions":[{"dimensionId":"evidence.quality", "unit":"ratio", "direction":"maximize", "minimumWeightQ32":0, "maximumWeightQ32":4294967296_i64}],
            "evidenceRequirements":[{"requirementId":"source.citation", "evidenceSourceId":"published.evidence", "minimumConfidencePpm":1000000,"terminal":true}],
            "resources":{"timeMicros":100000, "tokenCount":256, "computeMicros":100000, "memoryBytes":1048576, "networkBytes":0, "externalEffectCount":0},
            "risk":{"riskClass":"low", "abstentionRule":"abstain", "rollbackClass":"none", "compensationRequired":false},
            "provenance":{"sourceDigest":"2".repeat(64), "normalizationProfileDigest":"3".repeat(64)}
        },
        "sourceTrustClass":"trusted_system", "locale":"zh-CN",
        "observedAt":"2026-10-02T10:00:00Z", "deadline":"2026-10-02T10:05:00Z", "inputSchemaDigest":"4".repeat(64)
    })
}

#[test]
fn complete_source_roundtrips_and_distinct_semantic_goals_use_real_native_digest() {
    let first = source();
    let prepared = prepare_payload(&serde_json::to_vec(&first).unwrap()).unwrap();
    let native = decode_source_envelope_json_v1(&prepared).unwrap();
    assert_eq!(
        native.intent_digest,
        canonical_objective_intent_digest_v1(&native).unwrap()
    );
    let mut expected =
        decode_source_envelope_json_v1(&serde_json::to_vec(&first).unwrap()).unwrap();
    expected.intent_digest = native.intent_digest;
    assert_eq!(native, expected);
    assert_eq!(prepare_payload(&prepared).unwrap(), prepared);
    let mut second = first;
    second["requestId"] = "cpu-readonly.second".into();
    second["structuredIntent"]["successPredicates"][0]["predicateId"] =
        "evidence.contradiction".into();
    let second = prepare_payload(&serde_json::to_vec(&second).unwrap()).unwrap();
    assert_ne!(
        decode_source_envelope_json_v1(&second)
            .unwrap()
            .intent_digest,
        native.intent_digest
    );
}

#[test]
fn historical_wrong_intent_and_incomplete_or_duplicate_fields_reject() {
    assert!(decode_source_envelope_json_v1(&serde_json::to_vec(&source()).unwrap()).is_ok());
    let mut wrong = source();
    wrong["intentDigest"] = "9".repeat(64).into();
    assert!(prepare_payload(&serde_json::to_vec(&wrong).unwrap()).is_err());
    let mut incomplete = source();
    incomplete["structuredIntent"]
        .as_object_mut()
        .unwrap()
        .remove("resources");
    assert!(prepare_payload(&serde_json::to_vec(&incomplete).unwrap()).is_err());
    let raw = serde_json::to_string(&source()).unwrap();
    assert!(
        prepare_payload(
            raw.replacen('{', "{\"requestId\":\"duplicate\",", 1)
                .as_bytes()
        )
        .is_err()
    );
}
