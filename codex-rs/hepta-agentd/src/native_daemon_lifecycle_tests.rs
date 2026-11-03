//! Actual typed product startup into run(config), including native attachment, runtime health,
//! App Server, control UDS, original QueueStore and original ThreadStore.
//! Independent authority/model providers and SSH transport are controlled
//! fixtures. This does not qualify ordinary CLI bootstrap or an OS restart.

use pretty_assertions::assert_eq;

use super::*;
use app_test_support::MockResponsesConfig;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadHistoryMode as ApiHistoryMode;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadQueueListParams;
use codex_app_server_protocol::ThreadQueueListResponse;
use codex_app_server_protocol::ThreadQueueReconcileOutcome;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_app_server_protocol::ThreadQueueReconcileResponse;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput as ApiInput;
use codex_core::hosted_turn::HostedTurnProvenance;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveSourceOutboxTarget;
use codex_history::RolloutLine;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::timeout;

use crate::AgentdCanonicalNativeCompositionV1;
use crate::AgentdClient;
use crate::AgentdNativeProductLoadFuture;
use crate::AgentdNativeProductLoaderV1;
use crate::AgentdPayload;
use crate::AgentdProductionOperationRuntimeConfig;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::ObjectiveStartOutcome;
use crate::native_host::tests::runtime_acceptance_tests::daemon_environment;

const TEXT: &str = "Return the native owner result.";
const WAIT: Duration = Duration::from_secs(30);

// The product entry receives the existing real typed owners. Their independent
// authority inputs remain controlled by this fixture; no request creates them.
struct ExistingProductLoader {
    identity: crate::AgentdIdentity,
    composition: std::sync::Mutex<Option<AgentdCanonicalNativeCompositionV1>>,
    calls: Arc<AtomicUsize>,
    drops: Arc<AtomicUsize>,
}

impl AgentdNativeProductLoaderV1 for ExistingProductLoader {
    fn load<'a>(
        &'a self,
        identity: &'a crate::AgentdIdentity,
    ) -> AgentdNativeProductLoadFuture<'a> {
        Box::pin(async move {
            self.calls.fetch_add(1, Ordering::SeqCst);
            if identity != &self.identity {
                return Err(AgentdError::Invalid(
                    "product loader received another original daemon".to_owned(),
                ));
            }
            self.composition
                .lock()
                .map_err(|_| AgentdError::Invalid("product loader mutex poisoned".to_owned()))?
                .take()
                .ok_or_else(|| AgentdError::Invalid("product loader was invoked twice".to_owned()))
        })
    }
}

impl Drop for ExistingProductLoader {
    fn drop(&mut self) {
        self.drops.fetch_add(1, Ordering::SeqCst);
    }
}

struct UnavailableProductLoader(Arc<AtomicUsize>);

impl AgentdNativeProductLoaderV1 for UnavailableProductLoader {
    fn load<'a>(
        &'a self,
        _identity: &'a crate::AgentdIdentity,
    ) -> AgentdNativeProductLoadFuture<'a> {
        Box::pin(async move {
            self.0.fetch_add(1, Ordering::SeqCst);
            Err(AgentdError::Invalid(
                "original product owners are unavailable".to_owned(),
            ))
        })
    }
}

