use super::*;

use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::AgentId;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_evidence::ReplayCheckpoint;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_intelligence::ObjectiveRunBindingsV1;
use codex_hepta_intelligence::compile_and_publish_objective_run_v1;
use codex_hepta_learning_ledger::DurableRunStartJournal;
use codex_hepta_learning_ledger::RunStartAnchor;
use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_learning_ledger::RunStartRecovery;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

pub(super) struct InvocationProvider {
    original: RunStartRecordV1,
    invocation: Mutex<Option<crate::AgentdIntelligenceInvocationV1>>,
    pub(super) calls: AtomicUsize,
    drain_on_build: Option<FleetRegistry>,
}

impl crate::AgentdIntelligenceInvocationProviderV1 for InvocationProvider {
    fn build(
        &self,
        identity: &crate::AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<crate::AgentdIntelligenceInvocationV1, crate::AgentdError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        if record != &self.original {
            return Err(crate::AgentdError::Invalid(
                "fixture original RunStart changed".into(),
            ));
        }
        if let Some(registry) = &self.drain_on_build {
            registry.compare_and_transition(
                &identity.agent_id,
                record.snapshot.generation,
                AgentLifecycle::Draining,
            )?;
        }
        self.invocation
            .lock()
            .expect("invocation lock")
            .take()
            .ok_or_else(|| {
                crate::AgentdError::Invalid("fixture invocation already consumed".into())
            })
    }
}

pub(super) struct RuntimeFixture {
    pub(super) state: crate::AgentdState,
    pub(super) record: RunStartRecordV1,
    pub(super) journal: DurableRunStartJournal,
    pub(super) provider: Arc<InvocationProvider>,
    pub(super) trust_path: PathBuf,
    _directory: tempfile::TempDir,
}

fn utc_timestamp(milliseconds: u64) -> String {
    let seconds: libc::time_t = (milliseconds / 1_000).try_into().expect("timestamp range");
    let mut parts = std::mem::MaybeUninit::<libc::tm>::uninit();
    // SAFETY: both pointers refer to valid local storage. gmtime_r initializes
    // the output on success and does not use the process-global tm buffer.
    let result = unsafe { libc::gmtime_r(&seconds, parts.as_mut_ptr()) };
    assert!(!result.is_null());
    // SAFETY: the successful gmtime_r call initialized the complete tm value.
    let parts = unsafe { parts.assume_init() };
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z",
        parts.tm_year + 1900,
        parts.tm_mon + 1,
        parts.tm_mday,
        parts.tm_hour,
        parts.tm_min,
        parts.tm_sec,
        milliseconds % 1_000
    )
}

pub(super) fn private_json(path: &Path, value: &serde_json::Value) {
    std::fs::write(path, serde_json::to_vec(value).expect("JSON")).expect("write private file");
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).expect("private file");
}

fn fresh_inputs(
    body_generation: u64,
    now: u64,
) -> (
    Fixture,
    codex_hepta_learning_ledger::ActivatedLearningTrustV1,
) {
    let profile = objective_profile();
    let mut envelope = objective_envelope();
    envelope.observed_at = utc_timestamp(now);
    envelope.deadline = Some(utc_timestamp(now + 120_000));
    envelope.intent_digest = canonical_objective_intent_digest_v1(&envelope).expect("intent");
    let mut context = objective_context(&profile, &envelope);
    context.now_unix_micros = now * 1_000;
    let mut value = fixture_from_objective(profile, envelope, context);
    let snapshot = &value.request.snapshot;
    value.request.snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
        objective_digest: snapshot.objective_digest(),
        authority_epoch: snapshot.authority_epoch(),
        body_generation: generation(body_generation),
        configuration_digest: snapshot.configuration_digest(),
        revocation_frontier_digest: snapshot.revocation_frontier_digest(),
        owner_bindings: value.owners.clone(),
    })
    .expect("spawn body snapshot");
    sign_fixture(value)
}

