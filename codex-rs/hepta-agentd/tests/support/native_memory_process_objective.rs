//! External, controlled issuer for actual daemon ObjectiveStart admission.

use anyhow::Result;
use codex_hepta_agentd::AgentdIdentity;
use codex_hepta_agentd::AuthBusObjectiveBody;
use codex_hepta_agentd::AuthBusObjectiveIngress;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_objective::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::Value;
use serde_json::json;

use super::native_memory_process_fixture::retain;

pub struct ObjectiveFixture {
    pub ingress: AuthBusObjectiveIngress,
    pub digest: Digest32,
}

pub fn hash(value: &str) -> String {
    Digest32::of_bytes(value.as_bytes()).to_string()
}

fn timestamp(seconds: u64) -> Result<String> {
    let result = std::process::Command::new("date")
        .args([
            "--utc",
            "--date",
            &format!("@{seconds}"),
            "+%Y-%m-%dT%H:%M:%SZ",
        ])
        .output()?;
    anyhow::ensure!(result.status.success(), "fixture time formatter failed");
    Ok(String::from_utf8(result.stdout)?.trim().into())
}

pub fn profile() -> Value {
    let resource = |name: &str| {
        json!({"constraintId":format!("budget.{name}"), "axis":format!("resource.{name}"),
        "class":"task", "q32PerSourceUnit":1, "evidenceSource":"fixture.budget"})
    };
    json!({
        "profileId":"process.objective.profile", "profileRevision":1,
        "expectedInputSchemaDigest":hash("schema"), "expectedNormalizationProfileDigest":hash("normalization"),
        "principalScopeDigest":hash("principal"), "principalScope":"process.principal", "allowedLocales":["en-US"],
        "maximumSourceAgeMicros":300_000_000_u64, "maximumFutureSkewMicros":1_000_000,
        "deadlineRequired":true, "allowedTrustedSourceIdentities":["process.objective.issuer"],
        "constraints":[{"sourceConstraintId":"task.no-effects","expectedUnit":"count","class":"task","axis":"task.effects"}],
        "predicates":[{"sourcePredicateId":"task.done","expectedUnit":"boolean","axis":"task.done"},
            {"sourcePredicateId":"task.success","expectedUnit":"boolean","axis":"task.success"}],
        "actions":[{"sourceActionClass":"read","actionId":"action.read"}], "softDimensions":[],
        "evidenceRequirements":[{"sourceRequirementId":"task.evidence","axis":"task.evidence"}],
        "resources":{"timeMicros":resource("time"),"tokenCount":resource("tokens"),"computeMicros":resource("compute"),
            "memoryBytes":resource("memory"),"networkBytes":resource("network"),"externalEffectCount":resource("effects")},
        "risk":{"evidenceSource":"fixture.risk","class":"principal","riskConstraintId":"risk.class","riskAxis":"risk.class.value",
            "lowValueQ32":0,"mediumValueQ32":1,"highValueQ32":2,"criticalValueQ32":3,
            "rollbackConstraintId":"risk.rollback","rollbackAxis":"risk.rollback.value",
            "rollbackNoneValueQ32":0,"rollbackReversibleValueQ32":1,"rollbackCompensatableValueQ32":2,"rollbackIrreversibleValueQ32":3,
            "compensationConstraintId":"risk.compensation","compensationAxis":"risk.compensation.value",
            "compensationFalseValueQ32":0,"compensationTrueValueQ32":1,"abstentionConstraintId":"risk.abstention",
            "abstentionAxis":"risk.abstention.value","abstentionRules":[{"sourceRule":"ask","valueQ32":1}]}
    })
}