fn request(
    identity: &crate::AgentdIdentity,
    owners: &CanonicalObjectiveTestOwners,
    key: &SigningKey,
    thread: ThreadId,
    sequence: u64,
) -> Result<AuthBusObjectiveIngress> {
    let digest = |label: &str| Digest32::of_bytes(label.as_bytes()).to_string();
    let mut request = AuthBusObjectiveIngress {
        issuer_id: "adapter.console".to_owned(),
        key_epoch: 1,
        message_id: format!("message.daemon-native.{sequence}"),
        sequence,
        expires_at_ms: now_ms()? + 60_000,
        signature_hex: String::new(),
        body: AuthBusObjectiveBody {
            spawn_generation: identity.spawn_generation,
            run_id: format!("run.daemon-native.{sequence}"),
            objective_revision: 1,
            source_envelope_json: owners.source_json()?,
            runtime_body_digest: digest("objective runtime body"),
            preference_state_digest: digest("objective preferences"),
            model_tuple_digest: digest("objective model tuple"),
            prompt_registry_digest: digest("objective prompt registry"),
            artifact_set_digest: digest("objective artifacts"),
            authority_epoch: 11,
            queued_input: Some(ObjectiveQueuedInputV1 {
                thread_id: thread.to_string(),
                text: TEXT.to_owned(),
            }),
        },
    };
    sign_objective(identity, key, &mut request)?;
    Ok(request)
}

async fn posts(server: &MockServer) -> Result<Vec<wiremock::Request>> {
    Ok(server
        .received_requests()
        .await
        .context("controlled provider capture")?
        .into_iter()
        .filter(|request| {
            request.method.as_str() == "POST" && request.url.path() == "/v1/responses"
        })
        .collect())
}

fn id(next: &mut i64) -> RequestId {
    let current = *next;
    *next += 1;
    RequestId::Integer(current)
}

