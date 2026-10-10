use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Result;
use codex_core::MemoryModelProviderPolicyHandle;
use codex_core::MemoryTurnInputSubmission;
use codex_core::ModelClient;
use codex_core::Prompt;
use codex_core::ResponseEvent;
use codex_core::TurnInput;
use codex_core::TurnInputRequest;
use codex_core::detached_memory_responses_metadata;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyContributor;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderTerminal;
use codex_extension_api::ModelProviderTransport;
use codex_features::Feature;
use codex_login::auth::AgentIdentityAuthPolicy;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::EventMsg;
use codex_protocol::user_input::UserInput;
use core_test_support::responses::ResponseMock;
use core_test_support::responses::ev_assistant_message;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_once_match;
use core_test_support::responses::sse;
use core_test_support::responses::sse_response;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::TestCodex;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event;
use futures::StreamExt;
use tokio::sync::Notify;
use tokio::sync::Semaphore;
use tokio::time::timeout;
use wiremock::Mock;
use wiremock::Respond;
use wiremock::ResponseTemplate;
use wiremock::matchers::body_string_contains;
use wiremock::matchers::method;
use wiremock::matchers::path;

#[derive(Clone, Copy)]
enum MemoryDecision {
    Block,
    AllowWithTerminalGate,
}

#[derive(Default)]
struct TurnScopeToken;

struct InvocationRecord {
    attempt_id: String,
    request_binding_id: String,
    request_kind: ModelProviderRequestKind,
    transport: ModelProviderTransport,
    thread_id: String,
    turn_id: String,
    turn_store_id: String,
    scope: Arc<TurnScopeToken>,
}

struct MemoryPolicyState {
    active: bool,
    decision: MemoryDecision,
    begin_count: AtomicUsize,
    terminal_count: AtomicUsize,
    invocations: Mutex<Vec<InvocationRecord>>,
    memory_terminals: Mutex<Vec<ModelProviderTerminal>>,
    memory_terminal_entered: Notify,
    memory_terminal_release: Semaphore,
}

impl MemoryPolicyState {
    fn new(decision: MemoryDecision) -> Arc<Self> {
        Self::with_active(decision, true)
    }

    fn inactive() -> Arc<Self> {
        Self::with_active(MemoryDecision::AllowWithTerminalGate, false)
    }

    fn with_active(decision: MemoryDecision, active: bool) -> Arc<Self> {
        Arc::new(Self {
            active,
            decision,
            begin_count: AtomicUsize::new(0),
            terminal_count: AtomicUsize::new(0),
            invocations: Mutex::new(Vec::new()),
            memory_terminals: Mutex::new(Vec::new()),
            memory_terminal_entered: Notify::new(),
            memory_terminal_release: Semaphore::new(0),
        })
    }

    async fn wait_for_memory_terminal_count(&self, expected: usize) {
        loop {
            let notified = self.memory_terminal_entered.notified();
            if self
                .memory_terminals
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .len()
                >= expected
            {
                return;
            }
            notified.await;
        }
    }
}

struct MemoryPolicy {
    state: Arc<MemoryPolicyState>,
}

impl ModelProviderPolicyContributor for MemoryPolicy {
    fn is_active(&self, _thread_store: &ExtensionData) -> bool {
        self.state.active
    }

    fn begin<'a>(
        &'a self,
        input: ModelProviderInvocationInput<'a>,
    ) -> ModelProviderPolicyFuture<'a, ModelProviderPolicyDecision> {
        let scope = input.turn_store.get_or_init(TurnScopeToken::default);
        self.state
            .invocations
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(InvocationRecord {
                attempt_id: input.attempt_id.to_string(),
                request_binding_id: input.request_binding_id.to_string(),
                request_kind: input.request_kind,
                transport: input.transport,
                thread_id: input.thread_id.to_string(),
                turn_id: input.turn_id.to_string(),
                turn_store_id: input.turn_store.level_id().to_string(),
                scope,
            });
        self.state.begin_count.fetch_add(1, Ordering::SeqCst);
        let state = Arc::clone(&self.state);
        Box::pin(async move {
            if input.request_kind == ModelProviderRequestKind::Memory
                && matches!(state.decision, MemoryDecision::Block)
            {
                return Ok(ModelProviderPolicyDecision::Block {
                    reason_code: "test_memory_provider_block".to_string(),
                    message: "blocked by memory provider policy test".to_string(),
                });
            }
            Ok(ModelProviderPolicyDecision::Allow {
                lease: Box::new(MemoryPolicyLease {
                    state,
                    request_kind: input.request_kind,
                }),
            })
        })
    }
}

