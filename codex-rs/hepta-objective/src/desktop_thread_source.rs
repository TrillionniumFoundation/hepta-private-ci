//! Finite compilation for a newly seeded, two-target original Core thread.
//! This module cannot authenticate callbacks, obtain grants or dispatch effects.
//! The original adapter binds the exact target and predecessor in `source_digest`
//! and enforces one durable effect attempt across both targets per Core turn.

use codex_hepta_types::Digest32;
use serde_json::json;

pub const DESKTOP_THREAD_PROFILE_V1: &str = "organ.desktop.thread-tool.v1";

const SCHEMA: &[u8] = b"organ.desktop.thread-tool.v1:notes.replace(text,expected_revision)|calculator.evaluate(left,operator,right,expected_revision);private:original-thread,turn,call,target,operation,subject,policy";
const NORMALIZATION: &[u8] = b"organ.desktop.thread-tool.v1:notes_calculator_v1-new-original-core-thread;exact-original-callback-item-readback;original-authbus-acked-delivery;root-human-cas-binding;preserve-utf8-exactly;canonical-signed-i64-operands;checked-integral-arithmetic;exact-target-and-predecessor;original-operation-semantic-digest;one-effect-attempt-per-original-turn-across-all-targets;shared-durable-original-writer-fence;unknown-observation-only;causal-receipt-separate-current-state;no-network";

/// The finite action chosen by an authenticated original dynamic-tool callback.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DesktopThreadAction {
    NotesReplace,
    CalculatorEvaluate,
}

impl DesktopThreadAction {
    fn names(self) -> (&'static str, &'static str, &'static str) {
        match self {
            Self::NotesReplace => (
                "notes.replace",
                "notes.document.matches",
                "notes.original.readback",
            ),
            Self::CalculatorEvaluate => (
                "calculator.evaluate",
                "calculator.value.matches",
                "calculator.original.readback",
            ),
        }
    }
}

/// Bindings supplied by the original trusted adapter, never by model arguments.
pub struct DesktopThreadSourceContext<'a> {
    pub original_call_id: &'a str,
    pub source_digest: Digest32,
    pub principal_scope_digest: Digest32,
    pub locale: &'a str,
    pub observed_at: &'a str,
    pub deadline: &'a str,
}

/// Compile one exact operation without conferring authority or running a model.
pub fn desktop_thread_source_json_v1(
    action: DesktopThreadAction,
    context: DesktopThreadSourceContext<'_>,
) -> Result<String, String> {
    if context.original_call_id.is_empty()
        || context.original_call_id.len() > 96
        || !context
            .original_call_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"-_".contains(&byte))
        || context.source_digest.is_zero()
        || context.principal_scope_digest.is_zero()
        || !matches!(context.locale, "en-US" | "zh-CN")
        || context.observed_at.len() > 32
        || context.deadline.len() > 32
    {
        return Err("invalid original Desktop source binding".into());
    }
    let (action, predicate, readback) = action.names();
    let mut source = json!({
        "requestId": context.original_call_id,
        "principalScopeDigest": context.principal_scope_digest.to_string(),
        "intentDigest": Digest32::ZERO.to_string(),
        "structuredIntent": {
            "successPredicates": [{"predicateId":predicate,"unit":"boolean","comparator":"eq","boundQ32":4294967296_i64,"evidenceSourceId":readback,"terminal":false}],
            "terminalConditions": [{"predicateId":"desktop.operation.committed","unit":"boolean","comparator":"eq","boundQ32":4294967296_i64,"evidenceSourceId":"desktop.original.owner","terminal":true}],
            "legalActionClasses": [action],
            "forbiddenActionClasses": ["network", "process.execute"],
            "confirmationActionClasses": [],
            "constraints": [{"constraintId":"desktop.exact.destination","unit":"boolean","comparator":"eq","boundQ32":4294967296_i64,"evidenceSourceId":"desktop.original-thread.profile","terminal":false}],
            "softDimensions": [],
            "evidenceRequirements": [{"requirementId":"desktop.exact.receipt","evidenceSourceId":"desktop.original.owner","minimumConfidencePpm":1000000,"terminal":true}],
            "resources": {"timeMicros":5000000,"tokenCount":0,"computeMicros":1000000,"memoryBytes":8192,"networkBytes":0,"externalEffectCount":1},
            "risk": {"riskClass":"low","abstentionRule":"refuse_if_unbound","rollbackClass":"none","compensationRequired":false},
            "provenance": {
                "sourceDigest": context.source_digest.to_string(),
                "normalizationProfileDigest": Digest32::of_bytes(NORMALIZATION).to_string()
            }
        },
        "sourceTrustClass": "authorized_adapter", "locale": context.locale,
        "observedAt": context.observed_at, "deadline": context.deadline,
        "inputSchemaDigest": Digest32::of_bytes(SCHEMA).to_string()
    });
    let decoded = crate::decode_source_envelope_json_v1(
        &serde_json::to_vec(&source).map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())?;
    source["intentDigest"] = crate::canonical_objective_intent_digest_v1(&decoded)
        .map_err(|error| error.to_string())?
        .to_string()
        .into();
    serde_json::to_string(&source).map_err(|error| error.to_string())
}

