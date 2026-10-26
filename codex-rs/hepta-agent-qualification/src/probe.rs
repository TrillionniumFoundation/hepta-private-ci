use crate::Args;
use crate::evidence::ContinuationEvidence;
use crate::evidence::Evidence;
use crate::evidence::ExactBodyObserver;
use crate::request_wire::PreparedOrdinaryWire;
use anyhow::Result;
use anyhow::anyhow;
use codex_api::ResponsesOptions;
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

#[path = "probe_request.rs"]
mod request_template;
#[path = "probe_settings.rs"]
mod settings;

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
    let prepared_settings = settings::prepare(&config, &provider, model, &evidence).await?;
    let request_settings_evidence_digest = prepared_settings.evidence_digest;
    let normalized_settings = prepared_settings.settings;
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
    let turn_id = StableId::new(format!("qualification-turn:{identity}"))?;
    // Cold migrations are a separate bounded preparation phase. No generation
    // binding/deadline, admitted attempt or dispatch exists before it is ready.
    let bootstrap = crate::bootstrap::prepare(
        &config,
        &evidence,
        &run_id,
        &turn_id,
        args.maximum_bootstrap_seconds,
    )
    .await?;
    let policy = bootstrap.owner;
    let api_request = request_template::prepare(model, &run_id, normalized_settings)?;
    let encoded = EncodedJsonBody::encode(&api_request)
        .map_err(|_| anyhow!("qualification request encoding failed"))?;
    let body_digest = Digest32::of_bytes(encoded.as_bytes());
    let wire = PreparedOrdinaryWire::new(body_digest, request_settings_evidence_digest)?;
    let admission = json!({
        "schema":"hepta-native-qualification-admission:v2",
        "run_id":run_id.as_str(), "request_id":request_id.as_str(),
        "model":model, "provider":config.model_provider_id,
        "auth_policy":policy_name, "api_body_sha256":body_digest.to_string(),
        "wire_semantic_sha256":wire.semantic_digest().to_string(),
        "request_settings_evidence_sha256":request_settings_evidence_digest.to_string(),
        "request_normalization":"shared_original_model_settings_ordinary_v1",
        "ordinary_tool_shape":"shared_core_empty_tools_auto_v1",
        "catalog_refresh_strategy":"offline", "full_core_request_parity":false,
        "routing_hint":null, "responses_lite":false,
        "routing_and_lite_headers_must_be_absent":true,
        "compiled_context_tokens":0, "compiled_context_bytes":0,
        "maximum_provider_input_tokens":args.maximum_provider_input_tokens,
        "maximum_output_tokens":args.maximum_output_tokens,
        "maximum_elapsed_seconds":args.maximum_elapsed_seconds,
        "policy_bootstrap_sha256":bootstrap.evidence_digest.to_string(),
        "maximum_policy_bootstrap_seconds":args.maximum_bootstrap_seconds,
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
        turn_id,
        generation: Generation::new(1)?,
        admission_digest,
        deadline_unix_ms: now
            .checked_add(args.maximum_elapsed_seconds * 1_000)
            .ok_or_else(|| anyhow!("qualification deadline overflow"))?,
    };
    let observer = Arc::new(ExactBodyObserver::new(evidence.clone(), body_digest));
    let dispatch = wire.dispatch_metadata();
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
            &wire,
            policy_name,
        ),
    )
    .await
    .map_err(|_| anyhow!("qualification policy admission deadline"))??;
    let mut terminal_completion = client.terminal_completion();
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
    // Either terminal owner can finish first. Encoded evidence alone cannot
    // authorize closing the policy state while its original write is pending.
    let shutdown = crate::terminal_shutdown::TerminalShutdown::wait(
        &mut terminal_completion,
        &observer,
        Duration::from_secs(10),
    )
    .await;
    let terminal_writes_settled = shutdown.writes_settled();
    let terminal_recorded = shutdown.encoded_recorded();
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
    // Serialize fields independently so report growth does not deepen the
    // json! object parser recursion; keep the original keys and expressions.
    let report = Value::Object(serde_json::Map::from_iter([
        (
            "policy_bootstrap_sha256".to_owned(),
            json!(bootstrap.evidence_digest.to_string()),
        ),
        (
            "policy_bootstrap_elapsed_ms".to_owned(),
            json!(bootstrap.elapsed_ms),
        ),
        (
            "generation_deadline_started_after_policy_bootstrap".to_owned(),
            json!(true),
        ),
        (
            "schema".to_owned(),
            json!("hepta-native-provider-qualification-result:v1"),
        ),
        (
            "qualified".to_owned(),
            json!(
                complete
                    && observed.completed
                    && !observed.unexpected_tool
                    && terminal_recorded
                    && terminal_writes_settled
                    && within_reservations
                    && output_matches
            ),
        ),
        ("status".to_owned(), json!(status)),
        (
            "provider_transport_invoked".to_owned(),
            json!(dispatch.transport_invoked()),
        ),
        (
            "failure_diagnostic".to_owned(),
            json!(result.as_ref().err().map(failure_diagnostic)),
        ),
        (
            "wire_semantic_sha256".to_owned(),
            json!(wire.semantic_digest().to_string()),
        ),
        (
            "request_settings_evidence_sha256".to_owned(),
            json!(request_settings_evidence_digest.to_string()),
        ),
        (
            "request_normalization".to_owned(),
            json!("shared_original_model_settings_ordinary_v1"),
        ),
        (
            "ordinary_tool_shape".to_owned(),
            json!("shared_core_empty_tools_auto_v1"),
        ),
        ("catalog_refresh_strategy".to_owned(), json!("offline")),
        ("full_core_request_parity".to_owned(), json!(false)),
        (
            "routing_and_lite_headers_must_be_absent".to_owned(),
            json!(true),
        ),
        (
            "previous_indeterminate_attempt_repaired".to_owned(),
            json!(false),
        ),
        ("maximum_provider_calls".to_owned(), json!(1)),
        ("automatic_retry".to_owned(), json!(false)),
        ("requested_model".to_owned(), json!(model)),
        (
            "server_model".to_owned(),
            json!(continuation.as_ref().and_then(|c| c.get("server_model"))),
        ),
        (
            "configured_reasoning_effort".to_owned(),
            json!(config.model_reasoning_effort),
        ),
        ("actual_usage".to_owned(), json!(usage)),
        (
            "provider_rollout_budget_units".to_owned(),
            json!(
                continuation
                    .as_ref()
                    .and_then(|c| c.get("provider_rollout_budget_units"))
            ),
        ),
        (
            "within_declared_reservations".to_owned(),
            json!(within_reservations),
        ),
        (
            "provider_hard_token_cap".to_owned(),
            json!("not_exposed_by_current_request_schema"),
        ),
        ("compiled_context_tokens".to_owned(), json!(0)),
        ("compiled_context_qualified".to_owned(), json!(false)),
        (
            "local_reservation_input_tokens".to_owned(),
            json!(args.maximum_provider_input_tokens),
        ),
        (
            "local_reservation_output_tokens".to_owned(),
            json!(args.maximum_output_tokens),
        ),
        ("elapsed_ms".to_owned(), json!(elapsed_ms)),
        (
            "first_visible_ms".to_owned(),
            json!(observed.first_visible_ms),
        ),
        ("visible_bytes".to_owned(), json!(observed.text.len())),
        (
            "visible_sha256".to_owned(),
            json!(Digest32::of_bytes(observed.text.as_bytes()).to_string()),
        ),
        ("expected_marker_matches".to_owned(), json!(output_matches)),
        (
            "terminal_writes_settled".to_owned(),
            json!(terminal_writes_settled),
        ),
        (
            "encoded_terminal_recorded".to_owned(),
            json!(terminal_recorded),
        ),
        (
            "full_continuation_retained".to_owned(),
            json!(continuation.is_some()),
        ),
        (
            "continuation_scope".to_owned(),
            json!("supported typed ResponseItem fields exposed by the parser"),
        ),
        ("tool_calls_executed".to_owned(), json!(0)),
        (
            "unexpected_tool_call".to_owned(),
            json!(observed.unexpected_tool),
        ),
        ("production_native_agent_qualified".to_owned(), json!(false)),
        ("same_model_codex_ab".to_owned(), json!(false)),
        ("core_linked_for_config_bootstrap".to_owned(), json!(true)),
    ]));
    shutdown.close_if_settled(&policy.state).await;
    Ok(report)
}