async fn completed(
    client: &RemoteAppServerClient,
    next: &mut i64,
    thread: &str,
) -> Result<ThreadReadResponse> {
    timeout(WAIT, async {
        loop {
            let read: ThreadReadResponse = client
                .request_typed(ClientRequest::ThreadRead {
                    request_id: id(next),
                    params: ThreadReadParams {
                        thread_id: thread.to_owned(),
                        include_turns: true,
                    },
                })
                .await?;
            ensure!(
                read.thread.turns.len() <= 1,
                "original Objective created multiple turns"
            );
            if read
                .thread
                .turns
                .first()
                .is_some_and(|turn| turn.status == TurnStatus::Completed)
            {
                return Ok::<_, anyhow::Error>(read);
            }
            if let Some(turn) = read.thread.turns.first() {
                ensure!(
                    !matches!(turn.status, TurnStatus::Failed | TurnStatus::Interrupted),
                    "embedded native turn did not complete: {turn:?}"
                );
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .context("original daemon turn did not complete")?
}

// Use the existing bounded control wire protocol. AgentdClient currently has
// no drain convenience method; this sends its original AgentdRequest::drain.
async fn drain(
    identity: &crate::AgentdIdentity,
    request_id: u64,
) -> Result<codex_hepta_agent_protocol::DrainSnapshot> {
    timeout(Duration::from_secs(3), async {
        let mut stream = UnixStream::connect(&identity.control_socket).await?;
        let request = AgentdRequest::drain(request_id, identity.spawn_generation);
        let mut bytes = serde_json::to_vec(&request)?;
        bytes.push(b'\n');
        ensure!(
            bytes.len() as u64 <= crate::MAX_CONTROL_FRAME_BYTES,
            "drain request exceeds original bound"
        );
        stream.write_all(&bytes).await?;
        let mut reader = BufReader::new(stream).take(crate::MAX_CONTROL_FRAME_BYTES + 1);
        let mut bytes = Vec::new();
        let count = reader.read_until(b'\n', &mut bytes).await?;
        ensure!(
            count > 0 && count as u64 <= crate::MAX_CONTROL_FRAME_BYTES && bytes.ends_with(b"\n"),
            "original drain returned an invalid frame"
        );
        let response: AgentdResponse = serde_json::from_slice(&bytes)?;
        ensure!(
            response.schema_version == crate::AGENTD_CONTROL_SCHEMA_VERSION
                && response.request_id == request_id
                && response.agent_id == identity.agent_id
                && response.spawn_generation == identity.spawn_generation
                && response.current_generation == 3,
            "original drain response changed its Fleet/daemon identity"
        );
        match response.payload {
            AgentdPayload::Drain(value) => Ok(value),
            payload => anyhow::bail!("original control rejected drain: {payload:?}"),
        }
    })
    .await
    .context("original control drain timeout")?
}

async fn persisted_provenance(
    path: &Path,
    turn: &str,
    client: &str,
) -> Result<HostedTurnProvenance> {
    timeout(Duration::from_secs(5), async {
        loop {
            let bytes = tokio::fs::read(path).await?;
            ensure!(bytes.len() <= 1024 * 1024, "single-turn fixture history exceeds its read bound");
            let items = std::str::from_utf8(&bytes)?.lines()
                .map(|line| serde_json::from_str::<RolloutLine>(line).map(|line| line.item))
                .collect::<serde_json::Result<Vec<_>>>()?;
            let terminal = items.iter().filter(|item| matches!(item,
                RolloutItem::EventMsg(EventMsg::TurnComplete(event)) if event.turn_id == turn)).count();
            ensure!(terminal <= 1, "original turn has duplicate completion");
            if terminal == 0 { tokio::time::sleep(Duration::from_millis(20)).await; continue; }
            ensure!(items.iter().filter(|item| matches!(item,
                RolloutItem::EventMsg(EventMsg::TurnStarted(_)))).count() == 1, "original history has another turn");
            ensure!(!items.iter().any(|item| matches!(item, RolloutItem::EventMsg(EventMsg::TurnAborted(_)))),
                "successful daemon turn contains an abort");
            let typed = items.iter().filter(|item| matches!(item,
                RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if event.turn_id == turn
                    && matches!(&event.item, TurnItem::UserMessage(message)
                        if message.client_id.as_deref() == Some(client)
                            && message.content == vec![UserInput::Text { text: TEXT.to_owned(), text_elements: Vec::new() }]))).count();
            ensure!(typed == 1, "original client/text was not persisted exactly once");
            let recoveries = items.iter().filter_map(|item| match item {
                RolloutItem::TurnRecoveryRequestBinding(binding) if binding.turn_id == turn => Some(binding),
                _ => None,
            }).collect::<Vec<_>>();
            ensure!(recoveries.len() == 1, "initial daemon turn changed its original recovery binding");
            return HostedTurnProvenance::from_recovery(recoveries[0])?.context("original hosted provenance missing");
        }
    }).await.context("completed original history was not durably flushed")?
}

async fn exercise(root: &Path, arg0: codex_arg0::Arg0DispatchPaths) -> Result<()> {
    let server = provider().await;
    let (temporary, config, registry, recovered) =
        original_writer_fixture(AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c81")?).await?;
    let identity = config.identity().clone();
    // This is the same explicit process-home setup as Agentd main. It is safe
    // only here because the test runs alone in its own namespace subprocess.
    codex_utils_home_dir::set_process_codex_home_override(AbsolutePathBuf::try_from(
        identity.home_root.clone(),
    )?)?;
    MockResponsesConfig::new(&server.uri()).write(&identity.home_root)?;
    fs::set_permissions(&identity.home_root, fs::Permissions::from_mode(0o700))?;
    // Failure to load the original owners is terminal for this startup. It
    // cannot silently launch the ordinary App Server or retry a second loader.
    let failed_loads = Arc::new(AtomicUsize::new(0));
    let error = timeout(
        Duration::from_secs(3),
        crate::run_native_product_with_loader(
            config,
            codex_arg0::Arg0DispatchPaths::default(),
            Box::new(UnavailableProductLoader(failed_loads.clone())),
        ),
    )
    .await
    .context("unavailable product loader did not fail before daemon startup")?
    .err()
    .context("unavailable product owners unexpectedly started a daemon")?;
    ensure!(
        error
            .to_string()
            .contains("original product owners are unavailable"),
        "loader failure was replaced: {error}"
    );
    assert_eq!(failed_loads.load(Ordering::SeqCst), 1);
    assert!(!tokio::fs::try_exists(&identity.control_socket).await?);
    assert!(!tokio::fs::try_exists(&identity.app_server_socket).await?);
    assert!(posts(&server).await?.is_empty());
    // Reopen only this same still-Starting daemon configuration after the
    // failed startup released its original process lock. No owner was replaced.
    let config = crate::AgentdConfig::load(
        identity.fleet_root.clone(),
        identity.agent_id.clone(),
        identity.spawn_generation,
        identity.home_root.clone(),
        identity.run_root.clone(),
        identity.home_root.clone(),
        identity.workspace.clone(),
    )?;
    assert_eq!(config.identity(), &identity);
    let recovered = Arc::new(recovered);
    let writer = recovered.writer();
    let writer_weak = Arc::downgrade(&writer);
    let authority = writer.authority().clone();
    let retained = authority.clone();
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |candidate: &ProductionAuthorityLease, owner: &AgentId| {
            if candidate == &retained && &candidate.agent_id == owner {
                Ok(())
            } else {
                Err("daemon fixture changed original writer authority".to_owned())
            }
        },
    );
    let final_directory = temporary.path().join("final-use");
    fs::create_dir(&final_directory)?;
    fs::set_permissions(&final_directory, fs::Permissions::from_mode(0o700))?;
    let issuer = Arc::new(FixtureIssuer {
        key: SigningKey::from_bytes(&[61; 32]),
        state: std::sync::Weak::new(),
        grants: AtomicUsize::new(0),
        cancel_at_grant: AtomicBool::new(false),
        before_grant_return: std::sync::Mutex::new(None),
    });
    let final_use = FinalUseAuthority::open_state_dir(
        &final_directory,
        "native-test-issuer".to_owned(),
        issuer.key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 17,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    // Reuse the recovered cognitive read side for the existing primary target.
    // Native attach adds its two destinations to this same writer afterwards.
    let cognitive_runtime = recovered.cognitive_runtime();
    let target = Arc::new(
        CognitiveSourceOutboxTarget::new(
            cognitive_runtime
                .available_store()
                .context("original recovered store unavailable")?
                .as_ref()
                .clone(),
            CognitiveAccess::agent_private(identity.agent_id.clone()),
        )
        .map_err(anyhow::Error::msg)?,
    );
    drop(cognitive_runtime);
    let final_use_authority_destination = target.destination_id().to_owned();
    let operations = AgentdProductionOperationRuntimeConfig::new(
        authority,
        verifier,
        writer.lease_id().to_owned(),
        writer.generation(),
        final_use.clone(),
        target,
        issuer.clone(),
        Duration::from_millis(50),
    );
    let (owners, runner) =
        CanonicalObjectiveTestOwners::new(&identity.home_root.join("objective-authority.json"))?;
    let key = SigningKey::from_bytes(&[83; 32]);
    let placeholder = ThreadId::new();
    let trust = identity.home_root.join("objective-trust.json");
    write_trust(&trust, &identity, &key, placeholder, false, 1)?;
    let evidence = HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::try_from(identity.home_root.clone())?,
    ))
    .await?;
    let frontier = evidence.authbus_replay_frontier_digest().await?;
    drop(evidence);
    let checkpoint = temporary.path().join("objective-authbus-checkpoint.json");
    private_file(
        &checkpoint,
        &serde_json::to_vec(&json!({"schema_version":1,
        "agent_id":identity.agent_id.as_str(), "generation":1, "digest":frontier.to_string()}))?,
    )?;
    let profile = identity.home_root.join("objective-profile.json");
    private_file(&profile, &owners.profile_json()?)?;
    let (attached, attached_receive) = tokio::sync::oneshot::channel();
    let expected_writer = Arc::downgrade(&writer);
    let config = config
        .with_authbus_trust_file(trust.clone())
        .with_authbus_checkpoint_file(checkpoint)
        .with_objective_profile_file(profile);
    let composition = AgentdCanonicalNativeCompositionV1::new(
        runner,
        owners.clone(),
        recovered.clone(),
        operations,
        AgentdNativeRuntimeConfig {
            model: NativeResponsesTargetConfig {
                responses_url: format!("{}/v1/responses", server.uri()),
                bearer: None,
                idle_timeout: Duration::from_secs(3),
                max_request_bytes: 8192,
                max_stream_bytes: 16384,
            },
            http: Arc::new(HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault)),
            runtime_destination: "native-runtime-integration".to_owned(),
            required_hosts: vec!["controlled".to_owned()],
            max_tool_output_bytes: 4096,
            policy_generation: Generation::new(7)?,
            final_use_authority_destination,
            compiler: Arc::new(NoToolCompiler),
            hosted_turn: Some(NativeHostedRuntimeConfig::CanonicalObjective {
                agent: Arc::new(agent()),
                scope: NativeTurnScope {
                    cell_id: StableId::new("cell:native-test")?,
                    organ_id: StableId::new("organ:native-test")?,
                    final_scope_id: StableId::new("organ:native-test")?,
                },
            }),
            attach: Box::new(move |native| {
                let original = expected_writer.upgrade().ok_or_else(|| {
                    AgentdError::Invalid("original writer closed during attachment".to_owned())
                })?;
                if !Arc::ptr_eq(&original, &native.host.writer())
                    || native.gate.state()?.automation_admission_ready()?
                {
                    return Err(AgentdError::Invalid(
                        "native attachment replaced its owner or published readiness early"
                            .to_owned(),
                    ));
                }
                attached.send(native).map_err(|_| {
                    AgentdError::Invalid("daemon fixture attachment observer stopped".to_owned())
                })
            }),
        },
    )?;
    let loader_calls = Arc::new(AtomicUsize::new(0));
    let loader_drops = Arc::new(AtomicUsize::new(0));
    let loader = ExistingProductLoader {
        identity: identity.clone(),
        composition: std::sync::Mutex::new(Some(composition)),
        calls: loader_calls.clone(),
        drops: loader_drops.clone(),
    };
    drop(recovered);
    let mut daemon = tokio::spawn(crate::run_native_product_with_loader(
        config,
        arg0,
        Box::new(loader),
    ));
    let native = timeout(WAIT, attached_receive)
        .await
        .context("native attachment was not reached")??;
    assert_eq!(loader_calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        loader_drops.load(Ordering::SeqCst),
        1,
        "startup loader must not become another retained runtime owner"
    );
    let native_weak = Arc::downgrade(&native);
    let state = native.gate.state()?;
    let state_weak = Arc::downgrade(&state);
    let control = AgentdClient::new(
        identity.control_socket.clone(),
        identity.agent_id.clone(),
        1,
    )?;
    let health = timeout(WAIT, async {
        loop {
            ensure!(
                !daemon.is_finished(),
                "daemon exited before its real UDS readiness probe"
            );
            if let Ok(value) = control.health().await
                && value.promotion_ready
            {
                return Ok::<_, anyhow::Error>(value);
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .context("actual startup did not become promotion-ready")??;
    assert!(!health.ready);
    assert_eq!(
        (health.lifecycle, state.current_generation()?),
        (AgentLifecycle::Starting, 1)
    );
    assert!(control.session_ingress().await.is_err());
    let early = request(&identity, &owners, &key, placeholder, 1)?;
    let early_error = control
        .objective_start(early.clone())
        .await
        .err()
        .context("Starting generation admitted Objective")?;
    ensure!(
        early_error.to_string().contains("not ready"),
        "readiness test reached another gate: {early_error}"
    );
    assert!(
        state
            .objective_runtime
            .get()
            .context("original Objective host")?
            .original_record(&early.body.run_id)
            .is_err()
    );
    assert_eq!(
        (
            owners.calls.load(Ordering::SeqCst),
            issuer.grants.load(Ordering::SeqCst),
            final_use.capacity()?.used_nonces
        ),
        (0, 0, 0)
    );
    assert!(posts(&server).await?.is_empty());
    assert!(Arc::ptr_eq(&writer, &native.host.writer()));
    assert!(Arc::ptr_eq(
        &writer,
        &state
            .production_operations
            .get()
            .context("actual runtime operation host")?
            .writer()
    ));
    registry.compare_and_transition(&identity.agent_id, 1, AgentLifecycle::Running)?;
    timeout(WAIT, async {
        loop {
            if control.health().await?.ready {
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        Ok::<_, anyhow::Error>(())
    })
    .await??;
    let ingress = control.session_ingress().await?;
    assert_eq!(ingress.socket_path, identity.app_server_socket);
    let client = RemoteAppServerClient::connect(RemoteAppServerConnectArgs {
        endpoint: RemoteAppServerEndpoint::UnixSocket {
            socket_path: AbsolutePathBuf::try_from(ingress.socket_path)?,
        },
        client_name: "native-embedded-daemon-acceptance".to_owned(),
        client_version: env!("CARGO_PKG_VERSION").to_owned(),
        experimental_api: true,
        mcp_server_openai_form_elicitation: false,
        opt_out_notification_methods: Vec::new(),
        channel_capacity: 64,
    })
    .await?;
    let mut next = 1;
    let started: ThreadStartResponse = client
        .request_typed(ClientRequest::ThreadStart {
            request_id: id(&mut next),
            params: ThreadStartParams {
                cwd: Some(identity.workspace.to_string_lossy().into_owned()),
                ephemeral: Some(false),
                history_mode: Some(ApiHistoryMode::Paginated),
                ..ThreadStartParams::default()
            },
        })
        .await?;
    let thread = ThreadId::from_string(&started.thread.id)?;
    write_trust(&trust, &identity, &key, thread, false, 1)?;
    let signed = request(&identity, &owners, &key, thread, 2)?;
    let ObjectiveStartOutcome::Admitted { receipt } = control
        .objective_start(signed.clone())
        .await
        .context("initial signed Objective control response")?
    else {
        anyhow::bail!("actual signed Objective was not admitted");
    };
    assert!(!receipt.idempotent);
    assert_eq!(receipt.disposition, "canonical_queue_accepted");
    let read = completed(&client, &mut next, &thread.to_string()).await?;
    let turn = read
        .thread
        .turns
        .first()
        .context("original completed turn")?;
    let turn_id = turn.id.clone();
    let original = state
        .objective_runtime
        .get()
        .context("original journal")?
        .original_record(&signed.body.run_id)?;
    let input = state.canonical_queued_input(&original)?;
    assert_eq!(
        turn.items
            .iter()
            .filter_map(|item| match item {
                ThreadItem::UserMessage {
                    client_id, content, ..
                } => Some((client_id.clone(), content.clone())),
                _ => None,
            })
            .collect::<Vec<_>>(),
        vec![(
            Some(input.client_user_message_id.clone()),
            vec![ApiInput::Text {
                text: TEXT.to_owned(),
                text_elements: Vec::new()
            }]
        )]
    );
    assert_eq!(
        turn.items
            .iter()
            .filter_map(|item| match item {
                ThreadItem::AgentMessage { text, .. } => Some(text.as_str()),
                _ => None,
            })
            .collect::<Vec<_>>(),
        vec!["native owner complete"]
    );
    let provenance = persisted_provenance(
        read.thread
            .path
            .as_deref()
            .context("original durable rollout path")?,
        &turn_id,
        &input.client_user_message_id,
    )
    .await?;
    assert_eq!(
        (
            &provenance.queue.client_id,
            &provenance.queue.payload_sha256
        ),
        (&input.client_user_message_id, &input.input_payload_sha256)
    );
    assert!(!provenance.queue.queued_item_id.is_empty());
    for (key, expected) in [
        ("thread_id", thread.to_string()),
        ("turn_id", turn_id.clone()),
        ("run_id", signed.body.run_id.clone()),
        ("lease_id", writer.lease_id().to_owned()),
        ("fleet_generation", "2".to_owned()),
    ] {
        assert_eq!(provenance.correlation.get(key), Some(&expected));
    }
    let queued: ThreadQueueReconcileResponse = client
        .request_typed(ClientRequest::ThreadQueueReconcile {
            request_id: id(&mut next),
            params: ThreadQueueReconcileParams {
                thread_id: thread.to_string(),
                client_user_message_id: input.client_user_message_id.clone(),
                input: vec![ApiInput::Text {
                    text: TEXT.to_owned(),
                    text_elements: Vec::new(),
                }],
                expected_payload_sha256: input.input_payload_sha256.clone(),
                mode: ThreadQueueReconcileMode::ReconcileOnly,
            },
        })
        .await?;
    assert_eq!(
        queued.outcome,
        ThreadQueueReconcileOutcome::Persisted {
            turn_id: turn_id.clone()
        }
    );
    assert_eq!(
        (&queued.client_user_message_id, &queued.payload_sha256),
        (&input.client_user_message_id, &input.input_payload_sha256)
    );
    let queued: ThreadQueueListResponse = client
        .request_typed(ClientRequest::ThreadQueueList {
            request_id: id(&mut next),
            params: ThreadQueueListParams {
                thread_id: thread.to_string(),
                cursor: None,
                limit: Some(16),
            },
        })
        .await?;
    assert!(queued.data.is_empty() && queued.next_cursor.is_none());
    let run = control
        .run_status(signed.body.run_id.clone())
        .await
        .context("original run-status control response after completed native turn")?
        .context("original Agentd run")?;
    assert_eq!(
        (run.phase, run.generation, run.terminal_observed),
        (crate::AgentRunPhase::Succeeded, 2, true)
    );
    let captured = posts(&server).await?;
    assert_eq!(captured.len(), 1);
    let operation = captured[0]
        .headers
        .get("idempotency-key")
        .context("original operation key")?
        .to_str()?;
    let durable = writer
        .resolve_operation_request(operation, native.model.destination_id())
        .await?;
    assert_eq!(durable.payload_json.as_bytes(), captured[0].body.as_slice());
    assert_eq!(
        writer.status(operation).await?,
        LocalOutcomeState::Committed
    );
    let ObjectiveStartOutcome::Admitted { receipt: duplicate } = control
        .objective_start(signed.clone())
        .await
        .context("exact signed Objective replay control response")?
    else {
        anyhow::bail!("original signed replay was not reconciled");
    };
    assert!(duplicate.idempotent);
    assert_eq!(duplicate.run_id, signed.body.run_id);
    assert_eq!(
        (
            owners.calls.load(Ordering::SeqCst),
            issuer.grants.load(Ordering::SeqCst),
            final_use.capacity()?.used_nonces
        ),
        (1, 1, 1)
    );
    assert_eq!(posts(&server).await?.len(), 1);
    assert_eq!(
        completed(&client, &mut next, &thread.to_string())
            .await?
            .thread
            .turns
            .len(),
        1
    );
    client.shutdown().await?;

    // Publish the original Fleet drain, then use its real control handshake.
    // The daemon must remain alive so the owner can observe that handshake.
    registry.compare_and_transition(&identity.agent_id, 2, AgentLifecycle::Draining)?;
    timeout(WAIT, async {
        let mut request_id = 10_000;
        loop {
            let observed = drain(&identity, request_id).await?;
            request_id += 1;
            if observed.drained {
                assert!(
                    observed.admission_closed && observed.running_turns == 0 && !observed.fenced
                );
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        Ok::<_, anyhow::Error>(())
    })
    .await
    .context("original daemon did not acknowledge drain")??;
    assert!(
        !daemon.is_finished(),
        "drained App Server must retain original control until the stop signal"
    );
    assert!(
        !control
            .health()
            .await
            .context("drained original daemon health control response")?
            .ready
    );
    assert!(control.session_ingress().await.is_err());
    let drain_error = control
        .objective_start(request(&identity, &owners, &key, thread, 3)?)
        .await
        .err()
        .context("Draining generation admitted Objective")?;
    ensure!(
        drain_error.to_string().contains("not ready"),
        "drain test reached another gate: {drain_error}"
    );
    assert_eq!(
        (
            owners.calls.load(Ordering::SeqCst),
            issuer.grants.load(Ordering::SeqCst),
            final_use.capacity()?.used_nonces
        ),
        (1, 1, 1)
    );
    assert_eq!(posts(&server).await?.len(), 1);
    // Signal only this explicitly isolated single-test child, never the outer
    // cargo test process. run() owns its normal task cancellation and joins.
    let signal = tokio::process::Command::new("/bin/kill")
        .args(["-TERM", &std::process::id().to_string()])
        .status()
        .await?;
    ensure!(
        signal.success(),
        "could not signal the isolated daemon test child"
    );
    timeout(WAIT, &mut daemon)
        .await
        .context("actual Agentd runtime did not shut down")???;
    drop(native);
    drop(state);
    drop(writer);
    eprintln!(
        "NATIVE_DAEMON_SHUTDOWN retained_before_wait native={} state={} writer={}",
        native_weak.strong_count(),
        state_weak.strong_count(),
        writer_weak.strong_count()
    );
    timeout(Duration::from_secs(3), async {
        while native_weak.upgrade().is_some() || state_weak.upgrade().is_some() || writer_weak.upgrade().is_some() {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }).await.with_context(|| format!("original daemon/native/writer references survived normal shutdown: native={} state={} writer={}",
        native_weak.strong_count(), state_weak.strong_count(), writer_weak.strong_count()))?;
    assert!(!tokio::fs::try_exists(&identity.control_socket).await?);
    assert!(control.health().await.is_err());
    let trace = tokio::fs::read_to_string(root.join("transport.jsonl")).await?;
    let traces = trace
        .lines()
        .map(serde_json::from_str::<serde_json::Value>)
        .collect::<serde_json::Result<Vec<_>>>()?;
    assert_eq!(traces.len(), 1);
    assert_eq!(
        (
            traces[0]["health"].as_bool(),
            traces[0]["exit_code"].as_i64()
        ),
        (Some(true), Some(0))
    );
    assert_eq!(traces[0]["command"], "printf 'hepta-host-health-v1\\n'");
    private_file(
        &root.join("report.json"),
        &serde_json::to_vec_pretty(&json!({
            "schema":"hepta-native-embedded-daemon-acceptance-v1", "embedded_run_config":true,
            "typed_product_loader_used":true, "typed_product_loader_calls":loader_calls.load(Ordering::SeqCst),
            "loader_dropped_before_runtime":true, "unavailable_loader_failed_before_runtime":true,
            "ordinary_cli_bootstrap_qualified":false, "ssh_authentication_qualified":false, "os_restart_qualified":false,
            "health_probe_processes":1, "owner_preparations":1, "model_posts":1, "grants":1, "consumed_nonces":1,
            "turn_id":turn_id, "queued_item_id":provenance.queue.queued_item_id, "client_id":input.client_user_message_id,
            "initial_spawn_generation":1, "run_generation":2, "drain_generation":3,
            "original_runtime_joined":true, "original_owner_weak_handles_empty":true,
        }))?,
    )?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "requires explicit controlled native runtime namespace opt-in"]
async fn controlled_embedded_daemon_lifecycle() -> Result<()> {
    let Some((root, arg0)) = daemon_environment().await? else {
        return Ok(());
    };
    exercise(&root, arg0).await
}
