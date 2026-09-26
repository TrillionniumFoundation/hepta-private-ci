//! Owner-side restoration from the original signed protocol, with real durable I/O.
use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use serde_json::json;

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

fn profile_json() -> Vec<u8> {
    let resources = json!({
        "timeMicros": resource("time", "task", 1),
        "tokenCount": resource("tokens", "task", 2),
        "computeMicros": resource("compute", "environment", 3),
        "memoryBytes": resource("memory", "environment", 4),
        "networkBytes": resource("network", "principal", 5),
        "externalEffectCount": resource("effects", "principal", 6)
    });
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
        "expectedInputSchemaDigest": digest('1'),
        "expectedNormalizationProfileDigest": digest('2'),
        "principalScopeDigest": digest('3'),
        "principalScope": "principal.production",
        "allowedLocales": ["en-US"],
        "maximumSourceAgeMicros": 60000000,
        "maximumFutureSkewMicros": 1000000,
        "deadlineRequired": true,
        "allowedTrustedSourceIdentities": ["issuer.production"],
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
        "resources": resources,
        "risk": risk
    }))
    .expect("profile json")
}

fn fixture() -> (
    tempfile::TempDir,
    AgentdIdentity,
    ObjectiveRuntimeHost,
    RunStartRecordV1,
) {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().canonicalize().unwrap();
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).unwrap();
    let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    let registered = registry
        .register(
            AgentManifest::new(
                agent.clone(),
                WorkspaceBinding::new(&workspace, &fleet).unwrap(),
                ResourceBudget::local_default(),
            )
            .unwrap(),
        )
        .unwrap();
    let identity = AgentdIdentity {
        agent_id: agent,
        spawn_generation: 1,
        fleet_root: fleet.as_path().to_path_buf(),
        workspace,
        resources: registered.manifest.resources,
        home_root: registered.layout.home_root().to_path_buf(),
        run_root: registered.layout.run_root().to_path_buf(),
        control_socket: registered.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: registered.layout.app_server_socket().to_path_buf(),
        layout: registered.layout,
    };
    let profile = decode_admission_profile_json_v1(&profile_json()).unwrap();
    let mut source = json!({
        "requestId":"request.retained", "principalScopeDigest":digest('3'),
        "intentDigest":digest('4'),
        "structuredIntent":{
            "successPredicates":[{"predicateId":"task.success","unit":"ratio","comparator":"gte",
                "boundQ32":2147483648_i64,"evidenceSourceId":"observer.task","terminal":false}],
            "terminalConditions":[{"predicateId":"task.terminal","unit":"boolean","comparator":"eq",
                "boundQ32":4294967296_i64,"evidenceSourceId":"observer.task","terminal":true}],
            "legalActionClasses":["read"],"forbiddenActionClasses":[],"confirmationActionClasses":[],
            "constraints":[{"constraintId":"latency.ceiling","unit":"micros","comparator":"lte",
                "boundQ32":5000,"evidenceSourceId":"observer.clock","terminal":false}],
            "softDimensions":[{"dimensionId":"quality","unit":"ratio","direction":"maximize",
                "minimumWeightQ32":0,"maximumWeightQ32":4294967296_i64}],
            "evidenceRequirements":[{"requirementId":"evidence.quality","evidenceSourceId":"observer.evidence",
                "minimumConfidencePpm":900000,"terminal":true}],
            "resources":{"timeMicros":10000,"tokenCount":1000,"computeMicros":50000,
                "memoryBytes":1048576,"networkBytes":0,"externalEffectCount":0},
            "risk":{"riskClass":"low","abstentionRule":"ask","rollbackClass":"reversible","compensationRequired":false},
            "provenance":{"sourceDigest":digest('5'),"normalizationProfileDigest":digest('2')}
        },
        "sourceTrustClass":"authorized_adapter","locale":"en-US","observedAt":"2026-09-08T10:00:00Z",
        "deadline":"2026-09-08T10:05:00Z","inputSchemaDigest":digest('1')
    });
    let envelope = decode_source_envelope_json_v1(&serde_json::to_vec(&source).unwrap()).unwrap();
    source["intentDigest"] = json!(
        codex_hepta_objective::canonical_objective_intent_digest_v1(&envelope)
            .unwrap()
            .to_string()
    );
    let body = AuthBusObjectiveBody {
        spawn_generation: 1,
        run_id: "run.retained".to_string(),
        objective_revision: 1,
        source_envelope_json: source.to_string(),
        runtime_body_digest: digest('6'),
        preference_state_digest: digest('7'),
        model_tuple_digest: digest('8'),
        prompt_registry_digest: digest('9'),
        artifact_set_digest: digest('a'),
        authority_epoch: 1,
    };
    let signed_body_bytes = objective_payload(&identity, &body, 1).unwrap();
    let authentication = RunStartAuthenticationV1 {
        issuer_id: StableId::new("issuer.production").unwrap(),
        key_epoch: 1,
        message_id: StableId::new("message.retained").unwrap(),
        sequence: 1,
        expires_at_ms: 1_788_861_900_000,
        scope_digest: objective_scope(&identity),
        signed_body_digest: Digest32::of_bytes(&signed_body_bytes),
        signed_body_bytes,
        // This is a projection test. Real signature/issuer checks are exercised
        // separately by recovered_authentication_rejects_revoked_and_stale_owner_trust.
        signature: [7; 64],
    };
    let envelope = decode_source_envelope_json_v1(body.source_envelope_json.as_bytes()).unwrap();
    let profile_digest = profile.digest().unwrap();
    let context = ObjectiveAdmissionContextV1 {
        revision: Revision::new(1).unwrap(),
        now_unix_micros: 1_788_861_601_000_000,
        selected_profile_digest: profile_digest,
        source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
            source_identity: authentication.issuer_id.clone(),
            source_digest: envelope.structured_intent.provenance.source_digest,
        },
    };
    let mut journal = open_run_start_journal(&identity, profile_digest).unwrap();
    let published = compile_and_publish_objective_run_v1(
        &envelope,
        &profile,
        &context,
        ObjectiveRunBindingsV1 {
            authentication,
            run_id: StableId::new(&body.run_id).unwrap(),
            runtime_body_digest: body.runtime_body_digest.parse().unwrap(),
            preference_state_digest: body.preference_state_digest.parse().unwrap(),
            model_tuple_digest: body.model_tuple_digest.parse().unwrap(),
            prompt_registry_digest: body.prompt_registry_digest.parse().unwrap(),
            artifact_set_digest: body.artifact_set_digest.parse().unwrap(),
            authority_epoch: 1,
            generation: 1,
            fence_digest: objective_fence(&identity, 1),
            expected_run_start_head: Digest32::ZERO,
        },
        &mut journal,
    )
    .unwrap();
    let record = journal
        .get(&published.run_start.run_id)
        .unwrap()
        .unwrap()
        .clone();
    let highest_sequences = replay_frontier(&journal).unwrap();
    let host = ObjectiveRuntimeHost {
        profile,
        profile_digest,
        state: Mutex::new(ObjectiveHostState {
            journal,
            highest_sequences,
        }),
    };
    (temp, identity, host, record)
}

