//! Real owner composition through loopback HTTP. Only the remote provider and
//! independent authority issuer are fixtures. Full daemon startup/runtime-host
//! health probing is deliberately not represented by these model-only tests.

use std::collections::BTreeSet;
use std::fs;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_store::CognitiveRecoveryRequirement;
use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveRuntime;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_native_agent::Limits;
use codex_hepta_native_agent::ToolCall;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::StableId;
use codex_history::RolloutItem;
use codex_http_client::OutboundProxyPolicy;
use codex_protocol::ThreadId;
use codex_protocol::items::TurnItem;
use codex_protocol::items::UserMessageItem;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::ItemCompletedEvent;
use codex_protocol::protocol::ThreadHistoryMode;
use codex_protocol::protocol::ThreadMemoryMode;
use codex_protocol::turn_input::TurnInput;
use codex_protocol::user_input::UserInput;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_thread_store::LoadThreadHistoryParams;
use codex_thread_store::LocalQueueStore;
use codex_thread_store::LocalThreadStore;
use codex_thread_store::LocalThreadStoreConfig;
use codex_thread_store::NativeCheckpointLoad;
use codex_thread_store::NativeCheckpointOpenMode;
use codex_thread_store::QueueStore;
use codex_thread_store::QueuedClientBindingFinalizeMode;
use codex_thread_store::QueuedClientBindingFinalizeOutcome;
use codex_thread_store::QueuedClientBindingReserveOutcome;
use codex_thread_store::ResumeThreadParams;
use codex_thread_store::StoredModelContext;
use codex_thread_store::ThreadPersistenceMetadata;
use codex_thread_store::ThreadStore;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use hepta_runtime::mcp::runtime::jobs::ProcessStartParams;
use pretty_assertions::assert_eq;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

use super::recovery::ReadOriginalOnly;
use super::*;
use crate::AgentdConfig;
use crate::AgentdFinalUseGrantProvider;
use crate::native_turn_checkpoint::NativeQueueBindingV1;

struct NoToolCompiler;

impl NativeToolCompiler for NoToolCompiler {
    fn compile(&self, _call: &ToolCall) -> Result<ProcessStartParams> {
        anyhow::bail!("model-only integration must not admit a tool")
    }
}

struct FixtureIssuer {
    key: SigningKey,
    state: std::sync::Weak<AgentdState>,
    grants: AtomicUsize,
    cancel_at_grant: AtomicBool,
    before_grant_return:
        std::sync::Mutex<Option<Box<dyn FnOnce() -> std::result::Result<(), AgentdError> + Send>>>,
}

impl AgentdFinalUseGrantProvider for FixtureIssuer {
    fn signed_grant<'a>(
        &'a self,
        binding: &'a FinalUseBinding,
    ) -> crate::AgentdFinalUseGrantFuture<'a> {
        Box::pin(async move {
            let index = self.grants.fetch_add(1, Ordering::SeqCst);
            // This is the real original daemon's cancellation/drain operation,
            // after admission/checkpoint and before the target's physical gate.
            if self.cancel_at_grant.swap(false, Ordering::SeqCst) {
                self.state
                    .upgrade()
                    .ok_or_else(|| {
                        AgentdError::GenerationFenced("original fixture daemon stopped".to_owned())
                    })?
                    .mark_draining()?;
            }
            let id = format!("fixture-native-grant:{index}");
            let now = crate::authbus_ingress::now_ms()?;
            let grant = FinalUseGrant {
                schema_version: 1,
                signer_id: "native-test-issuer".to_owned(),
                authority_epoch: 17,
                grant_id: id.clone(),
                nonce: Sha256::digest(id.as_bytes()).into(),
                binding: binding.clone(),
                not_before_unix_ms: now.saturating_sub(1000),
                expires_at_unix_ms: now + 30_000,
            };
            let signature = self
                .key
                .sign(
                    &grant
                        .signing_bytes()
                        .map_err(|error| AgentdError::Invalid(error.to_string()))?,
                )
                .to_bytes()
                .to_vec();
            let callback = self
                .before_grant_return
                .lock()
                .map_err(|error| AgentdError::Invalid(error.to_string()))?
                .take();
            if let Some(callback) = callback {
                callback()?;
            }
            Ok(SignedFinalUseGrant { grant, signature })
        })
    }
}