struct MemoryPolicyLease {
    state: Arc<MemoryPolicyState>,
    request_kind: ModelProviderRequestKind,
}

impl ModelProviderAttemptLease for MemoryPolicyLease {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            self.state.terminal_count.fetch_add(1, Ordering::SeqCst);
            if self.request_kind != ModelProviderRequestKind::Memory {
                return Ok(());
            }
            self.state
                .memory_terminals
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .push(terminal);
            self.state.memory_terminal_entered.notify_one();
            let permit = self
                .state
                .memory_terminal_release
                .acquire()
                .await
                .map_err(|error| {
                    ModelProviderPolicyError::new(
                        "test_memory_terminal_gate_closed",
                        error.to_string(),
                    )
                })?;
            permit.forget();
            Ok(())
        })
    }
}

fn extensions_with_memory_policy(
    state: Arc<MemoryPolicyState>,
) -> Arc<codex_extension_api::ExtensionRegistry<codex_core::config::Config>> {
    let mut extensions = ExtensionRegistryBuilder::new();
    extensions.model_provider_policy_contributor(Arc::new(MemoryPolicy { state }));
    Arc::new(extensions.build())
}

fn user_input(text: &str) -> TurnInputRequest {
    TurnInputRequest::new(TurnInput::UserInput {
        content: vec![UserInput::Text {
            text: text.to_string(),
            text_elements: Vec::new(),
        }],
        client_id: Some("memory-parent-message".to_string()),
    })
}

fn request_body_contains(request: &wiremock::Request, needle: &str) -> bool {
    String::from_utf8_lossy(&request.body).contains(needle)
}

async fn capture_after_parent_completion(
    test: &TestCodex,
) -> Result<(String, MemoryModelProviderPolicyHandle)> {
    let submission = test
        .codex
        .start_or_steer_turn_and_capture_memory_policy(user_input(
            "parent turn for detached memory",
        ))
        .await?;
    let (turn_id, provider_policy) = match submission {
        MemoryTurnInputSubmission::Started {
            turn_id,
            provider_policy,
        } => (turn_id, provider_policy),
        MemoryTurnInputSubmission::Steered { .. }
        | MemoryTurnInputSubmission::NotSubmitted { .. } => {
            anyhow::bail!("memory policy capture did not start a fresh parent turn")
        }
    };
    wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;
    Ok((turn_id, provider_policy))
}

async fn stream_detached_memory(
    test: &TestCodex,
    provider_policy: &MemoryModelProviderPolicyHandle,
) -> Result<String> {
    let config = test.codex.config().await;
    let config_snapshot = test.codex.config_snapshot().await;
    let model = codex_core::test_support::get_model_offline(config.model.as_deref());
    let model_info = codex_core::test_support::construct_model_info_offline(&model, &config);
    let model_client = ModelClient::new(
        Some(test.thread_manager.auth_manager()),
        AgentIdentityAuthPolicy::JwtOnly,
        test.session_configured.thread_id,
        config.model_provider.clone(),
        config_snapshot.session_source.clone(),
        config_snapshot.originator,
        config.model_verbosity,
        config.features.enabled(Feature::ContentItemKinds),
        config.features.enabled(Feature::EnableRequestCompression),
        config.features.enabled(Feature::RuntimeMetrics),
        /*beta_features_header*/ None,
        /*concurrent_reasoning_summaries_enabled*/ false,
        /*attestation_provider*/ None,
        config.http_client_factory(),
    );
    let thread_id = test.session_configured.thread_id.to_string();
    let metadata = detached_memory_responses_metadata(
        "memory-policy-test-installation".to_string(),
        thread_id.clone(),
        thread_id.clone(),
        format!("{thread_id}:memory-policy-test"),
        &config_snapshot.session_source,
        &config.cwd,
        config.permissions.permission_profile(),
        /*sandbox*/ None,
    )
    .await;
    let mut prompt = Prompt::default();
    prompt.input.push(ResponseItem::Message {
        id: None,
        role: "user".to_string(),
        content: vec![ContentItem::InputText {
            text: "detached memory sample".to_string(),
        }],
        phase: None,
        internal_chat_message_metadata_passthrough: None,
    });
    let mut session = model_client.new_session();
    let mut stream = session
        .stream_memory_with_policy(
            &prompt,
            &model_info,
            &test.codex.session_telemetry(),
            config.model_reasoning_effort.clone(),
            config
                .model_reasoning_summary
                .unwrap_or(model_info.default_reasoning_summary),
            config_snapshot.service_tier,
            &metadata,
            &codex_rollout_trace::InferenceTraceContext::disabled(),
            provider_policy,
        )
        .await?;
    let mut output = String::new();
    while let Some(event) = stream.next().await.transpose()? {
        match event {
            ResponseEvent::OutputTextDelta(delta) => output.push_str(&delta),
            ResponseEvent::OutputItemDone(ResponseItem::Message { content, .. })
                if output.is_empty() =>
            {
                output = content
                    .iter()
                    .filter_map(|item| match item {
                        ContentItem::OutputText { text } => Some(text.as_str()),
                        _ => None,
                    })
                    .collect();
            }
            ResponseEvent::Completed { .. } => return Ok(output),
            _ => {}
        }
    }
    anyhow::bail!("detached memory response ended before completion")
}