// Error strings can contain provider bodies, URLs or credentials. Only the
// typed allowlist above the HTTP/stream boundary may enter retained evidence.
fn failure_diagnostic(error: &codex_hepta_agent_loop::Error) -> Value {
    use codex_hepta_agent_loop::Error as LoopError;
    match error {
        LoopError::Responses(failure) => json!({
            "stage":failure.stage.as_str(), "category":failure.category.as_str(),
            "http_status":failure.http_status,
            "provider_error":failure.provider_error.map(|details| json!({
                "type":details.error_type.map(codex_hepta_agent_loop::ResponsesProviderErrorType::as_str),
                "code":details.code.map(codex_hepta_agent_loop::ResponsesProviderErrorCode::as_str),
                "param":details.parameter.map(codex_hepta_agent_loop::ResponsesProviderErrorParam::as_str),
            })),
        }),
        LoopError::Limit(_) => json!({"stage":"native", "category":"limit", "http_status":null}),
        LoopError::Contract(_) => {
            json!({"stage":"native", "category":"contract", "http_status":null})
        }
        LoopError::Owner(_) => json!({"stage":"native", "category":"owner", "http_status":null}),
    }
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

#[cfg(test)]
#[path = "probe_diagnostics_tests.rs"]
mod diagnostics_tests;