struct Fixture {
    native: AgentdNativeHost,
    state: Arc<AgentdState>,
    writer: Arc<ProductionDurableWriter>,
    live: LiveThread,
    thread_store: Arc<LocalThreadStore>,
    queue: Arc<LocalQueueStore>,
    issuer: Arc<FixtureIssuer>,
    final_use: FinalUseAuthority,
    anchor: NativeTurnAnchorV1,
    run: RunReceipt,
    initial: TurnState,
    payload: String,
    scope: NativeTurnScope,
    _config: AgentdConfig,
    _temp: tempfile::TempDir,
}

// Shared original-owner provisioning only. Both direct model fixtures and the
// embedded daemon regression recover the same writer through this exact-cut
// factory; readiness, Core, QueueStore and ThreadStore belong to their callers.
async fn original_writer_fixture(
    agent_id: AgentId,
) -> Result<(
    tempfile::TempDir,
    AgentdConfig,
    FleetRegistry,
    AgentdProductionWriterHost,
)> {
    let retain = std::env::var("HEPTA_NATIVE_ACCEPTANCE_RETAIN_OWNERS").as_deref() == Ok("1");
    let mut temp = if retain {
        ensure!(
            cfg!(target_os = "linux")
                && std::env::var("HEPTA_NATIVE_REAL_PROCESS_CHILD").as_deref() == Ok("1")
                && std::path::Path::new("/acceptance/owners").is_dir(),
            "original owner retention requires the explicitly isolated acceptance child"
        );
        tempfile::Builder::new()
            .prefix("owner-")
            .tempdir_in("/acceptance/owners")?
    } else {
        tempfile::tempdir()?
    };
    temp.disable_cleanup(retain);
    let root = temp.path().canonicalize()?;
    #[cfg(unix)]
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
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
    let config = AgentdConfig::load(
        fleet_path,
        agent_id.clone(),
        /*spawn_generation*/ 1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )?;
    let store = DurableCognitiveStore::open(&record.layout).await?;
    let exact_cut = store.recovery_anchor().await?;
    drop(store);
    let grant_digest = Sha256Digest::for_bytes(b"native integration original writer authority");
    let authority = ProductionAuthorityLease::from_verified_parts(
        agent_id,
        grant_digest.clone(),
        /*authority_epoch*/ 9,
        /*owner_epoch*/ 4,
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() + 300,
        ProductionAuthorityToken::from_verified_bytes(b"fixture native writer token".to_vec())?,
    )?;
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |lease: &ProductionAuthorityLease, expected: &AgentId| {
            if &lease.agent_id == expected && lease.grant_digest == grant_digest {
                Ok(())
            } else {
                Err("fixture rejected different original writer".to_owned())
            }
        },
    );
    let recovered = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&exact_cut),
        authority,
        verifier,
        "lease:native-host-integration",
        /*lease_generation*/ 1,
    )
    .await?;
    if retain {
        let identity = config.identity();
        let original = json!({ "schema":"hepta.native.acceptance-original-owner.v1",
            "agent_id":identity.agent_id.as_str(), "spawn_generation":identity.spawn_generation,
            "root":root, "home_root":identity.home_root, "workspace":identity.workspace,
            "writer_lease":recovered.writer().lease_id(),
            "scope":"original fixture owners retained in place; no live-store export" });
        fs::write(
            root.join("OWNER.json"),
            serde_json::to_vec_pretty(&original)?,
        )?;
    }
    Ok((temp, config, registry, recovered))
}

impl Fixture {
    async fn new(endpoint: String) -> Result<Self> {
        Self::new_with_agent(
            endpoint,
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c81")?,
        )
        .await
    }