#[test]
fn restored_original_input_matches_real_owner_projection_and_exact_retry() {
    let (_temp, identity, host, record) = fixture();
    host.revalidate_projection(&record, &identity).unwrap();
    let profile = host.profile.clone();
    let profile_digest = host.profile_digest;
    let path = identity
        .home_root
        .join(RUN_START_DIRECTORY)
        .join(RUN_START_FILE);
    let before = std::fs::read(&path).unwrap();
    drop(host);
    let mut journal = open_run_start_journal(&identity, profile_digest).unwrap();
    let restored = journal
        .get(&record.snapshot.run_id)
        .unwrap()
        .unwrap()
        .clone();
    assert_eq!(restored, record);
    let replay = journal.append(Digest32::ZERO, restored.clone()).unwrap();
    assert_eq!(
        replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    assert_eq!(std::fs::read(path).unwrap(), before);
    let host = ObjectiveRuntimeHost {
        profile,
        profile_digest,
        state: Mutex::new(ObjectiveHostState {
            highest_sequences: replay_frontier(&journal).unwrap(),
            journal,
        }),
    };
    host.revalidate_projection(&restored, &identity).unwrap();
}

#[test]
fn hash_consistent_projection_substitution_is_not_authentic_source() {
    let (_temp, identity, host, record) = fixture();
    let mut variants = Vec::new();
    let mut changed = record.clone();
    changed.admission.deadline_unix_micros += 1000;
    variants.push(changed);
    let mut changed = record.clone();
    changed.admission.observed_at_unix_micros += 1;
    variants.push(changed);
    let mut changed = record.clone();
    changed.objective_semantic_bytes.push(1);
    changed.snapshot.objective_digest = Digest32::of_bytes(&changed.objective_semantic_bytes);
    variants.push(changed);
    let mut changed = record.clone();
    changed.objective_function_v1_bytes.push(b' ');
    changed.objective_function_v1_digest = Digest32::of_bytes(&changed.objective_function_v1_bytes);
    variants.push(changed);
    let mut changed = record.clone();
    changed.snapshot.hard_constraint_digest = Digest32::of_bytes(b"weakened constraints");
    variants.push(changed);
    for changed in variants {
        assert!(host.revalidate_projection(&changed, &identity).is_err());
    }
    host.revalidate_projection(&record, &identity).unwrap();
}
