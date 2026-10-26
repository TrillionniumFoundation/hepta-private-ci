//! Shared finite Notes source/profile encoder. This is authority-free data
//! compilation, extracted from Desktop's original literal Notes adapter so the
//! same Agentd writer can compile without depending on the Desktop renderer.
//! Callers must first derive `source_digest` through the original Notes operation
//! validator. Neither this module nor its result observes, signs or dispatches.

use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

use crate::canonical_objective_intent_digest_v1;
use crate::decode_admission_profile_json_v1;
use crate::decode_source_envelope_json_v1;

const SCHEMA: &[u8] = b"organ.notes.literal.v1:client_intent_id,text;private:target,expected_revision,operation_id,subject,policy_generation";
const NORMALIZATION: &[u8] = b"organ.notes.literal.v1:preserve-utf8-exactly;json-encode-notes-replace-v1;original-operation-semantic-digest;one-note-no-model-no-network";

/// Values supplied by the trusted literal adapter. The document and exact
/// predecessor are bound by the original operation's semantic digest.
pub struct LiteralNotesSourceContext<'a> {
    pub client_intent_id: &'a str,
    pub source_digest: Digest32,
    pub principal_scope_digest: Digest32,
    pub locale: &'a str,
    pub observed_at: &'a str,
    pub deadline: &'a str,
}

pub fn literal_notes_source_json_v1(
    context: LiteralNotesSourceContext<'_>,
) -> Result<String, String> {
    if context.client_intent_id.is_empty()
        || context.client_intent_id.len() > 96
        || !context
            .client_intent_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"-_".contains(&byte))
        || context.source_digest.is_zero()
        || context.principal_scope_digest.is_zero()
        || !matches!(context.locale, "en-US" | "zh-CN")
        || context.observed_at.len() > 32
        || context.deadline.len() > 32
    {
        return Err("invalid literal Notes source binding".into());
    }
    let mut source = json!({
        "requestId":context.client_intent_id,"principalScopeDigest":context.principal_scope_digest.to_string(),
        "intentDigest":Digest32::ZERO.to_string(),
        "structuredIntent":{
            "successPredicates":[{"predicateId":"notes.document.matches","unit":"boolean","comparator":"eq","boundQ32":4294967296_i64,"evidenceSourceId":"notes.original.readback","terminal":false}],
            "terminalConditions":[{"predicateId":"notes.operation.committed","unit":"boolean","comparator":"eq","boundQ32":4294967296_i64,"evidenceSourceId":"notes.original.owner","terminal":true}],
            "legalActionClasses":["notes.replace"],"forbiddenActionClasses":["network","process.execute"],"confirmationActionClasses":[],
            "constraints":[{"constraintId":"notes.exact.destination","unit":"boolean","comparator":"eq","boundQ32":4294967296_i64,"evidenceSourceId":"notes.literal.profile","terminal":false}],"softDimensions":[],
            "evidenceRequirements":[{"requirementId":"notes.exact.receipt","evidenceSourceId":"notes.original.owner","minimumConfidencePpm":1000000,"terminal":true}],
            "resources":{"timeMicros":5000000,"tokenCount":0,"computeMicros":1000000,"memoryBytes":8192,"networkBytes":0,"externalEffectCount":1},
            "risk":{"riskClass":"low","abstentionRule":"refuse_if_unbound","rollbackClass":"none","compensationRequired":false},
            "provenance":{"sourceDigest":context.source_digest.to_string(),"normalizationProfileDigest":Digest32::of_bytes(NORMALIZATION).to_string()}
        },
        "sourceTrustClass":"authorized_adapter","locale":context.locale,"observedAt":context.observed_at,
        "deadline":context.deadline,"inputSchemaDigest":Digest32::of_bytes(SCHEMA).to_string(),
    });
    let decoded = decode_source_envelope_json_v1(
        &serde_json::to_vec(&source).map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())?;
    source["intentDigest"] = json!(
        canonical_objective_intent_digest_v1(&decoded)
            .map_err(|error| error.to_string())?
            .to_string()
    );
    serde_json::to_string(&source).map_err(|error| error.to_string())
}

/// A frozen profile for one persistent principal and registered signing adapter.
/// Its scope is independent of a Notes process incarnation; each operation
/// separately binds the exact current target and predecessor in its payload.
pub fn literal_notes_admission_profile_json_v1(
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
        return Err("invalid literal Notes profile binding".into());
    }
    let resource = |name: &str| json!({"constraintId":format!("notes.resource.{name}.ceiling"),"axis":format!("notes.resource.{name}"),"class":"principal","q32PerSourceUnit":1,"evidenceSource":"notes.literal.profile"});
    let profile: Value = json!({
        "profileId":"organ.notes.literal.v1","profileRevision":1,
        "expectedInputSchemaDigest":Digest32::of_bytes(SCHEMA).to_string(),
        "expectedNormalizationProfileDigest":Digest32::of_bytes(NORMALIZATION).to_string(),
        "principalScopeDigest":principal_scope_digest.to_string(),"principalScope":principal_scope,
        "allowedLocales":["en-US","zh-CN"],"maximumSourceAgeMicros":60000000,"maximumFutureSkewMicros":1000000,
        "deadlineRequired":true,"allowedTrustedSourceIdentities":[issuer_id],
        "constraints":[{"sourceConstraintId":"notes.exact.destination","expectedUnit":"boolean","class":"principal","axis":"notes.exact.destination"}],
        "predicates":[
            {"sourcePredicateId":"notes.document.matches","expectedUnit":"boolean","axis":"notes.document.matches"},
            {"sourcePredicateId":"notes.operation.committed","expectedUnit":"boolean","axis":"notes.operation.committed"}
        ],
        "actions":[
            {"sourceActionClass":"notes.replace","actionId":"notes.replace"},
            {"sourceActionClass":"network","actionId":"network"},
            {"sourceActionClass":"process.execute","actionId":"process.execute"}
        ],
        "softDimensions":[],"evidenceRequirements":[{"sourceRequirementId":"notes.exact.receipt","axis":"notes.receipt.confidence"}],
        "resources":{"timeMicros":resource("time"),"tokenCount":resource("tokens"),"computeMicros":resource("compute"),"memoryBytes":resource("memory"),"networkBytes":resource("network"),"externalEffectCount":resource("effects")},
        "risk":{"evidenceSource":"notes.literal.profile","class":"principal",
            "riskConstraintId":"notes.risk.class","riskAxis":"notes.risk.class.value","lowValueQ32":0,"mediumValueQ32":1,"highValueQ32":2,"criticalValueQ32":3,
            "rollbackConstraintId":"notes.risk.rollback","rollbackAxis":"notes.risk.rollback.value","rollbackNoneValueQ32":0,"rollbackReversibleValueQ32":1,"rollbackCompensatableValueQ32":2,"rollbackIrreversibleValueQ32":3,
            "compensationConstraintId":"notes.risk.compensation","compensationAxis":"notes.risk.compensation.value","compensationFalseValueQ32":0,"compensationTrueValueQ32":1,
            "abstentionConstraintId":"notes.risk.abstention","abstentionAxis":"notes.risk.abstention.value","abstentionRules":[{"sourceRule":"refuse_if_unbound","valueQ32":1}]
        }
    });
    let bytes = serde_json::to_vec(&profile).map_err(|error| error.to_string())?;
    decode_admission_profile_json_v1(&bytes).map_err(|error| error.to_string())?;
    String::from_utf8(bytes).map_err(|error| error.to_string())
}

#[cfg(test)]
#[path = "notes_literal_source_tests.rs"]
mod tests;