    async fn new_with_agent(endpoint: String, agent_id: AgentId) -> Result<Self> {
        Self::new_with_agent_model_bounds(endpoint, agent_id, 8192, 16384).await
    }

    async fn new_with_agent_model_bounds(
        endpoint: String,
        agent_id: AgentId,
        max_request_bytes: usize,
        max_stream_bytes: usize,
    ) -> Result<Self> {
        let (temp, config, registry, recovered) = original_writer_fixture(agent_id).await?;
        let root = temp.path().canonicalize()?;
        let state = Arc::new(AgentdState::new(
            config.identity().clone(),
            registry.clone(),
            /*event_capacity*/ 32,
        )?);
        let writer = recovered.writer();
        let CognitiveRuntime::Available(store) = recovered.cognitive_runtime() else {
            anyhow::bail!("exact-cut recovered cognitive owner unavailable");
        };
        state.attach_cognitive_store(store)?;
        state.mark_runtime_prerequisites_ready()?;
        registry.compare_and_transition(
            &state.identity().agent_id,
            /*expected_generation*/ 1,
            AgentLifecycle::Running,
        )?;
        state.refresh_generation()?;
        state.mark_app_server_ready()?;

        let gate = Arc::new(NativeEntryGate {
            state: Arc::downgrade(&state),
            policy_generation: 7,
        });
        let model = Arc::new(NativeResponsesTarget::new(
            NativeResponsesTargetConfig {
                responses_url: endpoint,
                bearer: None,
                idle_timeout: Duration::from_secs(3),
                max_request_bytes,
                max_stream_bytes,
            },
            &HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
        )?);
        let runtime = Arc::new(NativeRuntimeTarget::new(
            "native-runtime-integration".to_owned(),
            /*max_output_bytes*/ 4096,
        )?);
        let directory = root.join("final-use");
        fs::create_dir(&directory)?;
        #[cfg(unix)]
        fs::set_permissions(&directory, fs::Permissions::from_mode(0o700))?;
        let issuer = Arc::new(FixtureIssuer {
            key: SigningKey::from_bytes(&[61; 32]),
            state: Arc::downgrade(&state),
            grants: AtomicUsize::new(0),
            cancel_at_grant: AtomicBool::new(false),
            before_grant_return: std::sync::Mutex::new(None),
        });
        let final_use = FinalUseAuthority::open_state_dir(
            &directory,
            "native-test-issuer".to_owned(),
            issuer.key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 17,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )?;
        let host = Arc::new(
            recovered
                .attach_target(final_use.clone(), model.clone(), issuer.clone())?
                .attach_additional_target(final_use.clone(), runtime.clone())?,
        );
        let native = AgentdNativeHost {
            gate,
            host,
            model,
            runtime,
            compiler: Arc::new(NoToolCompiler),
        };

        let thread_id = ThreadId::new();
        let home = config.identity().layout.home_root();
        let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(home.join("state"))?);
        let state_db = StateRuntime::init(sqlite.clone(), "native-test".to_owned()).await?;
        let thread_store = Arc::new(LocalThreadStore::new(
            LocalThreadStoreConfig {
                codex_home: home.to_path_buf(),
                sqlite,
                default_model_provider_id: "native-test".to_owned(),
            },
            Some(state_db.clone()),
        ));
        let sessions = home.join("sessions/2026/10/28");
        fs::create_dir_all(&sessions)?;
        let rollout = sessions.join(format!("rollout-2026-10-28T00-00-00-{thread_id}.jsonl"));
        let metadata = json!({"ordinal":0,"timestamp":"2026-10-28T00:00:00Z","type":"session_meta","payload":{
            "session_id":thread_id,"id":thread_id,"timestamp":"2026-10-28T00:00:00Z","cwd":home,
            "originator":"native-integration","cli_version":"test","source":"cli","model_provider":"native-test","history_mode":"paginated"}});
        fs::write(&rollout, format!("{metadata}\n"))?;
        let history = thread_store
            .load_latest_model_context(LoadThreadHistoryParams {
                thread_id,
                include_archived: false,
            })
            .await?;
        let live = LiveThread::resume(
            thread_store.clone(),
            ThreadHistoryMode::Paginated,
            ResumeThreadParams {
                thread_id,
                rollout_path: Some(rollout),
                history: Some(history.items.into()),
                include_archived: false,
                metadata: ThreadPersistenceMetadata {
                    cwd: Some(home.to_path_buf()),
                    model_provider: "native-test".to_owned(),
                    memory_mode: ThreadMemoryMode::Disabled,
                },
            },
        )
        .await?;
        let mut anchor: NativeTurnAnchorV1 = serde_json::from_value(json!({
            "checkpoint":{"thread_id":thread_id,"turn_id":"turn:native-host","operation_id":"run.native.host","generation":2,"lease_id":writer.lease_id()},
            "recovery":{"turn_id":"turn:native-host","generation":1,"fingerprint_sha256":Digest32::of_bytes(b"native test input").to_string(),
                "history_boundary":{"item_count":1,"prefix_sha256":Digest32::of_bytes(b"native fixture context").to_string()},
                "replay":{"history_boundary":{"item_count":1,"prefix_sha256":Digest32::of_bytes(b"native fixture context").to_string()},
                    "turn_context_sha256":Digest32::of_bytes(b"native fixture context").to_string(),"start":{},"environments":[]}},"queue":null
        }))?;
        let initial = TurnState::new(anchor.turn_binding()?, "native test input".to_owned());
        let context_digest = Digest32::of_bytes(&serde_json::to_vec(&initial.context)?).to_string();
        // These recovery values are original fixture history-owner inputs,
        // never generated by the native loop or treated as authority grants.
        anchor.recovery.fingerprint_sha256 = context_digest.clone();
        anchor
            .recovery
            .history_boundary
            .as_mut()
            .context("boundary")?
            .prefix_sha256 = context_digest.clone();
        let replay = anchor.recovery.replay.as_mut().context("replay")?;
        replay.history_boundary = anchor
            .recovery
            .history_boundary
            .clone()
            .context("boundary")?;
        replay.turn_context_sha256 = context_digest.clone();
        let queue = Arc::new(LocalQueueStore::new(state_db));
        let content = vec![UserInput::Text {
            text: "native test input".to_owned(),
            text_elements: Vec::new(),
        }];
        let payload = serde_json::to_string(&TurnInput::UserInput {
            content: content.clone(),
            client_id: Some("client:native-host".to_owned()),
        })?;
        let payload_sha256 = user_input_payload_sha256(&content)?;
        let QueuedClientBindingReserveOutcome::Reserved(lease) = queue
            .reserve_client_binding(
                thread_id,
                "client:native-host".to_owned(),
                payload_sha256.clone(),
                payload.clone(),
            )
            .await?
        else {
            anyhow::bail!("original queue input already exists");
        };
        let QueuedClientBindingFinalizeOutcome::Queued { record: queued, .. } = queue
            .finalize_client_binding(
                thread_id,
                "client:native-host".to_owned(),
                payload_sha256.clone(),
                payload.clone(),
                lease,
                QueuedClientBindingFinalizeMode::AllowIfAbsent,
                /*observed_turn_id*/ None,
            )
            .await?
        else {
            anyhow::bail!("original input not queued");
        };
        anchor.queue = Some(NativeQueueBindingV1 {
            client_id: "client:native-host".to_owned(),
            queued_item_id: queued.id,
            payload_sha256,
        });
        live.append_items(&[
            RolloutItem::EventMsg(EventMsg::ItemCompleted(ItemCompletedEvent {
                thread_id,
                turn_id: anchor.checkpoint.turn_id.clone(),
                item: TurnItem::UserMessage(UserMessageItem {
                    id: "input:native-host".to_owned(),
                    client_id: Some("client:native-host".to_owned()),
                    content,
                }),
                started_at_ms: Some(1),
                completed_at_ms: 2,
            })),
            RolloutItem::TurnRecoveryRequestBinding(anchor.recovery.clone()),
        ])
        .await?;
        live.flush().await?;
        let snapshot = crate::AgentRunSnapshot {
            run_id: anchor.checkpoint.operation_id.clone(),
            request_digest: "1".repeat(64),
            objective_digest: "2".repeat(64),
            body_digest: "3".repeat(64),
            artifact_set_digest: "4".repeat(64),
            authority_epoch: 9,
            generation: 2,
            fence_digest: crate::state::objective_run_fence(
                state.identity(),
                /*current_generation*/ 2,
            ),
            deadline_ms: u64::MAX - 1,
        };
        state
            .response(
                /*request_id*/ 1,
                /*spawn_generation*/ 1,
                crate::AgentdMethod::RunStart {
                    snapshot: snapshot.clone(),
                },
            )
            .await?;
        let admitted = state.native_run_receipt(&snapshot.run_id)?;
        state
            .response(
                /*request_id*/ 2,
                /*spawn_generation*/ 1,
                crate::AgentdMethod::RunAttachContext {
                    expected_revision: admitted.revision,
                    attachment: crate::AgentContextAttachment {
                        run_id: snapshot.run_id.clone(),
                        request_digest: snapshot.request_digest,
                        objective_digest: snapshot.objective_digest,
                        body_digest: snapshot.body_digest,
                        artifact_set_digest: snapshot.artifact_set_digest,
                        authority_epoch: snapshot.authority_epoch,
                        generation: snapshot.generation,
                        fence_digest: snapshot.fence_digest,
                        deadline_ms: snapshot.deadline_ms,
                        context_digest,
                        compilation_receipt_digest: "6".repeat(64),
                    },
                },
            )
            .await?;
        let run = state.native_run_receipt(&snapshot.run_id)?;
        let scope = NativeTurnScope {
            cell_id: StableId::new("cell:native-test")?,
            organ_id: StableId::new("organ:native-test")?,
            final_scope_id: StableId::new("organ:native-test")?,
        };
        Ok(Self {
            native,
            state,
            writer,
            live,
            thread_store,
            queue,
            issuer,
            final_use,
            anchor,
            run,
            initial,
            payload,
            scope,
            _config: config,
            _temp: temp,
        })
    }

    async fn handoff(&self) -> Result<NativeTurnHandoff> {
        let now = now_ms()?;
        let dispatch = NativeQueueDispatch::claim(
            self.queue.clone(),
            self.anchor.checkpoint.thread_id,
            self.anchor.queue.clone().context("original queued input")?,
            "dispatch:native-test".to_owned(),
            now,
            now + 30_000,
        )
        .await?;
        Ok(NativeTurnHandoff {
            live_thread: self.live.clone(),
            anchor: self.anchor.clone(),
            run: self.run.clone(),
            scope: self.scope.clone(),
            initial: self.initial.clone(),
            queue: Some(dispatch),
        })
    }

    async fn history(&self) -> Result<StoredModelContext> {
        // These fixture turns contain no compaction. Production owner identity
        // validation uses the separate complete, bounded canonical scan.
        Ok(self
            .thread_store
            .load_latest_model_context(LoadThreadHistoryParams {
                thread_id: self.anchor.checkpoint.thread_id,
                include_archived: false,
            })
            .await?)
    }

    async fn assert_queue_persisted_once(&self) -> Result<()> {
        let binding = self.anchor.queue.as_ref().context("queue binding")?;
        assert!(
            self.queue
                .list_page(
                    self.anchor.checkpoint.thread_id,
                    /*offset*/ 0,
                    /*limit*/ 16
                )
                .await?
                .is_empty()
        );
        assert_eq!(
            self.queue
                .reserve_client_binding(
                    self.anchor.checkpoint.thread_id,
                    binding.client_id.clone(),
                    binding.payload_sha256.clone(),
                    self.payload.clone()
                )
                .await?,
            QueuedClientBindingReserveOutcome::Persisted {
                turn_id: self.anchor.checkpoint.turn_id.clone()
            }
        );
        let history = self.history().await?;
        let inputs = history.items.iter().filter(|item| matches!(item,
            RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if matches!(&event.item,
                TurnItem::UserMessage(input) if input.client_id.as_deref() == Some("client:native-host")))).count();
        assert_eq!(inputs, 1, "duplicate input must not enter typed history");
        Ok(())
    }
}