pub async fn prepare(
    identity: &AgentdIdentity,
    external: &std::path::Path,
    now_ms: u64,
) -> Result<ObjectiveFixture> {
    let home = &identity.home_root;
    let profile_json = profile();
    retain(&home.join("objective-profile.json"), &profile_json)?;
    let decoded_profile = decode_admission_profile_json_v1(&serde_json::to_vec(&profile_json)?)?;
    let mut source = json!({
        "requestId":"process.objective.request", "principalScopeDigest":hash("principal"), "intentDigest":hash("placeholder"),
        "sourceTrustClass":"authorized_adapter", "locale":"en-US", "observedAt":timestamp(now_ms / 1000)?,
        "deadline":timestamp(now_ms / 1000 + 240)?, "inputSchemaDigest":hash("schema"),
        "structuredIntent":{"successPredicates":[{"predicateId":"task.success","unit":"boolean","comparator":"eq",
            "boundQ32":4294967296_i64,"evidenceSourceId":"fixture.observer","terminal":false}],"terminalConditions":[{"predicateId":"task.done","unit":"boolean",
            "comparator":"eq","boundQ32":4294967296_i64,"evidenceSourceId":"fixture.observer","terminal":true}],
            "legalActionClasses":["read"],"forbiddenActionClasses":[],"confirmationActionClasses":[],
            "constraints":[{"constraintId":"task.no-effects","unit":"count","comparator":"eq","boundQ32":0,
                "evidenceSourceId":"fixture.effects","terminal":false}],"softDimensions":[],
            "evidenceRequirements":[{"requirementId":"task.evidence","evidenceSourceId":"fixture.observer","minimumConfidencePpm":900_000,"terminal":true}],
            "resources":{"timeMicros":240_000_000_u64,"tokenCount":128,
                "computeMicros":240_000_000_u64,"memoryBytes":4294967296_u64,"networkBytes":0,"externalEffectCount":0},
            "risk":{"riskClass":"low","abstentionRule":"ask","rollbackClass":"reversible","compensationRequired":false},
            "provenance":{"sourceDigest":hash("explicit process fixture"),"normalizationProfileDigest":hash("normalization")}}
    });
    let preliminary = decode_source_envelope_json_v1(&serde_json::to_vec(&source)?)?;
    source["intentDigest"] = json!(canonical_objective_intent_digest_v1(&preliminary)?.to_string());
    let decoded = decode_source_envelope_json_v1(&serde_json::to_vec(&source)?)?;
    let compiled = admit_and_compile_objective_v1(
        &decoded,
        &decoded_profile,
        &ObjectiveAdmissionContextV1 {
            revision: Revision::new(/*value*/ 1)?,
            now_unix_micros: now_ms * 1000,
            selected_profile_digest: decoded_profile.digest()?,
            source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
                source_identity: StableId::new("process.objective.issuer")?,
                source_digest: decoded.structured_intent.provenance.source_digest,
            },
        },
    )?
    .compile_result
    .map_err(|error| anyhow::anyhow!("fixture objective conflict: {error:?}"))?;
    let signer = SigningKey::from_bytes(&[115; 32]);
    retain(
        &home.join("objective-trust.json"),
        &json!({"schema_version":1,"agent_id":identity.agent_id.as_str(),
        "issuer_id":"process.objective.issuer","key_epoch":1,"public_key_hex":hex(signer.verifying_key().as_bytes()),
        "revoked":false,"thread_ids":[]}),
    )?;
    let sqlite_home = codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(home)?;
    let evidence = codex_hepta_evidence::HeptaEvidenceStore::open(
        &codex_state::SqliteConfig::from_sqlite_home(sqlite_home),
    )
    .await?;
    let frontier = evidence.authbus_replay_frontier_digest().await?;
    drop(evidence);
    retain(
        &external.join("objective-checkpoint.json"),
        &json!({"schema_version":1,"agent_id":identity.agent_id.as_str(),
        "generation":1,"digest":frontier.to_string()}),
    )?;
    let body = AuthBusObjectiveBody {
        spawn_generation: 1,
        run_id: "process.current.run".into(),
        objective_revision: 1,
        source_envelope_json: serde_json::to_string(&source)?,
        runtime_body_digest: hash("runtime body"),
        preference_state_digest: hash("preference"),
        model_tuple_digest: hash("model tuple"),
        prompt_registry_digest: hash("prompt registry"),
        artifact_set_digest: hash("artifact set"),
        authority_epoch: 7,
    };
    let claims = SignedMessageClaims {
        issuer_id: StableId::new("process.objective.issuer")?,
        key_epoch: Generation::new(/*value*/ 1)?,
        message_id: StableId::new("process.objective.message")?,
        subject_id: StableId::new(identity.agent_id.as_str())?,
        scope_digest: Digest32::of_parts(&[
            b"hepta:agentd:signed-objective:v1\0",
            identity.agent_id.as_str().as_bytes(),
        ]),
        payload_digest: Digest32::of_bytes(&serde_json::to_vec(&body)?),
        sequence: 1,
        expires_at_ms: now_ms + 240_000,
    };
    Ok(ObjectiveFixture {
        digest: compiled.objective.semantic_digest,
        ingress: AuthBusObjectiveIngress {
            issuer_id: claims.issuer_id.to_string(),
            key_epoch: 1,
            message_id: claims.message_id.to_string(),
            sequence: 1,
            expires_at_ms: claims.expires_at_ms,
            signature_hex: hex(&signer.sign(&claims.signing_bytes()).to_bytes()),
            body,
        },
    })
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
