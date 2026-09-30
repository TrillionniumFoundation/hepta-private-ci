//! Explicit test-producer profile in the objective owner's JSON wire format.
use serde_json::json;

fn resource(name: &str, class: &str, suffix: usize) -> serde_json::Value {
    json!({
        "constraintId": format!("resource.{name}.{suffix}"),
        "axis": format!("resource.{name}"),
        "class": class,
        "q32PerSourceUnit": 1,
        "evidenceSource": "profile.resource"
    })
}

pub(super) fn profile_json() -> serde_json::Result<Vec<u8>> {
    let risk = json!({
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
    });
    serde_json::to_vec(&json!({
        "profileId": "objective.profile.production.v1",
        "profileRevision": 1,
        "expectedInputSchemaDigest": "1".repeat(64),
        "expectedNormalizationProfileDigest": "2".repeat(64),
        "principalScopeDigest": "3".repeat(64),
        "principalScope": "principal.production",
        "allowedLocales": ["en-US"],
        "maximumSourceAgeMicros": 60000000,
        "maximumFutureSkewMicros": 1000000,
        "deadlineRequired": true,
        "allowedTrustedSourceIdentities": [super::super::ISSUER_ID],
        "constraints": [{
            "sourceConstraintId": "latency.ceiling",
            "expectedUnit": "micros",
            "class": "task",
            "axis": "latency.micros"
        }],
        "predicates": [{
            "sourcePredicateId": "task.success",
            "expectedUnit": "ratio",
            "axis": "task.success.ratio"
        }, {
            "sourcePredicateId": "task.terminal",
            "expectedUnit": "boolean",
            "axis": "task.terminal"
        }],
        "actions": [{
            "sourceActionClass": "read",
            "actionId": "action.read"
        }],
        "softDimensions": [{
            "sourceDimensionId": "quality",
            "expectedUnit": "ratio",
            "expectedDirection": "maximize",
            "dimension": "quality.ratio",
            "baselineWeightQ32": 2147483648_i64
        }],
        "evidenceRequirements": [{
            "sourceRequirementId": "evidence.quality",
            "axis": "evidence.confidence"
        }],
        "resources": {
            "timeMicros": resource("time", "task", 1),
            "tokenCount": resource("tokens", "task", 2),
            "computeMicros": resource("compute", "environment", 3),
            "memoryBytes": resource("memory", "environment", 4),
            "networkBytes": resource("network", "principal", 5),
            "externalEffectCount": resource("effects", "principal", 6)
        },
        "risk": risk
    }))
}
