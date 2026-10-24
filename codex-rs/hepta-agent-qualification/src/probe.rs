use crate::Args;
use crate::evidence::ContinuationEvidence;
use crate::evidence::Evidence;
use crate::evidence::ExactBodyObserver;
use crate::policy::QualificationPolicy;
use anyhow::Result;
use anyhow::anyhow;
use codex_api::Reasoning;
use codex_api::RequestDispatchMetadata;
use codex_api::ResponsesApiRequest;
use codex_api::ResponsesOptions;
use codex_api::TextControls;
use codex_core::config::ConfigBuilder;
use codex_features::Feature;
use codex_hepta_agent_loop::ManagedResponsesAttempt;
use codex_hepta_agent_loop::ManagedResponsesClient;
use codex_hepta_agent_loop::ModelEvent;
use codex_hepta_agent_loop::ModelRequest;
use codex_hepta_agent_loop::ResponsesBridgeLimits;
use codex_hepta_agent_loop::ResponsesBridgeStatus;
use codex_hepta_agent_loop::TurnBinding;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_http_client::EncodedJsonBody;
use codex_login::AgentIdentityAuthPolicy;
use codex_login::AuthManager;
use codex_model_provider::AgentIdentitySessionFallback;
use codex_model_provider::ProviderAuthScope;
use codex_model_provider::create_model_provider;
use codex_protocol::protocol::SessionSource;
use serde_json::Value;
use serde_json::json;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

const EXPECTED: &str = "HEPTA_NATIVE_STREAM_OK";
const MAXIMUM_VISIBLE_BYTES: usize = 8_192;
const MAXIMUM_RETAINED_BYTES: usize = 262_144;

