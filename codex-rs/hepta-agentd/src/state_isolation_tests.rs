use std::fs;
use std::fs::OpenOptions;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

use super::*;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_learning_ledger::DurableRunStartJournal;
use codex_hepta_learning_ledger::RunStartAdmissionBindingV1;
use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_learning_ledger::RunStartSnapshotV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::AgentdPayload;
use crate::LifecycleSnapshot;
use crate::RunPhase;

fn fixture() -> anyhow::Result<(tempfile::TempDir, FleetRegistry, AgentdState)> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?;
    let record = registry.register(manifest)?;
    registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let identity = AgentdIdentity {
        agent_id,
        layout: record.layout.clone(),
        spawn_generation: 1,
        fleet_root: fleet_path,
        workspace,
        resources: record.manifest.resources,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    let state = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16)?;
    registry.compare_and_transition(
        &state.identity.agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    state.refresh_generation()?;
    state.mark_app_server_ready()?;
    Ok((temp, registry, state))
}

#[tokio::test]
async fn serving_agent_survives_unrelated_registry_corruption() {
    let (_temp, registry, state) = fixture().expect("runtime fixture");
    let peer = registry
        .layout()
        .agents_root()
        .join("019153a4-3088-7e03-a56a-9b1964f75dd3");
    fs::create_dir(peer).expect("incomplete peer");
    assert!(registry.load().is_err());
    state
        .refresh_generation()
        .expect("local generation remains valid");
    let response = state
        .response(
            /*request_id*/ 1,
            /*spawn_generation*/ 1,
            crate::AgentdMethod::Lifecycle,
        )
        .await
        .expect("serving control response");
    assert_eq!(
        serde_json::to_value(response.payload).expect("serialize actual lifecycle"),
        serde_json::to_value(AgentdPayload::Lifecycle(LifecycleSnapshot {
            lifecycle: AgentLifecycle::Running,
            app_server_ready: true,
            fenced: false,
        }))
        .expect("serialize expected lifecycle")
    );
}

struct RejectingIntelligenceInvocationProvider;

impl crate::AgentdIntelligenceInvocationProviderV1 for RejectingIntelligenceInvocationProvider {
    fn build(
        &self,
        _identity: &crate::AgentdIdentity,
        _record: &RunStartRecordV1,
    ) -> Result<crate::AgentdIntelligenceInvocationV1, AgentdError> {
        Err(AgentdError::Protocol(
            "test provider is not invoked by capability discovery".to_string(),
        ))
    }
}

#[tokio::test]
async fn configured_intelligence_runner_is_not_advertised_without_daemon_ingress() {
    let (temp, _registry, state) = fixture().expect("runtime fixture");
    let before = state
        .response(1, 1, crate::AgentdMethod::Capabilities)
        .await
        .expect("initial capabilities");
    let signer = ed25519_dalek::SigningKey::from_bytes(&[41; 32]);
    let runner = crate::AgentdIntelligenceProductRunnerV1::new(
        temp.path().join("intelligence-authority.json"),
        crate::IntelligenceAuthorityVerifierV1 {
            signer_id: "authority.owner".to_string(),
            verifying_key: signer.verifying_key().to_bytes(),
        },
    )
    .expect("valid runner");
    if state.intelligence_product.set(Arc::new(runner)).is_err() {
        panic!("attach runner once");
    }

    let response = state
        .response(
            /*request_id*/ 2,
            /*spawn_generation*/ 1,
            crate::AgentdMethod::Capabilities,
        )
        .await
        .expect("capabilities response");
    let AgentdPayload::Capabilities(capabilities) = response.payload else {
        panic!("capabilities payload");
    };
    let AgentdPayload::Capabilities(before) = before.payload else {
        panic!("initial capabilities payload");
    };
    assert_eq!(
        capabilities, before,
        "runner presence must not advertise an unconnected capability"
    );
}

#[tokio::test]
async fn canonical_intelligence_is_advertised_only_with_runner_and_host_provider() {
    let (temp, _registry, state) = fixture().expect("runtime fixture");
    let signer = ed25519_dalek::SigningKey::from_bytes(&[42; 32]);
    let runner = crate::AgentdIntelligenceProductRunnerV1::new(
        temp.path().join("intelligence-authority.json"),
        crate::IntelligenceAuthorityVerifierV1 {
            signer_id: "authority.owner".to_string(),
            verifying_key: signer.verifying_key().to_bytes(),
        },
    )
    .expect("valid runner");
    assert!(state.intelligence_product.set(Arc::new(runner)).is_ok());
    assert!(
        state
            .intelligence_invocation
            .set(Arc::new(RejectingIntelligenceInvocationProvider))
            .is_ok()
    );
    let response = state
        .response(3, 1, crate::AgentdMethod::Capabilities)
        .await
        .expect("capabilities response");
    let AgentdPayload::Capabilities(capabilities) = response.payload else {
        panic!("capabilities payload");
    };
    assert!(capabilities.capabilities.iter().any(|capability| {
        capability.id == crate::AGENTD_CAPABILITY_CANONICAL_INTELLIGENCE_V1
            && capability.major == 1
            && capability.minor == 0
    }));
}

