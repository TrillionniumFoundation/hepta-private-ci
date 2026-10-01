//! Exercise the actual signed ObjectiveStart publication/retry branch using the
//! existing live Production owner fixture, without another writer or runner.

use super::*;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use crate::objective_runtime::ObjectiveRuntimeHost;

fn profile_json() -> serde_json::Value {
    let resource = |name: &str, class: &str| {
        serde_json::json!({
            "constraintId": format!("resource.{name}.ceiling"),
            "axis": format!("resource.{name}"),
            "class": class,
            "q32PerSourceUnit": 1,
            "evidenceSource": "objective.resource.profile"
        })
    };
    serde_json::json!({
        "profileId": "objective.profile.agentd.v1",
        "profileRevision": 1,
        "expectedInputSchemaDigest": digest("schema-v1").to_string(),
        "expectedNormalizationProfileDigest": digest("normalization-v1").to_string(),
        "principalScopeDigest": digest("principal-scope").to_string(),
        "principalScope": "principal.alpha",
        "allowedLocales": ["en-US"],
        "maximumSourceAgeMicros": u64::MAX,
        "maximumFutureSkewMicros": 1_000_000,
        "deadlineRequired": true,
        "allowedTrustedSourceIdentities": ["issuer.objective"],
        "constraints": [{ "sourceConstraintId": "latency.ceiling", "expectedUnit": "micros", "class": "task", "axis": "latency.micros" }],
        "predicates": [
            { "sourcePredicateId": "task.success", "expectedUnit": "ratio", "axis": "task.success.ratio" },
            { "sourcePredicateId": "task.terminal", "expectedUnit": "boolean", "axis": "task.terminal" }
        ],
        "actions": [
            { "sourceActionClass": "read", "actionId": "action.read" },
            { "sourceActionClass": "network", "actionId": "action.network" }
        ],
        "softDimensions": [{ "sourceDimensionId": "quality", "expectedUnit": "ratio", "expectedDirection": "maximize", "dimension": "quality.ratio", "baselineWeightQ32": 1_i64 << 31 }],
        "evidenceRequirements": [{ "sourceRequirementId": "evidence.quality", "axis": "evidence.confidence" }],
        "resources": {
            "timeMicros": resource("time", "task"),
            "tokenCount": resource("tokens", "task"),
            "computeMicros": resource("compute", "environment"),
            "memoryBytes": resource("memory", "environment"),
            "networkBytes": resource("network", "principal"),
            "externalEffectCount": resource("effects", "principal")
        },
        "risk": {
            "evidenceSource": "objective.risk.profile",
            "class": "principal",
            "riskConstraintId": "risk.class",
            "riskAxis": "risk.class.value",
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
        }
    })
}

fn source_json(source: &ObjectiveSourceEnvelopeV1) -> String {
    serde_json::to_string(&serde_json::json!({
        "requestId": source.request_id,
        "principalScopeDigest": source.principal_scope_digest.to_string(),
        "intentDigest": source.intent_digest.to_string(),
        "structuredIntent": {
            "successPredicates": [{ "predicateId": "task.success", "unit": "ratio", "comparator": "gte", "boundQ32": 1_i64 << 31, "evidenceSourceId": "observer.task", "terminal": false }],
            "terminalConditions": [{ "predicateId": "task.terminal", "unit": "boolean", "comparator": "eq", "boundQ32": FixedQ32::ONE.raw(), "evidenceSourceId": "observer.task", "terminal": true }],
            "legalActionClasses": source.structured_intent.legal_action_classes,
            "forbiddenActionClasses": ["network"],
            "confirmationActionClasses": [],
            "constraints": [{ "constraintId": "latency.ceiling", "unit": "micros", "comparator": "lte", "boundQ32": 5_000, "evidenceSourceId": "observer.clock", "terminal": false }],
            "softDimensions": [{ "dimensionId": "quality", "unit": "ratio", "direction": "maximize", "minimumWeightQ32": 0, "maximumWeightQ32": FixedQ32::ONE.raw() }],
            "evidenceRequirements": [{ "requirementId": "evidence.quality", "evidenceSourceId": "observer.evidence", "minimumConfidencePpm": 900_000, "terminal": true }],
            "resources": { "timeMicros": 10_000, "tokenCount": 1_000, "computeMicros": 50_000, "memoryBytes": 1_048_576, "networkBytes": 0, "externalEffectCount": 0 },
            "risk": { "riskClass": "low", "abstentionRule": "ask", "rollbackClass": "reversible", "compensationRequired": false },
            "provenance": { "sourceDigest": digest("source-bytes").to_string(), "normalizationProfileDigest": digest("normalization-v1").to_string() }
        },
        "sourceTrustClass": "authorized_adapter",
        "locale": "en-US",
        "observedAt": source.observed_at,
        "deadline": "2030-01-01T00:00:00Z",
        "inputSchemaDigest": source.input_schema_digest.to_string()
    })).expect("strict source JSON")
}