async fn mount_parent_response(server: &wiremock::MockServer) -> ResponseMock {
    mount_sse_once_match(
        server,
        |request: &wiremock::Request| {
            request_body_contains(request, "parent turn for detached memory")
        },
        sse(vec![
            ev_response_created("memory-parent"),
            ev_completed("memory-parent"),
        ]),
    )
    .await
}

async fn mount_memory_response(server: &wiremock::MockServer) -> ResponseMock {
    mount_sse_once_match(
        server,
        |request: &wiremock::Request| request_body_contains(request, "detached memory sample"),
        sse(vec![
            ev_response_created("memory-response"),
            ev_assistant_message("memory-message", "memory complete"),
            ev_completed("memory-response"),
        ]),
    )
    .await
}

struct MemoryResponseSequence {
    next: AtomicUsize,
    responses: Vec<ResponseTemplate>,
}

impl Respond for MemoryResponseSequence {
    fn respond(&self, _: &wiremock::Request) -> ResponseTemplate {
        let index = self.next.fetch_add(1, Ordering::SeqCst);
        self.responses
            .get(index)
            .expect("missing detached Memory response")
            .clone()
    }
}

async fn mount_retrying_memory_response(server: &wiremock::MockServer) {
    Mock::given(method("POST"))
        .and(path("/v1/responses"))
        .and(body_string_contains("detached memory sample"))
        .respond_with(MemoryResponseSequence {
            next: AtomicUsize::new(0),
            responses: vec![
                ResponseTemplate::new(500)
                    .insert_header("content-type", "application/json")
                    .set_body_string(r#"{"error":{"message":"retry detached Memory"}}"#),
                sse_response(sse(vec![
                    ev_response_created("memory-response"),
                    ev_assistant_message("memory-message", "memory complete"),
                    ev_completed("memory-response"),
                ])),
            ],
        })
        .expect(2)
        .mount(server)
        .await;
}

async fn memory_request_count(server: &wiremock::MockServer) -> usize {
    server
        .received_requests()
        .await
        .unwrap_or_default()
        .iter()
        .filter(|request| {
            request.url.path() == "/v1/responses"
                && request_body_contains(request, "detached memory sample")
        })
        .count()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn memory_block_after_parent_completion_reuses_exact_turn_scope() -> Result<()> {
    let server = start_mock_server().await;
    let parent_response = mount_parent_response(&server).await;
    let memory_response = mount_memory_response(&server).await;
    let state = MemoryPolicyState::new(MemoryDecision::Block);
    let test = test_codex()
        .with_config(|config| config.model_provider.request_max_retries = Some(3))
        .with_extensions(extensions_with_memory_policy(Arc::clone(&state)))
        .build(&server)
        .await?;

    let (parent_turn_id, policy) = capture_after_parent_completion(&test).await?;
    assert_eq!(parent_response.requests().len(), 1);
    let error = stream_detached_memory(&test, &policy)
        .await
        .expect_err("Memory policy must block before transport");
    assert!(error.to_string().contains("test_memory_provider_block"));
    assert!(memory_response.requests().is_empty());

    let invocations = state
        .invocations
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let [turn, memory] = invocations.as_slice() else {
        panic!("expected one parent and one Memory invocation");
    };
    assert_eq!(turn.request_kind, ModelProviderRequestKind::Turn);
    assert_eq!(memory.request_kind, ModelProviderRequestKind::Memory);
    assert_eq!(turn.thread_id, memory.thread_id);
    assert_eq!(turn.turn_id, parent_turn_id);
    assert_eq!(memory.turn_id, parent_turn_id);
    assert_eq!(turn.turn_store_id, memory.turn_store_id);
    assert!(Arc::ptr_eq(&turn.scope, &memory.scope));
    assert_eq!(state.terminal_count.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn memory_retry_and_result_wait_for_each_terminal() -> Result<()> {
    let server = start_mock_server().await;
    mount_parent_response(&server).await;
    mount_retrying_memory_response(&server).await;
    let state = MemoryPolicyState::new(MemoryDecision::AllowWithTerminalGate);
    let test = test_codex()
        .with_config(|config| {
            config.model_provider.request_max_retries = Some(1);
            config.model_provider.stream_max_retries = Some(0);
        })
        .with_extensions(extensions_with_memory_policy(Arc::clone(&state)))
        .build(&server)
        .await?;
    let (_, policy) = capture_after_parent_completion(&test).await?;
    let request = stream_detached_memory(&test, &policy);
    tokio::pin!(request);

    tokio::select! {
        result = &mut request => panic!("Memory result returned before terminal entered: {result:?}"),
        result = timeout(Duration::from_secs(5), state.wait_for_memory_terminal_count(1)) => {
            result?;
        }
    }
    assert_eq!(memory_request_count(&server).await, 1);
    assert!(
        timeout(Duration::from_millis(50), &mut request)
            .await
            .is_err(),
        "Memory result must wait for terminal acknowledgment"
    );
    assert!(matches!(
        state
            .memory_terminals
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .as_slice(),
        [ModelProviderTerminal::Indeterminate {
            reason_code,
            partial_response_sha256: None,
        }] if reason_code == "provider_http_send_failed"
    ));

    state.memory_terminal_release.add_permits(1);
    tokio::select! {
        result = &mut request => panic!("Memory result returned before retry terminal entered: {result:?}"),
        result = timeout(Duration::from_secs(5), state.wait_for_memory_terminal_count(2)) => {
            result?;
        }
    }
    assert_eq!(memory_request_count(&server).await, 2);
    assert!(matches!(
        state
            .memory_terminals
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .as_slice(),
        [
            ModelProviderTerminal::Indeterminate { .. },
            ModelProviderTerminal::Completed { .. }
        ]
    ));
    assert!(
        timeout(Duration::from_millis(50), &mut request)
            .await
            .is_err(),
        "Memory result must wait for retry terminal acknowledgment"
    );

    state.memory_terminal_release.add_permits(1);
    assert_eq!(
        timeout(Duration::from_secs(5), &mut request).await??,
        "memory complete"
    );
    assert_eq!(state.begin_count.load(Ordering::SeqCst), 3);
    assert_eq!(state.terminal_count.load(Ordering::SeqCst), 3);
    let invocations = state
        .invocations
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let [parent, first, second] = invocations.as_slice() else {
        panic!("expected one parent and two Memory invocations");
    };
    assert_eq!(parent.request_kind, ModelProviderRequestKind::Turn);
    assert_eq!(first.request_kind, ModelProviderRequestKind::Memory);
    assert_eq!(second.request_kind, ModelProviderRequestKind::Memory);
    assert_eq!(first.transport, ModelProviderTransport::Http);
    assert_eq!(second.transport, ModelProviderTransport::Http);
    assert_ne!(first.attempt_id, second.attempt_id);
    assert_eq!(first.request_binding_id, second.request_binding_id);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn inactive_memory_policy_preserves_provider_transport_retry() -> Result<()> {
    let server = start_mock_server().await;
    mount_parent_response(&server).await;
    mount_retrying_memory_response(&server).await;
    let state = MemoryPolicyState::inactive();
    let test = test_codex()
        .with_config(|config| {
            config.model_provider.request_max_retries = Some(1);
            config.model_provider.stream_max_retries = Some(0);
        })
        .with_extensions(extensions_with_memory_policy(Arc::clone(&state)))
        .build(&server)
        .await?;
    let (_, policy) = capture_after_parent_completion(&test).await?;

    assert_eq!(
        stream_detached_memory(&test, &policy).await?,
        "memory complete"
    );
    assert_eq!(memory_request_count(&server).await, 2);
    assert_eq!(state.begin_count.load(Ordering::SeqCst), 0);
    assert_eq!(state.terminal_count.load(Ordering::SeqCst), 0);
    Ok(())
}