pub(super) async fn runtime_fixture(body_generation: u64, drain_on_build: bool) -> RuntimeFixture {
    let directory = tempfile::tempdir().expect("directory");
    let root = directory.path().canonicalize().expect("root");
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet");
    let registry = FleetRegistry::initialize(fleet.clone()).expect("registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c14").expect("agent");
    let registered = registry
        .register(
            AgentManifest::new(
                agent_id.clone(),
                WorkspaceBinding::new(&workspace, &fleet).expect("binding"),
                ResourceBudget::local_default(),
            )
            .expect("manifest"),
        )
        .expect("register");
    registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect("Starting");
    let identity = crate::AgentdIdentity {
        agent_id: agent_id.clone(),
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
    let state = crate::AgentdState::new(identity.clone(), registry.clone(), 32).expect("state");
    state
        .attach_cognitive_store(Arc::new(
            CognitiveStore::open(&identity.layout)
                .await
                .expect("cognitive owner"),
        ))
        .expect("attach cognitive owner");
    state
        .mark_runtime_prerequisites_ready()
        .expect("prerequisites");
    // This owner-boundary test seeds the readiness event; it does not claim to
    // start an App Server or provider. Those have separate process tests.
    state.mark_app_server_ready().expect("readiness event");
    registry
        .compare_and_transition(&agent_id, 1, AgentLifecycle::Running)
        .expect("Running");
    let current_generation = state
        .current_generation()
        .expect("actual lifecycle generation");
    assert_eq!(current_generation, 2);

    let key = SigningKey::from_bytes(&[83; 32]);
    let trust_path = identity.home_root.join("objective-trust.json");
    private_json(
        &trust_path,
        &serde_json::json!({
            "schema_version": 1, "agent_id": agent_id.as_str(), "issuer_id": "issuer.objective",
            "key_epoch": 1, "public_key_hex": key.verifying_key().as_bytes().iter().map(|b| format!("{b:02x}")).collect::<String>(),
            "revoked": false, "thread_ids": ["thread.objective"]
        }),
    );
    // Bootstrap only this fresh fixture's real replay owner. The independently
    // retained witness must name its exact frontier, even when no messages exist.
    let home = AbsolutePathBuf::from_absolute_path(&identity.home_root).expect("evidence home");
    let evidence = HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(home))
        .await
        .expect("original evidence owner");
    assert_eq!(
        evidence
            .authbus_restore_checkpoint()
            .await
            .expect("initial checkpoint"),
        None
    );
    let frontier = evidence
        .authbus_replay_frontier_digest()
        .await
        .expect("actual replay frontier");
    drop(evidence);
    let checkpoint = root.join("replay-checkpoint.json");
    let mut checkpoint_file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&checkpoint)
        .expect("new independent checkpoint");
    serde_json::to_writer(
        &mut checkpoint_file,
        &serde_json::json!({
            "schema_version": 1, "agent_id": agent_id.as_str(), "generation": 1,
            "digest": frontier.to_string()
        }),
    )
    .expect("checkpoint JSON");
    checkpoint_file.sync_all().expect("durable checkpoint");
    drop(checkpoint_file);
    File::open(&root)
        .expect("checkpoint directory")
        .sync_all()
        .expect("durable checkpoint directory");
    let ingress =
        crate::authbus_ingress::TextIngress::open(&identity, trust_path.clone(), checkpoint)
            .await
            .expect("real AuthBus trust owner");
    assert_eq!(
        ingress
            .evidence
            .authbus_restore_checkpoint()
            .await
            .expect("admitted checkpoint"),
        Some(ReplayCheckpoint {
            generation: 1,
            digest: frontier
        })
    );
    assert!(state.authbus.set(Arc::new(ingress)).is_ok());

    let now = wall_clock_ms().expect("clock");
    let (value, trust) = fresh_inputs(body_generation, now);
    let claims = SignedMessageClaims {
        issuer_id: id("issuer.objective"),
        key_epoch: generation(1),
        message_id: id("message.canonical"),
        subject_id: id(agent_id.as_str()),
        scope_digest: crate::objective_runtime::objective_scope(&identity),
        payload_digest: value.inputs.objective_envelope.intent_digest,
        sequence: 1,
        expires_at_ms: now + 120_000,
    };
    let path = root.join("run-start.journal");
    let mut journal = DurableRunStartJournal::create(
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&path)
            .expect("journal file"),
        digest("original-run-start-owner"),
        16,
    )
    .expect("journal");
    let published = compile_and_publish_objective_run_v1(
        &value.inputs.objective_envelope,
        &value.inputs.objective_profile,
        &value.inputs.objective_context,
        ObjectiveRunBindingsV1 {
            authentication: RunStartAuthenticationV1 {
                issuer_id: claims.issuer_id.clone(),
                key_epoch: claims.key_epoch.get(),
                message_id: claims.message_id.clone(),
                sequence: claims.sequence,
                expires_at_ms: claims.expires_at_ms,
                scope_digest: claims.scope_digest,
                signed_body_digest: claims.payload_digest,
                signature: key.sign(&claims.signing_bytes()).to_bytes(),
            },
            run_id: value.request.run_id.clone(),
            runtime_body_digest: digest("original-runtime-body"),
            preference_state_digest: digest("original-preference"),
            model_tuple_digest: digest("original-model"),
            prompt_registry_digest: digest("original-prompt-registry"),
            artifact_set_digest: digest("original-artifact-set"),
            authority_epoch: value.request.snapshot.authority_epoch(),
            generation: current_generation,
            fence_digest: crate::state::objective_run_fence(&identity, current_generation)
                .parse()
                .expect("fence"),
            expected_run_start_head: Digest32::ZERO,
        },
        &mut journal,
    )
    .expect("real objective publication");
    let before = journal
        .get(&value.request.run_id)
        .expect("read")
        .expect("published")
        .clone();
    drop(journal);
    let journal = DurableRunStartJournal::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .expect("reopen file"),
        digest("original-run-start-owner"),
        16,
        RunStartRecovery::Acknowledged(RunStartAnchor {
            sequence: published.publication.sequence,
            chain_digest: published.publication.chain_digest,
        }),
    )
    .expect("recover original publication");
    let record = journal
        .get(&value.request.run_id)
        .expect("recovered read")
        .expect("record")
        .clone();
    assert_eq!(record, before);

    let authority = root.join("canonical-authority.json");
    write_authority_file(
        &authority,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(authority, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("signed evaluator trust");
    let provider = Arc::new(InvocationProvider {
        original: record.clone(),
        invocation: Mutex::new(Some(crate::AgentdIntelligenceInvocationV1 {
            request: value.request,
            inputs: value.inputs,
        })),
        calls: AtomicUsize::new(0),
        drain_on_build: drain_on_build.then_some(registry),
    });
    assert!(state.intelligence_product.set(Arc::new(runner)).is_ok());
    assert!(state.intelligence_invocation.set(provider.clone()).is_ok());
    RuntimeFixture {
        _directory: directory,
        state,
        record,
        journal,
        provider,
        trust_path,
    }
}

pub(super) async fn run_state(
    fixture: &RuntimeFixture,
) -> Option<crate::AgentRunReconciliationState> {
    let response = fixture
        .state
        .response(
            1,
            1,
            crate::AgentdMethod::RunReconciliationState {
                run_id: fixture.record.snapshot.run_id.to_string(),
            },
        )
        .await
        .expect("owner read");
    let crate::AgentdPayload::RunReconciliationState { run } = response.payload else {
        panic!("run response")
    };
    run
}