fn agent() -> NativeAgent {
    NativeAgent {
        model_name: "native-fixture-model".to_owned(),
        instructions: "Return the fixture result.".to_owned(),
        tools: Vec::new(),
        store_responses: true,
        limits: Limits {
            context_bytes: 8192,
            output_tokens: 64,
            model_calls: 1,
            tool_calls: 1,
            tool_output_bytes: 4096,
            model_timeout: Duration::from_secs(5),
            tool_timeout: Duration::from_secs(2),
            observation_interval: Duration::from_millis(10),
        },
    }
}

async fn provider() -> MockServer {
    let server = MockServer::start().await;
    let output = json!({"type":"message","id":"message-native","role":"assistant","content":[{"type":"output_text","text":"native owner complete"}]});
    let events = [json!({"type":"response.created","response":{"id":"response-native"}}),
        json!({"type":"response.output_item.done","item":output.clone()}),
        json!({"type":"response.completed","response":{"id":"response-native","status":"completed","output":[output],"usage":{"input_tokens":3,"output_tokens":4}}})]
        .into_iter().map(|event| format!("data: {event}\n\n")).collect::<String>();
    Mock::given(method("POST"))
        .and(path("/v1/responses"))
        .respond_with(ResponseTemplate::new(200).set_body_raw(events, "text/event-stream"))
        .mount(&server)
        .await;
    server
}