/// A separate profile for the six-tool catalog of a newly created Core thread.
/// Existing Notes-only threads retain their original profile and catalog bytes.
pub fn desktop_thread_admission_profile_json_v1(
    principal_scope: &str,
    principal_scope_digest: Digest32,
    issuer_id: &str,
) -> Result<String, String> {
    if principal_scope.is_empty()
        || principal_scope.len() > 128
        || issuer_id.is_empty()
        || issuer_id.len() > 128
        || principal_scope_digest.is_zero()
    {
        return Err("invalid original Desktop profile binding".into());
    }
    let resource = |name: &str| json!({"constraintId":format!("desktop.resource.{name}.ceiling"),"axis":format!("desktop.resource.{name}"),"class":"principal","q32PerSourceUnit":1,"evidenceSource":"desktop.original-thread.profile"});
    let profile = json!({
        "profileId": DESKTOP_THREAD_PROFILE_V1, "profileRevision": 1,
        "expectedInputSchemaDigest": Digest32::of_bytes(SCHEMA).to_string(),
        "expectedNormalizationProfileDigest": Digest32::of_bytes(NORMALIZATION).to_string(),
        "principalScopeDigest": principal_scope_digest.to_string(),
        "principalScope": principal_scope,
        "allowedLocales": ["en-US", "zh-CN"],
        "maximumSourceAgeMicros": 60000000, "maximumFutureSkewMicros": 1000000,
        "deadlineRequired": true, "allowedTrustedSourceIdentities": [issuer_id],
        "constraints": [{"sourceConstraintId":"desktop.exact.destination","expectedUnit":"boolean","class":"principal","axis":"desktop.exact.destination"}],
        "predicates": [
            {"sourcePredicateId":"notes.document.matches","expectedUnit":"boolean","axis":"notes.document.matches"},
            {"sourcePredicateId":"calculator.value.matches","expectedUnit":"boolean","axis":"calculator.value.matches"},
            {"sourcePredicateId":"desktop.operation.committed","expectedUnit":"boolean","axis":"desktop.operation.committed"}
        ],
        "actions": [
            {"sourceActionClass":"notes.replace","actionId":"notes.replace"},
            {"sourceActionClass":"calculator.evaluate","actionId":"calculator.evaluate"},
            {"sourceActionClass":"network","actionId":"network"},
            {"sourceActionClass":"process.execute","actionId":"process.execute"}
        ],
        "softDimensions": [],
        "evidenceRequirements": [{"sourceRequirementId":"desktop.exact.receipt","axis":"desktop.receipt.confidence"}],
        "resources": {"timeMicros":resource("time"),"tokenCount":resource("tokens"),"computeMicros":resource("compute"),"memoryBytes":resource("memory"),"networkBytes":resource("network"),"externalEffectCount":resource("effects")},
        "risk": {
            "evidenceSource":"desktop.original-thread.profile","class":"principal",
            "riskConstraintId":"desktop.risk.class","riskAxis":"desktop.risk.class.value","lowValueQ32":0,"mediumValueQ32":1,"highValueQ32":2,"criticalValueQ32":3,
            "rollbackConstraintId":"desktop.risk.rollback","rollbackAxis":"desktop.risk.rollback.value","rollbackNoneValueQ32":0,"rollbackReversibleValueQ32":1,"rollbackCompensatableValueQ32":2,"rollbackIrreversibleValueQ32":3,
            "compensationConstraintId":"desktop.risk.compensation","compensationAxis":"desktop.risk.compensation.value","compensationFalseValueQ32":0,"compensationTrueValueQ32":1,
            "abstentionConstraintId":"desktop.risk.abstention","abstentionAxis":"desktop.risk.abstention.value","abstentionRules":[{"sourceRule":"refuse_if_unbound","valueQ32":1}]
        }
    });
    let bytes = serde_json::to_vec(&profile).map_err(|error| error.to_string())?;
    crate::decode_admission_profile_json_v1(&bytes).map_err(|error| error.to_string())?;
    String::from_utf8(bytes).map_err(|error| error.to_string())
}

#[cfg(test)]
#[path = "desktop_thread_source_tests.rs"]
mod tests;
