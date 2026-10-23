use super::*;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceInvocationV1;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdState;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_paths::HeptaFleetRoot;

#[path = "intelligence_objective_ingress_fixture.rs"]
mod wire_fixture;

struct InvocationProvider {
    invocation: Mutex<Option<AgentdIntelligenceInvocationV1>>,
    publication: Mutex<Option<RunStartRecordV1>>,
}

impl AgentdIntelligenceInvocationProviderV1 for InvocationProvider {
    fn build(
        &self,
        _identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        *self.publication.lock().expect("publication mutex") = Some(record.clone());
        self.invocation
            .lock()
            .expect("invocation mutex")
            .take()
            .ok_or_else(|| AgentdError::Protocol("fixture invocation already consumed".to_string()))
    }
}

struct ObjectiveHostFixture {
    _temp: tempfile::TempDir,
    _writer_lock: fs::File,
    state: AgentdState,
    provider: Arc<InvocationProvider>,
    request: AuthBusObjectiveIngress,
    canonical_request: CanonicalIntelligenceRunRequestV1,
    context_digest: Digest32,
}

fn write_private(path: &std::path::Path, bytes: &[u8]) {
    fs::write(path, bytes).expect("write explicit owner configuration");
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).expect("private configuration");
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

async fn objective_host_fixture() -> ObjectiveHostFixture {
    let temp = tempfile::tempdir().expect("owner root");
    let root = temp.path().canonicalize().expect("canonical root");
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).expect("private root");
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
    let workspace = root.join("workspace");
    fs::create_dir(&workspace).expect("workspace");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root).expect("workspace binding"),
        ResourceBudget::local_default(),
    )
    .expect("manifest");
    let registered = registry.register(manifest).expect("registered agent");
    registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect("Starting");
    let home = registered.layout.home_root().to_path_buf();
    fs::set_permissions(&home, fs::Permissions::from_mode(0o700)).expect("private home");

    // This explicit test profile admits the fixed source date at the real clock.
    // Production policy is still loaded, frozen and authenticated by the host.
    let mut profile = objective_profile();
    profile.maximum_source_age_micros = u64::MAX;
    let mut source = objective_envelope();
    source.source_trust_class = ObjectiveSourceTrustV1::AuthorizedAdapter;
    source.deadline = Some("2099-12-31T23:59:59Z".to_string());
    source.intent_digest = canonical_objective_intent_digest_v1(&source).expect("source digest");
    let context = ObjectiveAdmissionContextV1 {
        revision: revision(7),
        now_unix_micros: crate::authbus_ingress::now_ms().expect("clock") * 1_000,
        selected_profile_digest: profile.digest().expect("profile digest"),
        source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
            source_identity: id("adapter.console"),
            source_digest: source.structured_intent.provenance.source_digest,
        },
    };
    let (value, trust) = signed_fixture_with_body(
        fixture_for_objective(profile.clone(), source.clone(), context),
        generation(1),
    );
    let canonical_request = value.request.clone();
    let context_digest = compile(value.inputs.context_request.clone())
        .expect("real context")
        .context_digest;
    let authority = root.join("authority.json");
    write_authority_file(
        &authority,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = Arc::new(
        AgentdIntelligenceProductRunnerV1::new(authority, authority_verifier())
            .expect("runner")
            .with_evaluation_trust(trust)
            .expect("evaluation trust"),
    );
    let provider = Arc::new(InvocationProvider {
        invocation: Mutex::new(Some(AgentdIntelligenceInvocationV1 {
            request: value.request,
            inputs: value.inputs,
        })),
        publication: Mutex::new(None),
    });
    let signer = SigningKey::from_bytes(&[53; 32]);
    let trust_file = home.join("authbus-trust.json");
    write_private(
        &trust_file,
        &serde_json::to_vec(&serde_json::json!({
            "schema_version": 1, "agent_id": agent_id.to_string(), "issuer_id": "adapter.console",
            "key_epoch": 1, "public_key_hex": hex(&signer.verifying_key().to_bytes()),
            "revoked": false, "thread_ids": [],
        }))
        .expect("trust JSON"),
    );
    let profile_file = home.join("objective-profile.json");
    let profile_json = wire_fixture::profile_json(&profile);
    assert_eq!(
        codex_hepta_objective::decode_admission_profile_json_v1(&profile_json)
            .expect("profile roundtrip"),
        profile
    );
    write_private(&profile_file, &profile_json);
    let evidence = codex_hepta_evidence::HeptaEvidenceStore::open(
        &codex_state::SqliteConfig::from_sqlite_home(
            codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(&home)
                .expect("absolute home"),
        ),
    )
    .await
    .expect("canonical evidence owner");
    let frontier = evidence
        .authbus_replay_frontier_digest()
        .await
        .expect("empty frontier");
    drop(evidence);
    let checkpoint_file = root.join("replay-checkpoint.json");
    write_private(
        &checkpoint_file,
        &serde_json::to_vec(&serde_json::json!({
            "schema_version": 1, "agent_id": agent_id.to_string(), "generation": 1,
            "digest": frontier.to_string(),
        }))
        .expect("checkpoint JSON"),
    );

    let config = AgentdConfig::load(
        fleet_path,
        agent_id.clone(),
        1,
        home.clone(),
        registered.layout.run_root().to_path_buf(),
        home,
        workspace,
    )
    .expect("real daemon config and writer lock")
    .with_authbus_trust_file(trust_file)
    .with_authbus_checkpoint_file(checkpoint_file)
    .with_objective_profile_file(profile_file)
    .with_intelligence_product_runner(runner)
    .expect("configured runner")
    .with_intelligence_invocation_provider(provider.clone())
    .expect("configured seven owners");
    let selected_runner = config
        .intelligence_product_runner()
        .expect("selected runner");
    let selected_provider = config
        .intelligence_invocation_provider()
        .expect("selected provider");
    let ingress = crate::authbus_ingress::TextIngress::open(
        config.identity(),
        config
            .authbus_trust_file()
            .expect("trust path")
            .to_path_buf(),
        config
            .authbus_checkpoint_file()
            .expect("checkpoint path")
            .to_path_buf(),
    )
    .await
    .expect("real signed ingress");
    let objective = crate::objective_runtime::ObjectiveRuntimeHost::open(
        config.identity(),
        config.objective_profile_file().expect("profile path"),
    )
    .expect("durable Objective owner");
    let (identity, registry, writer_lock) = config.into_parts();
    let state = AgentdState::new(identity, registry.clone(), 16).expect("daemon state");
    assert!(state.intelligence_product.set(selected_runner).is_ok());
    assert!(state.intelligence_invocation.set(selected_provider).is_ok());
    assert!(state.authbus.set(Arc::new(ingress)).is_ok());
    assert!(state.objective_runtime.set(Arc::new(objective)).is_ok());
    registry
        .compare_and_transition(&agent_id, 1, AgentLifecycle::Running)
        .expect("Running");
    state.refresh_generation().expect("durable Running epoch");
    let cognitive =
        codex_hepta_cognitive_store::DurableCognitiveStore::open(&state.identity().layout)
            .await
            .expect("real cognitive owner");
    state
        .attach_cognitive_store(Arc::new(cognitive))
        .expect("cognitive attachment");
    state
        .mark_runtime_prerequisites_ready()
        .expect("complete owner readiness");
    state.mark_app_server_ready().expect("App Server readiness");

    let body = AuthBusObjectiveBody {
        spawn_generation: 1,
        run_id: canonical_request.run_id.to_string(),
        objective_revision: 7,
        source_envelope_json: wire_fixture::source_json(&source),
        runtime_body_digest: crate::intelligence_ingress::canonical_runtime_body_digest(
            &canonical_request.snapshot,
        )
        .to_string(),
        preference_state_digest: digest("preference").to_string(),
        model_tuple_digest: digest("model").to_string(),
        prompt_registry_digest: digest("prompt").to_string(),
        artifact_set_digest: canonical_request.snapshot.digest().to_string(),
        authority_epoch: 11,
    };
    let mut request = AuthBusObjectiveIngress {
        issuer_id: "adapter.console".to_string(),
        key_epoch: 1,
        message_id: "objective.1".to_string(),
        sequence: 1,
        expires_at_ms: crate::authbus_ingress::now_ms().expect("clock") + 300_000,
        signature_hex: String::new(),
        body,
    };
    let mut scope = b"hepta:agentd:signed-objective:v1\0".to_vec();
    scope.extend_from_slice(agent_id.as_str().as_bytes());
    let claims = SignedMessageClaims {
        issuer_id: id(&request.issuer_id),
        key_epoch: generation(request.key_epoch),
        message_id: id(&request.message_id),
        subject_id: id(agent_id.as_str()),
        scope_digest: Digest32::of_bytes(&scope),
        payload_digest: Digest32::of_bytes(&serde_json::to_vec(&request.body).expect("body JSON")),
        sequence: request.sequence,
        expires_at_ms: request.expires_at_ms,
    };
    request.signature_hex = hex(&signer.sign(&claims.signing_bytes()).to_bytes());
    ObjectiveHostFixture {
        _temp: temp,
        _writer_lock: writer_lock,
        state,
        provider,
        request,
        canonical_request,
        context_digest,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn configured_running_objective_reaches_seven_owners_and_exact_durable_context_receipt() {
    let fixture = objective_host_fixture().await;
    let response = fixture
        .state
        .response(
            1,
            1,
            AgentdMethod::ObjectiveStart {
                request: fixture.request.clone(),
            },
        )
        .await
        .expect("signed ObjectiveStart through daemon");
    let AgentdPayload::ObjectiveRun(admission) = response.payload else {
        panic!("Objective receipt");
    };
    assert_eq!(admission.disposition, "canonical_ready");
    let record = fixture
        .provider
        .publication
        .lock()
        .expect("publication mutex")
        .clone()
        .expect("actual durable publication");
    assert_eq!(record.snapshot.generation, 2);
    assert_eq!(
        fixture.canonical_request.snapshot.body_generation(),
        generation(1)
    );
    let status = fixture
        .state
        .response(
            2,
            1,
            AgentdMethod::RunStatus {
                run_id: admission.run_id.clone(),
            },
        )
        .await
        .expect("actual coordinator receipt");
    let AgentdPayload::RunStatus { run: Some(actual) } = status.payload else {
        panic!("attached run");
    };
    let compilation = actual
        .compilation_receipt_digest
        .clone()
        .expect("canonical envelope receipt");
    assert!(
        !compilation
            .parse::<Digest32>()
            .expect("receipt digest")
            .is_zero()
    );
    assert_eq!(
        actual,
        crate::AgentRunReceipt {
            run_id: admission.run_id,
            revision: 2,
            phase: crate::AgentRunPhase::ContextAttached,
            context_digest: Some(fixture.context_digest.to_string()),
            compilation_receipt_digest: Some(compilation),
            authority_epoch: record.snapshot.authority_epoch,
            generation: record.snapshot.generation,
            fence_digest: record.snapshot.fence_digest.to_string(),
            deadline_ms: record.admission.deadline_unix_micros.div_ceil(1_000),
            cancel_reason: None,
            cancel_ack_deadline_ms: None,
            terminal_observed: false,
            idempotent: false,
        }
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn objective_binding_rejects_mixed_lifecycle_body_epoch_and_artifacts() {
    let fixture = objective_host_fixture().await;
    fixture
        .state
        .response(
            1,
            1,
            AgentdMethod::ObjectiveStart {
                request: fixture.request.clone(),
            },
        )
        .await
        .expect("valid authenticated publication");
    let record = fixture
        .provider
        .publication
        .lock()
        .expect("publication mutex")
        .clone()
        .expect("durable record");
    let invocation = AgentdIntelligenceInvocationV1 {
        request: fixture.canonical_request.clone(),
        inputs: super::super::fixture().inputs,
    };
    invocation
        .validate(fixture.state.identity(), &record)
        .expect("separate process/lifecycle domains");
    for field in 0..5 {
        let mut mixed = record.clone();
        match field {
            0 => mixed.snapshot.generation = 1,
            1 => mixed.snapshot.fence_digest = digest("foreign-fence"),
            2 => mixed.runtime_body_digest = digest("foreign-body"),
            3 => mixed.snapshot.authority_epoch += 1,
            4 => mixed.snapshot.artifact_set_digest = digest("foreign-artifacts"),
            _ => unreachable!(),
        }
        assert!(
            invocation
                .validate(fixture.state.identity(), &mixed)
                .is_err(),
            "mixed field {field}"
        );
    }
    let snapshot = invocation.request.snapshot.clone();
    let mut owners = owner_bindings();
    for owner in &mut owners {
        if owner.owner_id.as_str() == "learning.eval" {
            owner.key_digest =
                Digest32::of_bytes(&SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes());
        }
    }
    let mut wrong_body = invocation;
    wrong_body.request.snapshot =
        CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
            objective_digest: snapshot.objective_digest(),
            authority_epoch: snapshot.authority_epoch(),
            body_generation: generation(2),
            configuration_digest: snapshot.configuration_digest(),
            revocation_frontier_digest: snapshot.revocation_frontier_digest(),
            owner_bindings: owners,
        })
        .expect("different immutable Body");
    let mut wrong_record = record;
    wrong_record.snapshot.artifact_set_digest = wrong_body.request.snapshot.digest();
    wrong_record.runtime_body_digest =
        crate::intelligence_ingress::canonical_runtime_body_digest(&wrong_body.request.snapshot);
    assert!(
        wrong_body
            .validate(fixture.state.identity(), &wrong_record)
            .is_err()
    );
}