fn request(
    identity: &AgentdIdentity,
    run_id: &StableId,
    source: &ObjectiveSourceEnvelopeV1,
) -> AuthBusObjectiveIngress {
    let body = AuthBusObjectiveBody {
        spawn_generation: identity.spawn_generation,
        run_id: run_id.to_string(),
        objective_revision: 7,
        source_envelope_json: source_json(source),
        runtime_body_digest: digest("runtime-body").to_string(),
        preference_state_digest: digest("preference").to_string(),
        model_tuple_digest: digest("model-tuple").to_string(),
        prompt_registry_digest: digest("prompt-registry").to_string(),
        artifact_set_digest: digest("artifacts").to_string(),
        authority_epoch: 11,
    };
    let mut scope = b"hepta:agentd:signed-objective:v1\0".to_vec();
    scope.extend_from_slice(identity.agent_id.as_str().as_bytes());
    let claims = SignedMessageClaims {
        issuer_id: id("issuer.objective"),
        key_epoch: generation(/*value*/ 1),
        message_id: id("objective-host-replay-message"),
        subject_id: id(identity.agent_id.as_str()),
        scope_digest: Digest32::of_bytes(&scope),
        payload_digest: Digest32::of_bytes(&serde_json::to_vec(&body).expect("signed body")),
        sequence: 2,
        expires_at_ms: wall_clock_ms().expect("host clock") + 60_000,
    };
    let key = SigningKey::from_bytes(&[83; 32]);
    AuthBusObjectiveIngress {
        issuer_id: claims.issuer_id.to_string(),
        key_epoch: claims.key_epoch.get(),
        message_id: claims.message_id.to_string(),
        sequence: claims.sequence,
        expires_at_ms: claims.expires_at_ms,
        signature_hex: key
            .sign(&claims.signing_bytes())
            .to_bytes()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect(),
        body,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn objective_host_parallel_and_reopened_replays_stop_before_provider() {
    let fixture = RunningFixture::new().await;
    let identity = fixture.state.identity();
    let profile_path = identity.home_root.join("objective-profile.json");
    write_private(&profile_path, &profile_json());
    let host =
        ObjectiveRuntimeHost::open(identity, &profile_path).expect("actual ObjectiveStart owner");
    let request = request(
        identity,
        &fixture.record.snapshot.run_id,
        &objective_envelope(),
    );
    let ledger_before = std::fs::read(&fixture.ledger_path).expect("ledger before");
    let witness_before = std::fs::read(&fixture.witness_path).expect("witness before");

    // The signed adapter source intentionally differs from the provider's
    // Principal source. Publication succeeds, then invocation validation fails;
    // no ephemeral run exists to hide a missing durable-publication retry gate.
    let first = host
        .submit(
            &fixture.state,
            request.clone(),
            /*current_generation*/ 2,
        )
        .await;
    assert!(
        matches!(first, Err(AgentdError::Invalid(message)) if message == "canonical intelligence invocation does not match the durable RunStart identity")
    );
    assert_eq!(fixture.provider.calls.load(Ordering::Acquire), 1);

    let runtime = tokio::runtime::Handle::current();
    let start = std::sync::Barrier::new(/*n*/ 2);
    let left_request = request.clone();
    let right_request = request.clone();
    let parallel = std::thread::scope(|threads| {
        let left = threads.spawn(|| {
            start.wait();
            runtime.block_on(host.submit(
                &fixture.state,
                left_request,
                /*current_generation*/ 2,
            ))
        });
        let right = threads.spawn(|| {
            start.wait();
            runtime.block_on(host.submit(
                &fixture.state,
                right_request,
                /*current_generation*/ 2,
            ))
        });
        [
            left.join().expect("left retry"),
            right.join().expect("right retry"),
        ]
    });
    for result in parallel {
        assert!(
            matches!(result, Err(AgentdError::Invalid(code)) if code == "agentd.intuition.service.durable_handoff_reconciliation_required")
        );
    }
    drop(host);
    let reopened =
        ObjectiveRuntimeHost::open(identity, &profile_path).expect("durable RunStart owner reopen");
    reopened
        .reconcile(
            &fixture.state,
            /*current_generation*/ 2,
            wall_clock_ms().expect("recovery clock"),
        )
        .expect("canonical recovery remains quarantined");
    let retry = reopened
        .submit(&fixture.state, request, /*current_generation*/ 2)
        .await;
    assert!(
        matches!(retry, Err(AgentdError::Invalid(code)) if code == "agentd.intuition.service.durable_handoff_reconciliation_required")
    );
    assert_eq!(fixture.provider.calls.load(Ordering::Acquire), 1);
    assert_eq!(
        std::fs::read(&fixture.ledger_path).expect("ledger after"),
        ledger_before
    );
    assert_eq!(
        std::fs::read(&fixture.witness_path).expect("witness after"),
        witness_before
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn compiler_explicit_abstain_parallel_and_reopened_replays_keep_original_publication() {
    let fixture = RunningFixture::new().await;
    let identity = fixture.state.identity();
    let profile_path = identity.home_root.join("objective-profile.json");
    write_private(&profile_path, &profile_json());
    let host =
        ObjectiveRuntimeHost::open(identity, &profile_path).expect("actual ObjectiveStart owner");
    let mut source = objective_envelope();
    source.structured_intent.legal_action_classes.clear();
    source.intent_digest =
        canonical_objective_intent_digest_v1(&source).expect("native abstain intent");
    let request = request(identity, &fixture.record.snapshot.run_id, &source);
    let ledger_before = std::fs::read(&fixture.ledger_path).expect("ledger before");
    let witness_before = std::fs::read(&fixture.witness_path).expect("witness before");
    let original = match host
        .submit(
            &fixture.state,
            request.clone(),
            /*current_generation*/ 2,
        )
        .await
        .expect("native compiler abstain publication")
    {
        crate::objective_runtime::ObjectiveStartResult::Admitted(receipt) => Some(receipt),
        crate::objective_runtime::ObjectiveStartResult::Conflict { .. } => None,
    }
    .expect("native compiler abstain is not a conflict");
    assert_eq!(original.disposition, "explicit_abstain");
    assert!(!original.idempotent);
    let journal_path = identity
        .home_root
        .join("objective-run-start-v1")
        .join("journal.bin");
    let journal_before = std::fs::read(&journal_path).expect("published journal");
    let mut expected = original;
    expected.idempotent = true;

    // This is the compiler's terminal outcome, not Compiled followed by a
    // canonical policy abstention. The latter still needs its original handoff.
    let runtime = tokio::runtime::Handle::current();
    let start = std::sync::Barrier::new(/*n*/ 2);
    let left_request = request.clone();
    let right_request = request.clone();
    let parallel = std::thread::scope(|threads| {
        let left = threads.spawn(|| {
            start.wait();
            runtime.block_on(host.submit(
                &fixture.state,
                left_request,
                /*current_generation*/ 2,
            ))
        });
        let right = threads.spawn(|| {
            start.wait();
            runtime.block_on(host.submit(
                &fixture.state,
                right_request,
                /*current_generation*/ 2,
            ))
        });
        [
            left.join().expect("left terminal retry"),
            right.join().expect("right terminal retry"),
        ]
    });
    for result in parallel {
        assert!(
            matches!(result, Ok(crate::objective_runtime::ObjectiveStartResult::Admitted(receipt)) if receipt == expected)
        );
    }
    drop(host);
    let reopened =
        ObjectiveRuntimeHost::open(identity, &profile_path).expect("durable RunStart owner reopen");
    reopened
        .reconcile(
            &fixture.state,
            /*current_generation*/ 2,
            wall_clock_ms().expect("recovery clock"),
        )
        .expect("native compiler terminal recovery");
    let retry = reopened
        .submit(
            &fixture.state,
            request.clone(),
            /*current_generation*/ 2,
        )
        .await;
    assert!(
        matches!(retry, Ok(crate::objective_runtime::ObjectiveStartResult::Admitted(receipt)) if receipt == expected)
    );

    let mut expired = request.clone();
    expired.expires_at_ms = 0;
    assert!(matches!(
        reopened.submit(&fixture.state, expired, /*current_generation*/ 2).await,
        Err(AgentdError::Invalid(message)) if message == "objective expiry must be within five minutes"
    ));
    let trust_path = identity.home_root.join("objective-trust.json");
    let mut trust: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&trust_path).expect("current issuer trust"))
            .expect("trust JSON");
    trust["revoked"] = serde_json::json!(true);
    write_private(&trust_path, &trust);
    assert!(matches!(
        reopened.submit(&fixture.state, request.clone(), /*current_generation*/ 2).await,
        Err(AgentdError::Invalid(message)) if message.starts_with("objective signature:")
    ));
    trust["revoked"] = serde_json::json!(false);
    write_private(&trust_path, &trust);
    let registry = FleetRegistry::open_existing(
        HeptaFleetRoot::parse(fixture._directory.path().join("fleet")).expect("existing Fleet"),
    )
    .expect("existing Fleet owner");
    registry
        .compare_and_transition(
            &identity.agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .expect("Draining 3");
    assert!(matches!(
        reopened.submit(&fixture.state, request, /*current_generation*/ 2).await,
        Err(AgentdError::Invalid(message)) if message == "Agent generation is not ready"
    ));
    assert_eq!(fixture.provider.calls.load(Ordering::Acquire), 0);
    assert_eq!(
        std::fs::read(&journal_path).expect("journal after retries"),
        journal_before
    );
    assert_eq!(
        std::fs::read(&fixture.ledger_path).expect("ledger after"),
        ledger_before
    );
    assert_eq!(
        std::fs::read(&fixture.witness_path).expect("witness after"),
        witness_before
    );
}
