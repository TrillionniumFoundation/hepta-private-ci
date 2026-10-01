use super::*;
use serde_json::json;

fn resource_json(value: &ObjectiveResourceAxisProfileV1) -> serde_json::Value {
    let class = match value.class {
        ConstraintClass::Constitutional => "constitutional",
        ConstraintClass::Task => "task",
        ConstraintClass::Environment => "environment",
        ConstraintClass::Principal => "principal",
    };
    json!({
        "constraintId": value.constraint_id.as_str(), "axis": value.axis.as_str(),
        "class": class, "q32PerSourceUnit": value.q32_per_source_unit.raw(),
        "evidenceSource": value.evidence_source.as_str(),
    })
}

pub(super) fn profile_json(profile: &ObjectiveAdmissionProfileV1) -> Vec<u8> {
    let risk = &profile.risk;
    let mut value = json!({
        "profileId": profile.profile_id.as_str(), "profileRevision": profile.profile_revision.get(),
        "expectedInputSchemaDigest": profile.expected_input_schema_digest.to_string(),
        "expectedNormalizationProfileDigest": profile.expected_normalization_profile_digest.to_string(),
        "principalScopeDigest": profile.principal_scope_digest.to_string(),
        "principalScope": profile.principal_scope.as_str(), "allowedLocales": profile.allowed_locales,
        "maximumSourceAgeMicros": profile.maximum_source_age_micros,
        "maximumFutureSkewMicros": profile.maximum_future_skew_micros,
        "deadlineRequired": profile.deadline_required,
    });
    value["allowedTrustedSourceIdentities"] = json!(["adapter.console"]);
    value["constraints"] = json!([{"sourceConstraintId":"latency.ceiling", "expectedUnit":"micros", "class":"task", "axis":"latency.micros"}]);
    value["predicates"] = json!([
        {"sourcePredicateId":"task.success", "expectedUnit":"ratio", "axis":"task.success.ratio"},
        {"sourcePredicateId":"task.terminal", "expectedUnit":"boolean", "axis":"task.terminal"}
    ]);
    value["actions"] = json!([
        {"sourceActionClass":"read", "actionId":"action.read"},
        {"sourceActionClass":"network", "actionId":"action.network"}
    ]);
    value["softDimensions"] = json!([{"sourceDimensionId":"quality", "expectedUnit":"ratio", "expectedDirection":"maximize", "dimension":"quality.ratio", "baselineWeightQ32":2147483648_i64}]);
    value["evidenceRequirements"] =
        json!([{"sourceRequirementId":"evidence.quality", "axis":"evidence.confidence"}]);
    value["resources"] = json!({
        "timeMicros": resource_json(&profile.resources.time_micros),
        "tokenCount": resource_json(&profile.resources.token_count),
        "computeMicros": resource_json(&profile.resources.compute_micros),
        "memoryBytes": resource_json(&profile.resources.memory_bytes),
        "networkBytes": resource_json(&profile.resources.network_bytes),
        "externalEffectCount": resource_json(&profile.resources.external_effect_count)
    });
    let mut risk_json = json!({
        "evidenceSource":risk.evidence_source.as_str(), "class":"principal",
        "riskConstraintId":risk.risk_constraint_id.as_str(), "riskAxis":risk.risk_axis.as_str(),
        "lowValueQ32":risk.low_value.raw(), "mediumValueQ32":risk.medium_value.raw(),
        "highValueQ32":risk.high_value.raw(), "criticalValueQ32":risk.critical_value.raw(),
    });
    for fields in [
        json!({
            "rollbackConstraintId":risk.rollback_constraint_id.as_str(), "rollbackAxis":risk.rollback_axis.as_str(),
            "rollbackNoneValueQ32":risk.rollback_none_value.raw(), "rollbackReversibleValueQ32":risk.rollback_reversible_value.raw(),
            "rollbackCompensatableValueQ32":risk.rollback_compensatable_value.raw(), "rollbackIrreversibleValueQ32":risk.rollback_irreversible_value.raw(),
        }),
        json!({
            "compensationConstraintId":risk.compensation_constraint_id.as_str(), "compensationAxis":risk.compensation_axis.as_str(),
            "compensationFalseValueQ32":risk.compensation_false_value.raw(), "compensationTrueValueQ32":risk.compensation_true_value.raw(),
            "abstentionConstraintId":risk.abstention_constraint_id.as_str(), "abstentionAxis":risk.abstention_axis.as_str(),
            "abstentionRules":[{"sourceRule":"ask", "valueQ32":1}]
        }),
    ] {
        risk_json
            .as_object_mut()
            .expect("risk object")
            .extend(fields.as_object().expect("risk fields").clone());
    }
    value["risk"] = risk_json;
    serde_json::to_vec(&value).expect("explicit profile JSON")
}

pub(super) fn source_json(source: &ObjectiveSourceEnvelopeV1) -> String {
    let mut intent = json!({
        "legalActionClasses":["read"], "forbiddenActionClasses":["network"], "confirmationActionClasses":[],
    });
    intent["successPredicates"] = json!([{"predicateId":"task.success", "unit":"ratio", "comparator":"gte", "boundQ32":2147483648_i64, "evidenceSourceId":"observer.task", "terminal":false}]);
    intent["terminalConditions"] = json!([{"predicateId":"task.terminal", "unit":"boolean", "comparator":"eq", "boundQ32":4294967296_i64, "evidenceSourceId":"observer.task", "terminal":true}]);
    intent["constraints"] = json!([{"constraintId":"latency.ceiling", "unit":"micros", "comparator":"lte", "boundQ32":5000, "evidenceSourceId":"observer.clock", "terminal":false}]);
    intent["softDimensions"] = json!([{"dimensionId":"quality", "unit":"ratio", "direction":"maximize", "minimumWeightQ32":0, "maximumWeightQ32":4294967296_i64}]);
    intent["evidenceRequirements"] = json!([{"requirementId":"evidence.quality", "evidenceSourceId":"observer.evidence", "minimumConfidencePpm":900000, "terminal":true}]);
    intent["resources"] = json!({"timeMicros":10000, "tokenCount":1000, "computeMicros":50000, "memoryBytes":1048576, "networkBytes":0, "externalEffectCount":0});
    intent["risk"] = json!({"riskClass":"low", "abstentionRule":"ask", "rollbackClass":"reversible", "compensationRequired":false});
    intent["provenance"] = json!({
        "sourceDigest":source.structured_intent.provenance.source_digest.to_string(),
        "normalizationProfileDigest":source.structured_intent.provenance.normalization_profile_digest.to_string()
    });
    let source_json = serde_json::to_string(&json!({
        "requestId":source.request_id, "principalScopeDigest":source.principal_scope_digest.to_string(),
        "intentDigest":source.intent_digest.to_string(), "structuredIntent":intent,
        "sourceTrustClass":"authorized_adapter", "locale":source.locale,
        "observedAt":source.observed_at, "deadline":source.deadline,
        "inputSchemaDigest":source.input_schema_digest.to_string()
    })).expect("explicit signed source JSON");
    assert_eq!(
        codex_hepta_objective::decode_source_envelope_json_v1(source_json.as_bytes())
            .expect("source roundtrip"),
        *source
    );
    source_json
}