#[test]
fn missing_local_record_immediately_fences_the_serving_agent() {
    let (_temp, _registry, state) = fixture().expect("runtime fixture");
    fs::remove_file(state.identity.layout.agent_config()).expect("remove local manifest");
    assert!(matches!(
        state.refresh_generation(),
        Err(AgentdError::GenerationFenced(_))
    ));
    assert!(state.is_fenced().expect("fenced state"));
}

#[test]
fn targeted_read_preserves_lifecycle_and_resource_fences() {
    let (_temp, registry, state) = fixture().expect("runtime fixture");
    // Separate owners: the original state holds a real prompt-registry lock.
    // A second host of the same directory is not a valid resource-fence fixture.
    let (_changed_temp, _changed_registry, mut changed) = fixture().expect("independent owner");
    changed.identity.resources.turn_queue_capacity += 1;
    assert!(matches!(
        changed.refresh_generation(),
        Err(AgentdError::GenerationFenced(_))
    ));
    registry
        .compare_and_transition(
            &state.identity.agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .expect("draining");
    state.refresh_generation().expect("drain remains valid");
    registry
        .compare_and_transition(
            &state.identity.agent_id,
            /*expected_generation*/ 3,
            AgentLifecycle::Stopped,
        )
        .expect("stopped");
    assert!(matches!(
        state.refresh_generation(),
        Err(AgentdError::GenerationFenced(_))
    ));
}

fn digest(byte: char) -> String {
    byte.to_string().repeat(64)
}

fn run_fence(state: &AgentdState, current_generation: u64) -> String {
    let mut material = b"hepta:agentd:objective-fence:v1\0".to_vec();
    material.extend_from_slice(state.identity.agent_id.as_str().as_bytes());
    material.extend_from_slice(&state.identity.spawn_generation.to_be_bytes());
    material.extend_from_slice(&current_generation.to_be_bytes());
    codex_hepta_contracts::Sha256Digest::for_bytes(&material)
        .as_str()
        .to_string()
}

#[tokio::test]
async fn daemon_control_owns_the_run_lifecycle_and_advertises_it() {
    let (_temp, _registry, state) = fixture().expect("runtime fixture");

    let capabilities = state
        .response(
            /*request_id*/ 10,
            /*spawn_generation*/ 1,
            crate::AgentdMethod::Capabilities,
        )
        .await
        .expect("capabilities");
    let AgentdPayload::Capabilities(capabilities) = capabilities.payload else {
        panic!("expected capabilities payload");
    };
    assert!(capabilities.capabilities.iter().any(|capability| {
        capability.id == crate::AGENTD_RUN_LIFECYCLE_CAPABILITY_ID
            && capability.major == crate::AGENTD_RUN_LIFECYCLE_CAPABILITY_MAJOR
            && capability.minor == crate::AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR
    }));

    let snapshot = crate::AgentRunSnapshot {
        run_id: "run.control.1".to_string(),
        request_digest: digest('1'),
        objective_digest: digest('2'),
        body_digest: digest('3'),
        artifact_set_digest: digest('4'),
        authority_epoch: 7,
        generation: 2,
        fence_digest: run_fence(&state, 2),
        deadline_ms: u64::MAX - 1,
    };
    let mut stale_generation = snapshot.clone();
    stale_generation.run_id = "run.control.stale-generation".to_string();
    stale_generation.generation = 1;
    assert!(
        state
            .response(
                11,
                1,
                crate::AgentdMethod::RunStart {
                    snapshot: stale_generation,
                },
            )
            .await
            .is_err()
    );

    let mut stale_fence = snapshot.clone();
    stale_fence.run_id = "run.control.stale-fence".to_string();
    stale_fence.fence_digest = digest('f');
    assert!(
        state
            .response(
                11,
                1,
                crate::AgentdMethod::RunStart {
                    snapshot: stale_fence,
                },
            )
            .await
            .is_err()
    );

    let started = state
        .response(
            11,
            1,
            crate::AgentdMethod::RunStart {
                snapshot: snapshot.clone(),
            },
        )
        .await
        .expect("start run");
    let AgentdPayload::RunReceipt(started) = started.payload else {
        panic!("expected run receipt");
    };
    assert_eq!(started.phase, crate::AgentRunPhase::Admitted);
    assert_eq!(started.revision, 1);

    let attached = state
        .response(
            12,
            1,
            crate::AgentdMethod::RunAttachContext {
                expected_revision: started.revision,
                attachment: crate::AgentContextAttachment {
                    run_id: snapshot.run_id.clone(),
                    request_digest: snapshot.request_digest.clone(),
                    objective_digest: snapshot.objective_digest.clone(),
                    body_digest: snapshot.body_digest.clone(),
                    artifact_set_digest: snapshot.artifact_set_digest.clone(),
                    authority_epoch: snapshot.authority_epoch,
                    generation: snapshot.generation,
                    fence_digest: snapshot.fence_digest.clone(),
                    deadline_ms: snapshot.deadline_ms,
                    context_digest: digest('5'),
                    compilation_receipt_digest: digest('6'),
                },
            },
        )
        .await
        .expect("attach context");
    let AgentdPayload::RunReceipt(attached) = attached.payload else {
        panic!("expected run receipt");
    };
    assert_eq!(attached.phase, crate::AgentRunPhase::ContextAttached);
    assert_eq!(attached.revision, 2);

    let dispatched = state
        .response(
            13,
            1,
            crate::AgentdMethod::RunMarkDispatched {
                run_id: snapshot.run_id.clone(),
                expected_revision: attached.revision,
            },
        )
        .await
        .expect("mark dispatched");
    let AgentdPayload::RunReceipt(dispatched) = dispatched.payload else {
        panic!("expected run receipt");
    };
    assert_eq!(dispatched.phase, crate::AgentRunPhase::Dispatched);
    assert_eq!(dispatched.revision, 3);

    state.mark_draining().expect("begin local drain");
    assert!(
        state
            .response(
                14,
                1,
                crate::AgentdMethod::RunStart {
                    snapshot: crate::AgentRunSnapshot {
                        run_id: "run.control.2".to_string(),
                        ..snapshot.clone()
                    },
                },
            )
            .await
            .is_err()
    );

    let status = state
        .response(
            15,
            1,
            crate::AgentdMethod::RunStatus {
                run_id: snapshot.run_id.clone(),
            },
        )
        .await
        .expect("run remains queryable during drain");
    let AgentdPayload::RunStatus {
        run: Some(draining),
    } = status.payload
    else {
        panic!("expected draining run status");
    };
    assert_eq!(draining.phase, crate::AgentRunPhase::Cancelling);
    assert_eq!(draining.cancel_reason.as_deref(), Some("agentd_shutdown"));

    let terminal = state
        .response(
            16,
            1,
            crate::AgentdMethod::RunObserveTerminal {
                run_id: snapshot.run_id,
                expected_revision: draining.revision,
                phase: crate::AgentRunPhase::Succeeded,
                terminal_observed: true,
            },
        )
        .await
        .expect("terminal observation during drain");
    let AgentdPayload::RunReceipt(terminal) = terminal.payload else {
        panic!("expected terminal receipt");
    };
    assert_eq!(terminal.phase, crate::AgentRunPhase::Succeeded);
    assert!(terminal.terminal_observed);
    assert_eq!(state.active_run_count().expect("active runs"), 0);

    let released = state
        .response(
            17,
            1,
            crate::AgentdMethod::RunReleaseClosed {
                run_id: terminal.run_id.clone(),
                expected_revision: terminal.revision,
            },
        )
        .await
        .expect("release closed run");
    let AgentdPayload::RunReceipt(released) = released.payload else {
        panic!("expected released run receipt");
    };
    assert_eq!(released.phase, crate::AgentRunPhase::Succeeded);

    let status = state
        .response(
            18,
            1,
            crate::AgentdMethod::RunStatus {
                run_id: released.run_id,
            },
        )
        .await
        .expect("status after release");
    let AgentdPayload::RunStatus { run } = status.payload else {
        panic!("expected run status");
    };
    assert!(run.is_none());
}

#[tokio::test]
async fn current_durable_run_start_requires_live_owner_trust() {
    let (temp, registry, previous) = fixture().expect("runtime fixture");
    let identity = previous.identity.clone();
    drop(previous);
    let state = AgentdState::new(identity, registry, 16).expect("restarted owner");
    state.refresh_generation().expect("current generation");
    fs::set_permissions(&state.identity.home_root, fs::Permissions::from_mode(0o700))
        .expect("private home");

    let cognitive =
        codex_hepta_cognitive_store::DurableCognitiveStore::open(&state.identity.layout)
            .await
            .expect("cognitive owner");
    state
        .attach_cognitive_store(Arc::new(cognitive))
        .expect("attach cognitive owner");
    state
        .mark_runtime_prerequisites_ready()
        .expect("owner prerequisites");
    state
        .mark_app_server_ready()
        .expect("ready after owner initialization");
    let key = SigningKey::from_bytes(&[77; 32]);
    let trust_file = state.identity.home_root.join("run-start-trust.json");
    let write_trust = |revoked: bool| {
        let public_key_hex = key
            .verifying_key()
            .as_bytes()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let value = serde_json::json!({
            "schema_version": 1,
            "agent_id": state.identity.agent_id.as_str(),
            "issuer_id": "issuer:run-start",
            "key_epoch": 1,
            "public_key_hex": public_key_hex,
            "revoked": revoked,
            "thread_ids": []
        });
        fs::write(&trust_file, serde_json::to_vec(&value).expect("trust json"))
            .expect("write trust");
        fs::set_permissions(&trust_file, fs::Permissions::from_mode(0o600)).expect("private trust");
    };
    write_trust(false);
    let checkpoint_file = temp.path().join("run-start-replay-checkpoint.json");
    // The external fixture witness is captured from the canonical empty owner,
    // never invented from a label or recaptured from a suspect backup.
    let evidence = codex_hepta_evidence::HeptaEvidenceStore::open(
        &codex_state::SqliteConfig::from_sqlite_home(
            codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(
                &state.identity.home_root,
            )
            .expect("owner home"),
        ),
    )
    .await
    .expect("evidence owner");
    let frontier = evidence
        .authbus_replay_frontier_digest()
        .await
        .expect("initial frontier");
    drop(evidence);
    let checkpoint = serde_json::json!({
        "schema_version": 1,
        "agent_id": state.identity.agent_id.to_string(),
        "generation": 1,
        "digest": frontier.to_string(),
    });
    fs::write(
        &checkpoint_file,
        serde_json::to_vec(&checkpoint).expect("checkpoint json"),
    )
    .expect("write checkpoint");
    fs::set_permissions(&checkpoint_file, fs::Permissions::from_mode(0o600))
        .expect("private checkpoint");
    let ingress = crate::authbus_ingress::TextIngress::open(
        state.identity(),
        trust_file.clone(),
        checkpoint_file,
    )
    .await
    .expect("open trust");
    state
        .authbus
        .set(Arc::new(ingress))
        .map_err(|_| ())
        .expect("attach trust");

    let now_ms = crate::authbus_ingress::now_ms().expect("clock");
    let mut scope_bytes = b"hepta:agentd:signed-objective:v1\0".to_vec();
    scope_bytes.extend_from_slice(state.identity.agent_id.as_str().as_bytes());
    let scope = Digest32::of_bytes(&scope_bytes);
    let signed_body = crate::AuthBusObjectiveBody {
        spawn_generation: state.identity.spawn_generation,
        run_id: "run.durable.current".to_string(),
        objective_revision: 1,
        source_envelope_json: "{}".to_string(),
        runtime_body_digest: Digest32::of_bytes(b"body").to_string(),
        preference_state_digest: Digest32::of_bytes(b"preference").to_string(),
        model_tuple_digest: Digest32::of_bytes(b"model").to_string(),
        prompt_registry_digest: Digest32::of_bytes(b"prompt").to_string(),
        artifact_set_digest: Digest32::of_bytes(b"artifacts").to_string(),
        authority_epoch: 7,
    };
    let signed_body_bytes = serde_json::to_vec(&signed_body).unwrap();
    let signed_body_digest = Digest32::of_bytes(&signed_body_bytes);
    let claims = SignedMessageClaims {
        issuer_id: StableId::new("issuer:run-start").expect("issuer"),
        key_epoch: Generation::new(1).expect("key epoch"),
        message_id: StableId::new("message:run-start:1").expect("message"),
        subject_id: StableId::new(state.identity.agent_id.as_str()).expect("subject"),
        scope_digest: scope,
        payload_digest: signed_body_digest,
        sequence: 1,
        expires_at_ms: now_ms + 300_000,
    };
    let objective_bytes = b"compiled objective".to_vec();
    let objective_protocol_bytes = b"objective protocol v1".to_vec();
    let run_id = StableId::new("run.durable.current").expect("run id");
    let record = RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            signed_body_bytes,
            issuer_id: claims.issuer_id.clone(),
            key_epoch: claims.key_epoch.get(),
            message_id: claims.message_id.clone(),
            sequence: claims.sequence,
            expires_at_ms: claims.expires_at_ms,
            scope_digest: claims.scope_digest,
            signed_body_digest,
            signature: key.sign(&claims.signing_bytes()).to_bytes(),
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: StableId::new("profile.run-start").expect("profile"),
            profile_revision: 1,
            profile_digest: Digest32::of_bytes(b"profile"),
            supplied_source_digest: Digest32::of_bytes(b"source"),
            intent_digest: Digest32::of_bytes(b"intent"),
            admitted_source_digest: Digest32::of_bytes(b"admitted source"),
            observed_at_unix_micros: now_ms * 1_000,
            deadline_unix_micros: (now_ms + 60_000) * 1_000,
            authority: AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::Compiled,
        snapshot: RunStartSnapshotV1 {
            run_id: run_id.clone(),
            objective_digest: Digest32::of_bytes(&objective_bytes),
            hard_constraint_digest: Digest32::of_bytes(b"hard"),
            preference_state_digest: Digest32::of_bytes(b"preference"),
            model_tuple_digest: Digest32::of_bytes(b"model"),
            prompt_registry_digest: Digest32::of_bytes(b"prompt"),
            artifact_set_digest: Digest32::of_bytes(b"artifacts"),
            authority_epoch: 7,
            generation: 2,
            fence_digest: objective_run_fence(state.identity(), 2)
                .parse()
                .expect("fence digest"),
        },
        runtime_body_digest: Digest32::of_bytes(b"body"),
        objective_semantic_bytes: objective_bytes,
        objective_function_v1_digest: Digest32::of_bytes(&objective_protocol_bytes),
        objective_function_v1_bytes: objective_protocol_bytes,
    };
    let journal_path = temp.path().join("run-start-current.journal");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&journal_path)
        .expect("journal file");
    let mut journal =
        DurableRunStartJournal::create(file, Digest32::of_bytes(b"agentd run-start owner"), 4)
            .expect("create journal");
    journal
        .append(Digest32::ZERO, record)
        .expect("append run start");

    let admitted = state
        .start_current_run_start(&journal, &run_id)
        .expect("current signed durable admission");
    assert_eq!(admitted.phase, RunPhase::Admitted);
    assert_eq!(admitted.generation, 2);

    write_trust(true);
    let second_id = StableId::new("run.durable.revoked").expect("run id");
    let mut second = journal
        .get(&run_id)
        .expect("journal")
        .expect("first record")
        .clone();
    second.snapshot.run_id = second_id.clone();
    second.authentication.message_id = StableId::new("message:run-start:2").expect("message");
    second.authentication.sequence = 2;
    let mut second_body = signed_body;
    second_body.run_id = second_id.to_string();
    second.authentication.signed_body_bytes = serde_json::to_vec(&second_body).unwrap();
    second.authentication.signed_body_digest =
        Digest32::of_bytes(&second.authentication.signed_body_bytes);
    let second_claims = SignedMessageClaims {
        issuer_id: second.authentication.issuer_id.clone(),
        key_epoch: Generation::new(second.authentication.key_epoch).expect("key epoch"),
        message_id: second.authentication.message_id.clone(),
        subject_id: StableId::new(state.identity.agent_id.as_str()).expect("subject"),
        scope_digest: second.authentication.scope_digest,
        payload_digest: second.authentication.signed_body_digest,
        sequence: second.authentication.sequence,
        expires_at_ms: second.authentication.expires_at_ms,
    };
    second.authentication.signature = key.sign(&second_claims.signing_bytes()).to_bytes();
    let predecessor = journal.head_digest();
    journal
        .append(predecessor, second)
        .expect("append revoked candidate");
    assert!(state.start_current_run_start(&journal, &second_id).is_err());
    assert!(
        state
            .runs
            .lock()
            .expect("runs")
            .run(second_id.as_str())
            .is_none()
    );
}

#[tokio::test]
async fn final_use_revalidation_rejects_stale_spawn_generation_before_store_access() {
    let (_temp, _registry, state) = fixture().expect("runtime fixture");
    let result = state
        .response(
            /*request_id*/ 9,
            /*stale spawn_generation*/ 0,
            crate::AgentdMethod::CognitiveContextRevalidate {
                snapshot_digest: "11".repeat(32),
                read_digest: "22".repeat(32),
                omitted_records: 0,
                items: Vec::new(),
                plan: None,
            },
        )
        .await;
    assert!(matches!(result, Err(AgentdError::GenerationFenced(_))));
}