#[tokio::test]
async fn native_host_completes_same_writer_run_history_and_queue_once() -> Result<()> {
    let server = provider().await;
    let fixture = Fixture::new(format!("{}/v1/responses", server.uri())).await?;
    assert!(Arc::ptr_eq(&fixture.writer, &fixture.native.host.writer()));
    let result = fixture
        .native
        .run_turn(
            &agent(),
            fixture.handoff().await?,
            &CancellationToken::new(),
        )
        .await?;
    assert_eq!(
        result.outcome,
        RunOutcome::Completed("native owner complete".to_owned()),
        "native model state after the original attempt: {:#?}",
        result.state
    );
    assert_eq!(
        (
            result.run.run_id.as_str(),
            result.run.phase,
            result.run.terminal_observed
        ),
        (fixture.run.run_id.as_str(), RunPhase::Succeeded, true)
    );
    let captured = server.received_requests().await.context("HTTP capture")?;
    assert_eq!(captured.len(), 1);
    let operation = captured[0]
        .headers
        .get("idempotency-key")
        .context("original idempotency header")?
        .to_str()?;
    let request = fixture
        .writer
        .resolve_operation_request(operation, fixture.native.model.destination_id())
        .await?;
    assert_eq!(
        (
            request.operation_subject_id.as_str(),
            request.payload_json.as_bytes()
        ),
        (
            fixture.writer.owner_agent_id().as_str(),
            captured[0].body.as_slice()
        )
    );
    assert_eq!(
        fixture.writer.status(operation).await?,
        LocalOutcomeState::Committed
    );
    assert!(
        fixture
            .writer
            .resolve_queued_operation(operation, fixture.native.model.destination_id())
            .await
            .is_err()
    );
    assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 1);
    fixture.assert_queue_persisted_once().await?;
    let admission = fixture.native.admission(
        fixture.anchor.checkpoint.clone(),
        fixture.scope.clone(),
        &result.run,
    )?;
    let session = fixture
        .live
        .open_native_checkpoint(
            fixture.anchor.checkpoint.clone(),
            NativeCheckpointOpenMode::Recover,
            admission,
        )
        .await?;
    let NativeCheckpointLoad::Present(checkpoint) =
        fixture.live.load_native_checkpoint(&session).await?
    else {
        anyhow::bail!("native checkpoint missing");
    };
    let (_, stored) = crate::native_turn_checkpoint::decode(
        &checkpoint.state.payload,
        &fixture.anchor.checkpoint,
    )?;
    assert_eq!(
        (
            stored.final_answer,
            stored.provider_response_id,
            stored.model_calls
        ),
        (
            Some("native owner complete".to_owned()),
            Some("response-native".to_owned()),
            1
        )
    );
    let duplicate = NativeTurnHandoff {
        live_thread: fixture.live.clone(),
        anchor: fixture.anchor.clone(),
        run: fixture.run.clone(),
        scope: fixture.scope.clone(),
        initial: fixture.initial.clone(),
        queue: None,
    };
    assert!(
        fixture
            .native
            .run_turn(&agent(), duplicate, &CancellationToken::new())
            .await
            .is_err()
    );
    assert!(
        fixture.handoff().await.is_err(),
        "completed original queue row cannot be claimed again"
    );
    fixture.assert_queue_persisted_once().await?;
    assert_eq!(
        server
            .received_requests()
            .await
            .context("HTTP capture")?
            .len(),
        1
    );
    assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 1);
    fixture.live.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn original_owner_cancellation_after_checkpoint_opens_no_http_request() -> Result<()> {
    let server = provider().await;
    let fixture = Fixture::new(format!("{}/v1/responses", server.uri())).await?;
    fixture.issuer.cancel_at_grant.store(true, Ordering::SeqCst);
    let result = fixture
        .native
        .run_turn(
            &agent(),
            fixture.handoff().await?,
            &CancellationToken::new(),
        )
        .await?;
    assert_eq!(result.outcome, RunOutcome::PendingModel);
    assert_eq!(
        (result.run.phase, result.run.terminal_observed),
        (RunPhase::Indeterminate, false)
    );
    let pending = result
        .state
        .pending_model
        .as_ref()
        .context("original request must remain pending")?;
    tokio::time::timeout(Duration::from_secs(3), async {
        loop {
            if fixture.writer.status(&pending.operation_id).await?
                == LocalOutcomeState::Indeterminate
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        Ok::<_, anyhow::Error>(())
    })
    .await??;
    let original = fixture
        .writer
        .resolve_operation_request(&pending.operation_id, fixture.native.model.destination_id())
        .await?;
    assert_eq!(original.payload_json.as_bytes(), pending.body.as_slice());
    assert!(
        fixture
            .state
            .require_native_effect(&fixture.run.run_id)
            .is_err()
    );
    assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 1);
    assert!(
        server
            .received_requests()
            .await
            .context("HTTP capture")?
            .is_empty()
    );
    fixture.assert_queue_persisted_once().await?;
    assert!(
        fixture
            .native
            .host
            .begin_native_effect(fixture.native.model.destination_id(), &pending.operation_id)
            .await
            .is_err()
    );
    assert!(
        server
            .received_requests()
            .await
            .context("HTTP capture")?
            .is_empty()
    );
    fixture.live.shutdown().await?;
    Ok(())
}

#[path = "native_host_recovery_tests.rs"]
mod recovery_tests;

#[path = "native_host_writer_reopen_tests.rs"]
mod writer_reopen_tests;

#[path = "native_admission_tests.rs"]
mod admission_tests;

#[cfg(target_os = "linux")]
#[path = "native_runtime_acceptance_tests.rs"]
mod runtime_acceptance_tests;

#[path = "native_hosted_turn_tests.rs"]
mod hosted_turn_tests;

#[path = "objective_native_integration_tests.rs"]
mod objective_native_tests;

#[path = "native_shared_authority_tests.rs"]
mod shared_authority_tests;

#[path = "native_bootstrap_tests.rs"]
mod bootstrap_tests;