pub(crate) async fn run(args: &Args, evidence: Arc<Evidence>) -> Result<Value> {
    let config = tokio::time::timeout(Duration::from_secs(20), ConfigBuilder::default().build())
        .await
        .map_err(|_| anyhow!("qualification configuration deadline"))?
        .map_err(|_| anyhow!("qualification installed configuration failed"))?;
    let model = config
        .model
        .as_deref()
        .ok_or_else(|| anyhow!("qualification requires an explicitly configured model"))?;
    if model != args.expected_model {
        return Err(anyhow!(
            "qualification configured model differs from expected model"
        ));
    }
    let auth = tokio::time::timeout(
        Duration::from_secs(20),
        AuthManager::shared_from_config(&config, true),
    )
    .await
    .map_err(|_| anyhow!("qualification auth owner deadline"))?
    .map_err(|_| anyhow!("qualification auth owner unavailable"))?;
    let provider = create_model_provider(config.model_provider.clone(), Some(auth));
    let use_agent_identity = config.features.enabled(Feature::UseAgentIdentity);
    let policy_name = if use_agent_identity {
        "configured_chatgpt_agent_identity"
    } else {
        "configured_jwt_only"
    };
    let cancellation = CancellationToken::new();
    let client = ManagedResponsesClient::from_owner(
        &provider,
        ProviderAuthScope {
            agent_identity_policy: if use_agent_identity {
                AgentIdentityAuthPolicy::ChatGptAuth
            } else {
                AgentIdentityAuthPolicy::JwtOnly
            },
            session_source: SessionSource::Exec,
            agent_identity_session_fallback: AgentIdentitySessionFallback::default(),
        },
        &config.http_client_factory(),
        Duration::from_secs(20),
        &cancellation,
    )
    .await
    .map_err(|_| anyhow!("qualification managed provider setup failed"))?;
    let identity = uuid::Uuid::new_v4().to_string();
    let request_id = StableId::new(format!("qualification-request:{identity}"))?;
    let run_id = StableId::new(format!("qualification-run:{identity}"))?;
    let api_request = ResponsesApiRequest {
        model: model.to_string(),
        instructions: "Run this harmless connectivity qualification. Return exactly the requested marker, without explanations or tool calls.".into(),
        input: vec![serde_json::from_value(json!({
            "type":"message", "role":"user",
            "content":[{"type":"input_text", "text":format!("Return only {EXPECTED}")}],
        }))?],
        tools: None, tool_choice: "none".into(), parallel_tool_calls: false,
        reasoning: Some(Reasoning { effort: config.model_reasoning_effort.clone(),
            summary: config.model_reasoning_summary, context: None }),
        store: false, stream: true, stream_options: None,
        include: vec!["reasoning.encrypted_content".into()],
        service_tier: config.service_tier.clone(), prompt_cache_key: Some(run_id.to_string()),
        text: config.model_verbosity.map(|verbosity| TextControls { verbosity: Some(verbosity.into()), format: None }),
        client_metadata: None,
    };
    let encoded = EncodedJsonBody::encode(&api_request)
        .map_err(|_| anyhow!("qualification request encoding failed"))?;
    let body_digest = Digest32::of_bytes(encoded.as_bytes());
    let admission = json!({
        "schema":"hepta-native-qualification-admission:v1",
        "run_id":run_id.as_str(), "request_id":request_id.as_str(),
        "model":model, "provider":config.model_provider_id,
        "auth_policy":policy_name, "api_body_sha256":body_digest.to_string(),
        "compiled_context_tokens":0, "compiled_context_bytes":0,
        "maximum_provider_input_tokens":args.maximum_provider_input_tokens,
        "maximum_output_tokens":args.maximum_output_tokens,
        "maximum_elapsed_seconds":args.maximum_elapsed_seconds,
        "maximum_provider_calls":1, "research_only":true,
    });
    let admission_digest = evidence.record("admission.json", &admission)?;
    // There is no compiled history in this first connectivity probe. The task
    // is in the explicitly admitted API template. No tokenizer estimate is
    // represented as an exact model count; all actual input is reserved below.
    let request = ModelRequest {
        request_id,
        payload: "".into(),
        context_digest: Digest32::of_bytes(b""),
        input_tokens: 0,
        maximum_provider_input_tokens: args.maximum_provider_input_tokens,
        maximum_output_tokens: args.maximum_output_tokens,
    };
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let binding = TurnBinding {
        run_id,
        turn_id: StableId::new(format!("qualification-turn:{identity}"))?,
        generation: Generation::new(1)?,
        admission_digest,
        deadline_unix_ms: now
            .checked_add(args.maximum_elapsed_seconds * 1_000)
            .ok_or_else(|| anyhow!("qualification deadline overflow"))?,
    };
    let policy = tokio::time::timeout(
        Duration::from_secs(10),
        QualificationPolicy::open(
            &config,
            &evidence.directory().join("provider-policy"),
            &binding,
        ),
    )
    .await
    .map_err(|_| anyhow!("qualification policy setup deadline"))??;
    let observer = Arc::new(ExactBodyObserver::new(evidence.clone(), body_digest));
    let dispatch = RequestDispatchMetadata::new();
    let retained = Arc::new(Mutex::new(None));
    let mut owner = ContinuationEvidence {
        evidence: evidence.clone(),
        binding: binding.clone(),
        request: request.clone(),
        retained: retained.clone(),
    };
    let (tx, rx) = mpsc::channel(8);
    let started = Instant::now();
    let collector = tokio::spawn(collect(rx, cancellation.clone(), started));
    // Nothing fallible or awaited may intervene after admission and transfer
    // of the real consumed lease into the managed cancellation supervisor.
    let lease = tokio::time::timeout(
        Duration::from_secs(10),
        policy.admit(
            &config,
            &binding,
            &request,
            model,
            client.endpoint_for_admission(),
            body_digest,
            policy_name,
        ),
    )
    .await
    .map_err(|_| anyhow!("qualification policy admission deadline"))??;
    let result = client
        .stream_admitted(
            ManagedResponsesAttempt {
                binding: &binding,
                request: &request,
                expected_model: model,
                api_request,
                options: ResponsesOptions {
                    session_id: Some(binding.run_id.to_string()),
                    thread_id: Some(binding.run_id.to_string()),
                    session_source: Some(SessionSource::Exec),
                    encoded_body_observer: Some(observer.clone()),
                    ..Default::default()
                },
                dispatch: dispatch.clone(),
                lease,
                maximum_elapsed: Duration::from_secs(args.maximum_elapsed_seconds),
                terminal_timeout: Duration::from_secs(10),
                bridge_limits: ResponsesBridgeLimits {
                    maximum_items: 16,
                    maximum_retained_bytes: MAXIMUM_RETAINED_BYTES,
                    maximum_visible_bytes: MAXIMUM_VISIBLE_BYTES,
                },
            },
            &mut owner,
            tx,
            &cancellation,
        )
        .await;
    let elapsed_ms = started.elapsed().as_millis();
    // A local timeout is not a provider cancellation ACK. Give the retained
    // supervisor its bounded terminal-write grace before this process exits.
    let terminal_recorded =
        tokio::time::timeout(Duration::from_secs(10), observer.terminal_recorded())
            .await
            .is_ok();
    let observed = collector
        .await
        .map_err(|_| anyhow!("qualification event collector failed"))?;
    let continuation = retained
        .lock()
        .map_err(|_| anyhow!("qualification observation lock"))?
        .clone();
    let usage = continuation.as_ref().and_then(|c| c.get("usage")).cloned();
    let within_reservations = usage.as_ref().is_some_and(|usage| {
        usage
            .get("input_tokens")
            .and_then(Value::as_u64)
            .is_some_and(|n| n <= args.maximum_provider_input_tokens)
            && usage
                .get("output_tokens")
                .and_then(Value::as_u64)
                .is_some_and(|n| n <= args.maximum_output_tokens)
    });
    let complete =
        matches!(&result, Ok(result) if result.status == ResponsesBridgeStatus::Completed);
    let status = match &result {
        Ok(result) => match result.status {
            ResponsesBridgeStatus::Completed => "completed",
            ResponsesBridgeStatus::Incomplete => "incomplete",
            ResponsesBridgeStatus::LocalCancellation => "local_cancellation_unresolved",
        },
        Err(_) => "provider_or_owner_failure",
    };
    let output_matches = observed.text.trim() == EXPECTED;
    let report = json!({
        "schema":"hepta-native-provider-qualification-result:v1",
        "qualified":complete && observed.completed && !observed.unexpected_tool && terminal_recorded && within_reservations && output_matches,
        "status":status, "provider_transport_invoked":dispatch.transport_invoked(),
        "maximum_provider_calls":1, "automatic_retry":false,
        "requested_model":model, "server_model":continuation.as_ref().and_then(|c| c.get("server_model")),
        "configured_reasoning_effort":config.model_reasoning_effort,
        "actual_usage":usage, "provider_rollout_budget_units":continuation.as_ref().and_then(|c| c.get("provider_rollout_budget_units")),
        "within_declared_reservations":within_reservations,
        "provider_hard_token_cap":"not_exposed_by_current_request_schema",
        "compiled_context_tokens":0, "compiled_context_qualified":false,
        "local_reservation_input_tokens":args.maximum_provider_input_tokens,
        "local_reservation_output_tokens":args.maximum_output_tokens,
        "elapsed_ms":elapsed_ms, "first_visible_ms":observed.first_visible_ms,
        "visible_bytes":observed.text.len(), "visible_sha256":Digest32::of_bytes(observed.text.as_bytes()).to_string(),
        "expected_marker_matches":output_matches, "encoded_terminal_recorded":terminal_recorded,
        "full_continuation_retained":continuation.is_some(),
        "continuation_scope":"supported typed ResponseItem fields exposed by the parser",
        "tool_calls_executed":0, "unexpected_tool_call":observed.unexpected_tool,
        "production_native_agent_qualified":false, "same_model_codex_ab":false,
        "core_linked_for_config_bootstrap":true,
    });
    if terminal_recorded {
        policy.state.close().await;
    }
    Ok(report)
}

struct Observation {
    text: String,
    first_visible_ms: Option<u128>,
    completed: bool,
    unexpected_tool: bool,
}

async fn collect(
    mut events: mpsc::Receiver<codex_hepta_agent_loop::Result<ModelEvent>>,
    cancellation: CancellationToken,
    started: Instant,
) -> Observation {
    let mut observed = Observation {
        text: String::new(),
        first_visible_ms: None,
        completed: false,
        unexpected_tool: false,
    };
    while let Some(event) = events.recv().await {
        match event {
            Ok(ModelEvent::TextDelta(text)) => {
                if observed.text.len().saturating_add(text.len()) > MAXIMUM_VISIBLE_BYTES {
                    cancellation.cancel();
                    break;
                }
                observed
                    .first_visible_ms
                    .get_or_insert_with(|| started.elapsed().as_millis());
                observed.text.push_str(&text);
            }
            Ok(ModelEvent::Completed { .. }) => observed.completed = true,
            Ok(ModelEvent::ToolCall(_)) => {
                observed.unexpected_tool = true;
                cancellation.cancel();
            }
            Err(_) => cancellation.cancel(),
        }
    }
    observed
}
