//! Session- and turn-scoped helpers for talking to model provider APIs.
//!
//! `ModelClient` is intended to live for the lifetime of a Codex session and holds the stable
//! configuration and state needed to talk to a provider (auth, provider selection, conversation id,
//! and transport fallback state).
//!
//! Per-turn settings (model selection, reasoning controls, telemetry context, and turn metadata)
//! are passed explicitly to streaming and unary methods so that the turn lifetime is visible at the
//! call site.
//!
//! A [`ModelClientSession`] is created per turn and is used to stream one or more Responses API
//! requests during that turn. It caches a Responses WebSocket connection (opened lazily) and stores
//! per-turn state such as the `x-codex-turn-state` token used for sticky routing.
//!
//! WebSocket prewarm is a v2-only `response.create` with `generate=false`; it waits for completion
//! so the next request can reuse the same connection and `previous_response_id`.
//!
//! Turn execution performs prewarm as a best-effort step before the first stream request so the
//! subsequent request can reuse the same connection.
//!
//! ## Retry-Budget Tradeoff
//!
//! WebSocket prewarm is treated as the first websocket connection attempt for a turn. If it
//! fails, normal stream retry/fallback logic handles recovery on the same turn.

use std::collections::BTreeMap;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex as StdMutex;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_api::AgentIdentityTelemetry;
use codex_api::ApiError;
use codex_api::AuthProvider;
use codex_api::CompactClient as ApiCompactClient;
use codex_api::CompactionInput as ApiCompactionInput;
use codex_api::Compression;
use codex_api::MemoriesClient as ApiMemoriesClient;
use codex_api::MemorySummarizeInput as ApiMemorySummarizeInput;
use codex_api::MemorySummarizeOutput as ApiMemorySummarizeOutput;
use codex_api::Provider as ApiProvider;
use codex_api::RawMemory as ApiRawMemory;
use codex_api::RealtimeCallClient as ApiRealtimeCallClient;
use codex_api::RealtimeSessionConfig as ApiRealtimeSessionConfig;
use codex_api::Reasoning;
use codex_api::ReasoningContext;
use codex_api::RequestDispatchMetadata;
use codex_api::RequestTelemetry;
use codex_api::ReqwestTransport;
use codex_api::ResponseCreateWsRequest;
use codex_api::ResponsesApiRequest;
use codex_api::ResponsesClient as ApiResponsesClient;
use codex_api::ResponsesOptions as ApiResponsesOptions;
use codex_api::ResponsesWebsocketClient as ApiWebSocketResponsesClient;
use codex_api::ResponsesWebsocketConnection as ApiWebSocketConnection;
use codex_api::ResponsesWsRequest;
use codex_api::SharedAuthProvider;
use codex_api::SseTelemetry;
use codex_api::StreamOptions;
use codex_api::TransportError;
use codex_api::WebsocketTelemetry;
use codex_api::auth_header_telemetry;
use codex_api::build_session_headers;
use codex_api::create_text_param_for_request;
use codex_api::response_create_client_metadata;
use codex_http_client::ClientRouteClass;
use codex_http_client::HttpClientFactory;
use codex_login::AuthManager;
use codex_login::CodexAuth;
use codex_login::RefreshTokenError;
use codex_login::UnauthorizedRecovery;
use codex_login::default_client::add_originator_header;
use codex_login::default_client::create_client_for_route;
use codex_login::default_client::create_client_for_sensitive_route;
use codex_otel::SessionTelemetry;
use codex_otel::current_span_w3c_trace_context;
use codex_protocol::auth::AuthMode;

use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderTerminal;
use codex_extension_api::ModelProviderTransport;
use codex_protocol::ThreadId;
use codex_protocol::config_types::ReasoningSummary as ReasoningSummaryConfig;
use codex_protocol::config_types::Verbosity as VerbosityConfig;
use codex_protocol::models::ResponseItem;
use codex_protocol::openai_models::ModelInfo;
use codex_protocol::openai_models::ReasoningEffort as ReasoningEffortConfig;
use codex_protocol::protocol::InternalSessionSource;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::W3cTraceContext;
use codex_rollout_trace::CompactionTraceAttempt;
use codex_rollout_trace::CompactionTraceContext;
use codex_rollout_trace::InferenceTraceAttempt;
use codex_rollout_trace::InferenceTraceContext;
use codex_tools::create_tools_json_for_responses_api;
use codex_tools::create_tools_json_for_responses_lite;
use codex_tools::create_tools_raw_json_for_responses_api;
use eventsource_stream::Event;
use eventsource_stream::EventStreamError;
use futures::FutureExt;
use futures::StreamExt;
use futures::future::BoxFuture;
use http::HeaderMap as ApiHeaderMap;
use http::HeaderName;
use http::HeaderValue;
use http::StatusCode;
use std::time::Duration;
use std::time::Instant;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::sync::oneshot::error::TryRecvError;
use tokio_tungstenite::tungstenite::Error;
use tokio_tungstenite::tungstenite::Message;
use tokio_util::sync::CancellationToken;
use tracing::instrument;
use tracing::trace;
use tracing::warn;

use crate::attestation::AttestationContext;
use crate::attestation::AttestationProvider;
use crate::attestation::X_OAI_ATTESTATION_HEADER;
use crate::client_common::Prompt;
use crate::client_common::ResponseEvent;
use crate::client_common::ResponseStream;
use crate::context::BaseInstructionsFragment;
use crate::context::ContextualUserFragment;
use crate::feedback_tags;
use crate::model_provider_policy::ModelProviderPolicyBegin;
use crate::model_provider_policy::ModelProviderPolicyContext;
use crate::model_provider_policy::ProviderAttemptOwner;
use crate::model_provider_policy::ProviderResponseTerminal;
use crate::model_provider_policy::ProviderRoutingHint;
use crate::model_provider_policy::ProviderWireSemantic;
use crate::model_provider_policy::active_model_provider_policies;
use crate::model_provider_policy::begin_active_model_provider_policy;
use crate::model_provider_policy::begin_model_provider_policy;
use crate::model_provider_policy::has_active_model_provider_policy;
use crate::model_provider_policy::logical_compaction_request;
use crate::model_provider_policy::logical_responses_request;
use crate::model_provider_policy::prepare_model_provider_attempt;
use crate::model_provider_policy::prepare_model_provider_policy;
use crate::model_provider_policy::provider_websocket_wire_payload;
use crate::model_provider_policy::resolve_ephemeral_model_input;
use crate::model_provider_policy::responses_lite_from_http_header;
use crate::model_provider_policy::responses_lite_from_ws_metadata;
use crate::responses_metadata::CodexResponsesMetadata;
use crate::responses_metadata::CodexResponsesRequestKind;
use crate::responses_metadata::subagent_header_value;
use crate::util::emit_feedback_auth_recovery_tags;
use codex_feedback::FeedbackRequestTags;
use codex_feedback::emit_feedback_request_tags_with_auth_env;
use codex_login::auth::AgentIdentityAuthPolicy;
use codex_login::auth_env_telemetry::AuthEnvTelemetry;
use codex_login::auth_env_telemetry::collect_auth_env_telemetry;
use codex_model_provider::AgentIdentitySessionFallback;
use codex_model_provider::ProviderAuthScope;
use codex_model_provider::ProviderUnauthorizedRecovery;
use codex_model_provider::SharedModelProvider;
use codex_model_provider::create_model_provider;
#[cfg(test)]
use codex_model_provider_info::DEFAULT_WEBSOCKET_CONNECT_TIMEOUT_MS;
use codex_model_provider_info::ModelProviderInfo;
use codex_model_provider_info::WireApi;
use codex_model_provider_info::provider_accepts_internal_chat_message_metadata;
use codex_protocol::error::CodexErr;
use codex_protocol::error::CodexErrorDetails;
use codex_protocol::error::Result;
use codex_protocol::error::RetryLimitReachedError;
use codex_protocol::error::UnexpectedResponseError;
use codex_protocol::error::UsageLimitReachedError;
use codex_response_debug_context::ResponseDebugContext;
use codex_response_debug_context::extract_response_debug_context;
use codex_response_debug_context::extract_response_debug_context_from_api_error;
use codex_response_debug_context::telemetry_api_error_message;
use codex_response_debug_context::telemetry_transport_error_message;

/// Host-owned gate invoked after the effective provider request is finalized
/// and immediately before a physical turn send may be attempted.
pub(crate) trait TurnRecoveryRequestCheckpoint: Send + Sync {
    fn authorize<'a>(&'a self, fingerprint_sha256: &'a str) -> BoxFuture<'a, Result<()>>;

    /// Called when the provider configuration cannot be reduced to a
    /// secret-free, exact recovery selector. A live request may still be sent
    /// after recovery is durably disabled for this generation; a cold recovery
    /// must reject the send.
    fn unavailable<'a>(
        &'a self,
        reason_code: &'a str,
        detail: &'a str,
    ) -> BoxFuture<'a, Result<()>>;
}

pub const OPENAI_BETA_HEADER: &str = "OpenAI-Beta";
pub const X_CODEX_INSTALLATION_ID_HEADER: &str = "x-codex-installation-id";
pub const X_CODEX_ROUTING_HINT_HEADER: &str = "x-codex-routing-hint";
pub const X_CODEX_TURN_STATE_HEADER: &str = "x-codex-turn-state";
pub const X_CODEX_TURN_METADATA_HEADER: &str = "x-codex-turn-metadata";
pub const X_CODEX_PARENT_THREAD_ID_HEADER: &str = "x-codex-parent-thread-id";
pub const X_CODEX_WINDOW_ID_HEADER: &str = "x-codex-window-id";
pub const X_OPENAI_MEMGEN_REQUEST_HEADER: &str = "x-openai-memgen-request";
pub const X_OPENAI_SUBAGENT_HEADER: &str = "x-openai-subagent";
pub const X_RESPONSESAPI_INCLUDE_TIMING_METRICS_HEADER: &str =
    "x-responsesapi-include-timing-metrics";
const X_CODEX_WS_STREAM_REQUEST_START_MS_CLIENT_METADATA_KEY: &str =
    "x-codex-ws-stream-request-start-ms";
const WS_REQUEST_HEADER_RESPONSES_LITE_CLIENT_METADATA_KEY: &str =
    "ws_request_header_x_openai_internal_codex_responses_lite";
const RESPONSES_WEBSOCKETS_V2_BETA_HEADER_VALUE: &str = "responses_websockets=2026-02-06";
const X_OPENAI_INTERNAL_CODEX_RESPONSES_LITE_HEADER: &str =
    "x-openai-internal-codex-responses-lite";
const REALTIME_CALLS_ENDPOINT: &str = "/realtime/calls";
const RESPONSES_ENDPOINT: &str = "/responses";
const RESPONSES_COMPACT_ENDPOINT: &str = "/responses/compact";
// `/responses/compact` is unary, so the timeout covers the full response rather than one idle
// period between stream events.
const COMPACT_REQUEST_TIMEOUT_IDLE_MULTIPLIER: u32 = 4;
const MEMORIES_SUMMARIZE_ENDPOINT: &str = "/memories/trace_summarize";

#[cfg(test)]
pub(crate) const WEBSOCKET_CONNECT_TIMEOUT: Duration =
    Duration::from_millis(DEFAULT_WEBSOCKET_CONNECT_TIMEOUT_MS);

pub(crate) struct CompactConversationRequestSettings {
    pub(crate) effort: Option<ReasoningEffortConfig>,
    pub(crate) summary: ReasoningSummaryConfig,
    pub(crate) service_tier: Option<String>,
}

fn reasoning_effort_for_request(effort: ReasoningEffortConfig) -> ReasoningEffortConfig {
    match effort {
        ReasoningEffortConfig::Ultra => ReasoningEffortConfig::Max,
        effort => effort,
    }
}

fn session_telemetry_for_request(
    session_telemetry: &SessionTelemetry,
    request: &ResponsesApiRequest,
) -> SessionTelemetry {
    session_telemetry.clone().with_inference_request(
        request.service_tier.as_deref(),
        request
            .reasoning
            .as_ref()
            .and_then(|reasoning| reasoning.effort.as_ref()),
    )
}

/// Session-scoped state shared by all [`ModelClient`] clones.
///
/// This is intentionally kept minimal so `ModelClient` does not need to hold a full `Config`. Most
/// configuration is per turn and is passed explicitly to streaming/unary methods.
#[derive(Debug)]
struct ModelClientState {
    thread_id: ThreadId,
    provider: SharedModelProvider,
    auth_env_telemetry: AuthEnvTelemetry,
    session_source: SessionSource,
    originator: String,
    model_verbosity: Option<VerbosityConfig>,
    content_item_kinds_enabled: bool,
    enable_request_compression: bool,
    include_timing_metrics: bool,
    beta_features_header: Option<String>,
    concurrent_reasoning_summaries_enabled: bool,
    include_attestation: bool,
    attestation_provider: Option<Arc<dyn AttestationProvider>>,
    disable_websockets: AtomicBool,
    agent_identity_session_fallback: AgentIdentitySessionFallback,
    cached_websocket_session: StdMutex<WebsocketSession>,
}

/// Resolved API client setup for a single request attempt.
///
/// Keeping this as a single bundle ensures prewarm and normal request paths
/// share the same auth/provider setup flow.
struct CurrentClientSetup {
    auth: Option<CodexAuth>,
    api_provider: ApiProvider,
    api_auth: SharedAuthProvider,
    agent_identity_telemetry: Option<AgentIdentityTelemetry>,
}

#[derive(Clone, Copy)]
struct RequestRouteTelemetry {
    endpoint: &'static str,
}

impl RequestRouteTelemetry {
    fn for_endpoint(endpoint: &'static str) -> Self {
        Self { endpoint }
    }
}

/// A session-scoped client for model-provider API calls.
///
/// This holds configuration and state that should be shared across turns within a Codex session
/// (auth, provider selection, thread id, and transport fallback state).
///
/// WebSocket fallback is session-scoped: once a turn activates the HTTP fallback, subsequent turns
/// will also use HTTP for the remainder of the session.
///
/// Turn-scoped settings (model selection, reasoning controls, telemetry context, and turn
/// metadata) are passed explicitly to the relevant methods to keep turn lifetime visible at the
/// call site.
#[derive(Debug, Clone)]
pub struct ModelClient {
    state: Arc<ModelClientState>,
    agent_identity_policy: AgentIdentityAuthPolicy,
    prompt_cache_key_override: Option<String>,
    http_client_factory: HttpClientFactory,
}

/// A turn-scoped streaming session created from a [`ModelClient`].
///
/// The session establishes a Responses WebSocket connection lazily and reuses it across multiple
/// requests within the turn. It also caches per-turn state:
///
/// - The last full request, so subsequent calls can reuse incremental websocket request payloads
///   only when the current request is an incremental extension of the previous one.
/// - The `x-codex-turn-state` sticky-routing token, which must be replayed for all requests within
///   the same turn.
///
/// Create a fresh `ModelClientSession` for each Codex turn. Reusing it across turns would replay
/// the previous turn's sticky-routing token into the next turn, which violates the client/server
/// contract and can cause routing bugs.
pub struct ModelClientSession {
    client: ModelClient,
    websocket_session: WebsocketSession,
    /// Turn state for sticky routing.
    ///
    /// This is an `OnceLock` that stores the turn state value received from the server
    /// on turn start via the `x-codex-turn-state` response header. Once set, this value
    /// should be sent back to the server in the `x-codex-turn-state` request header for
    /// all subsequent requests within the same turn to maintain sticky routing.
    ///
    /// This is a contract between the client and server: we receive it at turn start,
    /// keep sending it unchanged between turn requests (e.g., for retries, incremental
    /// appends, or continuation requests), and must not send it between different turns.
    turn_state: Arc<OnceLock<String>>,
}

#[derive(Debug, Clone)]
struct LastResponse {
    response_id: String,
    items_added: Vec<ResponseItem>,
}

#[derive(Debug, Default)]
struct WebsocketSession {
    connection: Option<ConnectedWebsocket>,
    last_request: Option<ResponsesApiRequest>,
    last_response_rx: Option<oneshot::Receiver<LastResponse>>,
    last_response_from_untraced_warmup: bool,
    connection_reused: StdMutex<bool>,
}

#[derive(Debug)]
struct ConnectedWebsocket {
    connection: ApiWebSocketConnection,
    /// Routing hint actually used for this connection's opening handshake.
    /// This remains sticky even if a later request desires a different hint.
    actual_routing_hint: Option<ProviderRoutingHint>,
    /// Exact provider setup used to open this socket. Secret-bearing values
    /// stay in memory and are never rendered by Debug/logging.
    identity: WebsocketConnectionIdentity,
}

#[derive(Clone, Eq, PartialEq)]
struct WebsocketConnectionIdentity {
    provider_name: String,
    base_url: String,
    query_params: BTreeMap<String, String>,
    headers: ApiHeaderMap,
    beta_features_header: Option<String>,
    compatibility_projection_json: Vec<u8>,
}

impl WebsocketConnectionIdentity {
    fn from_provider(
        provider: &ApiProvider,
        beta_features_header: Option<&str>,
        responses_metadata: &CodexResponsesMetadata,
    ) -> std::result::Result<Self, ApiError> {
        let compatibility_projection_json =
            serde_json::to_vec(&responses_metadata.turn_recovery_compatibility_projection())
                .map_err(|error| {
                    ApiError::Stream(format!(
                        "failed to bind websocket compatibility identity: {error}"
                    ))
                })?;
        Ok(Self {
            provider_name: provider.name.clone(),
            base_url: provider.base_url.clone(),
            query_params: provider
                .query_params
                .clone()
                .unwrap_or_default()
                .into_iter()
                .collect(),
            headers: provider.headers.clone(),
            beta_features_header: beta_features_header.map(str::to_string),
            compatibility_projection_json,
        })
    }
}

impl std::fmt::Debug for WebsocketConnectionIdentity {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("WebsocketConnectionIdentity")
            .field("provider_name", &self.provider_name)
            .field("base_url", &"[redacted]")
            .field("query_param_count", &self.query_params.len())
            .field("header_count", &self.headers.len())
            .field(
                "beta_features_present",
                &self.beta_features_header.is_some(),
            )
            .finish()
    }
}

struct AdmittedProviderAttempt {
    owner: ProviderAttemptOwner,
    dispatch: RequestDispatchMetadata,
}

impl AdmittedProviderAttempt {
    fn new(
        lease: Box<dyn codex_extension_api::ModelProviderAttemptLease>,
        dispatch: RequestDispatchMetadata,
    ) -> Self {
        Self {
            owner: ProviderAttemptOwner::new(lease, dispatch.clone()),
            dispatch,
        }
    }

    fn dispatch_metadata(&self) -> RequestDispatchMetadata {
        self.dispatch.clone()
    }

    fn into_owner(self) -> ProviderAttemptOwner {
        self.owner
    }

    async fn finish_immediate(
        self,
        http_status: Option<u16>,
        operation: &'static str,
    ) -> Result<()> {
        let terminal = if !self.dispatch.transport_invoked() {
            ModelProviderTerminal::NotDispatched {
                reason_code: format!("provider_{operation}_not_dispatched"),
            }
        } else if http_status == Some(StatusCode::UNAUTHORIZED.as_u16()) {
            ModelProviderTerminal::Rejected {
                reason_code: format!("provider_{operation}_unauthorized"),
            }
        } else {
            ModelProviderTerminal::Indeterminate {
                reason_code: format!("provider_{operation}_send_failed"),
                partial_response_sha256: None,
            }
        };
        self.owner
            .finish(terminal)
            .await
            .map_err(model_provider_policy_error)
    }
}

// This is intentionally not a `PartialEq` implementation: request equality includes `input` and
// `client_metadata`, while websocket reuse compares the input separately and ignores metadata.
// Keep the destructuring exhaustive so new request fields require an explicit reuse decision.
fn responses_request_properties_match(
    previous: &ResponsesApiRequest,
    current: &ResponsesApiRequest,
) -> bool {
    let ResponsesApiRequest {
        model: previous_model,
        instructions: previous_instructions,
        input: _,
        tools: previous_tools,
        tool_choice: previous_tool_choice,
        parallel_tool_calls: previous_parallel_tool_calls,
        reasoning: previous_reasoning,
        store: previous_store,
        stream: previous_stream,
        stream_options: _,
        include: previous_include,
        service_tier: previous_service_tier,
        prompt_cache_key: previous_prompt_cache_key,
        text: previous_text,
        client_metadata: _,
    } = previous;
    let ResponsesApiRequest {
        model: current_model,
        instructions: current_instructions,
        input: _,
        tools: current_tools,
        tool_choice: current_tool_choice,
        parallel_tool_calls: current_parallel_tool_calls,
        reasoning: current_reasoning,
        store: current_store,
        stream: current_stream,
        stream_options: _,
        include: current_include,
        service_tier: current_service_tier,
        prompt_cache_key: current_prompt_cache_key,
        text: current_text,
        client_metadata: _,
    } = current;

    previous_model == current_model
        && previous_instructions == current_instructions
        && previous_tools == current_tools
        && previous_tool_choice == current_tool_choice
        && previous_parallel_tool_calls == current_parallel_tool_calls
        && previous_reasoning == current_reasoning
        && previous_store == current_store
        && previous_stream == current_stream
        // Stream options control delivery for this response, not the context
        // referenced by `previous_response_id`.
        && previous_include == current_include
        && previous_service_tier == current_service_tier
        && previous_prompt_cache_key == current_prompt_cache_key
        && previous_text == current_text
}

fn response_items_equal_ignoring_internal_metadata(
    previous: &ResponseItem,
    current: &ResponseItem,
) -> bool {
    if previous == current {
        return true;
    }

    let mut previous = previous.clone();
    previous.clear_internal_chat_message_metadata_passthrough();
    let mut current = current.clone();
    current.clear_internal_chat_message_metadata_passthrough();
    previous == current
}

impl WebsocketSession {
    fn set_connection_reused(&self, connection_reused: bool) {
        *self
            .connection_reused
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = connection_reused;
    }

    fn connection_reused(&self) -> bool {
        *self
            .connection_reused
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

enum WebsocketStreamOutcome {
    Stream(ResponseStream),
    FallbackToHttp,
}

fn has_active_ephemeral_model_input_contributor(context: &ModelProviderPolicyContext<'_>) -> bool {
    context.request_kind == ModelProviderRequestKind::Turn
        && context
            .registry
            .ephemeral_model_input_contributors()
            .iter()
            .any(|contributor| contributor.is_active(context.thread_store, context.turn_store))
}

/// Result of opening a WebRTC Realtime call.
///
/// The SDP answer goes back to the client. The call id and auth headers stay on the server so the
/// ordinary Realtime WebSocket machinery can join the same in-progress call as a sideband
/// controller.
pub(crate) struct RealtimeWebrtcCallStart {
    pub(crate) sdp: String,
    pub(crate) call_id: String,
    pub(crate) sideband_headers: ApiHeaderMap,
}

/// Reuses the API-auth material that created the WebRTC call for the sideband WebSocket join.
///
/// API-key sessions send that API bearer. ChatGPT-auth sessions send their bearer plus account id;
/// transceiver is responsible for accepting that same call-create identity on the direct
/// `api.openai.com` sideband path.
fn sideband_websocket_auth_headers(api_auth: &dyn AuthProvider) -> ApiHeaderMap {
    let mut headers = ApiHeaderMap::new();
    api_auth.add_auth_headers(&mut headers);
    headers
}

impl ModelClient {
    #[allow(clippy::too_many_arguments)]
    /// Creates a new session-scoped `ModelClient`.
    ///
    /// All arguments are expected to be stable for the lifetime of a Codex session. Per-turn values
    /// are passed explicitly to `ModelClientSession` turn-scoped methods. The HTTP client factory
    /// must come from the effective session configuration so every transport observes the resolved
    /// outbound proxy policy.
    pub fn new(
        auth_manager: Option<Arc<AuthManager>>,
        agent_identity_policy: AgentIdentityAuthPolicy,
        thread_id: ThreadId,
        provider_info: ModelProviderInfo,
        session_source: SessionSource,
        originator: String,
        model_verbosity: Option<VerbosityConfig>,
        content_item_kinds_enabled: bool,
        enable_request_compression: bool,
        include_timing_metrics: bool,
        beta_features_header: Option<String>,
        concurrent_reasoning_summaries_enabled: bool,
        attestation_provider: Option<Arc<dyn AttestationProvider>>,
        http_client_factory: HttpClientFactory,
    ) -> Self {
        let model_provider = create_model_provider(provider_info, auth_manager);
        let codex_api_key_env_enabled = model_provider
            .auth_manager()
            .as_ref()
            .is_some_and(|manager| manager.codex_api_key_env_enabled());
        let auth_env_telemetry =
            collect_auth_env_telemetry(model_provider.info(), codex_api_key_env_enabled);
        let include_attestation = model_provider.supports_attestation();
        Self {
            state: Arc::new(ModelClientState {
                thread_id,
                provider: model_provider,
                auth_env_telemetry,
                session_source,
                originator,
                model_verbosity,
                content_item_kinds_enabled,
                enable_request_compression,
                include_timing_metrics,
                beta_features_header,
                concurrent_reasoning_summaries_enabled,
                include_attestation,
                attestation_provider,
                disable_websockets: AtomicBool::new(false),
                agent_identity_session_fallback: AgentIdentitySessionFallback::default(),
                cached_websocket_session: StdMutex::new(WebsocketSession::default()),
            }),
            agent_identity_policy,
            prompt_cache_key_override: None,
            http_client_factory,
        }
    }

    pub(crate) fn with_prompt_cache_key_override(
        mut self,
        prompt_cache_key_override: Option<String>,
    ) -> Self {
        self.prompt_cache_key_override = prompt_cache_key_override;
        self
    }

    fn prompt_cache_key(&self, responses_metadata: &CodexResponsesMetadata) -> String {
        if let Some(prompt_cache_key) = &self.prompt_cache_key_override {
            return prompt_cache_key.clone();
        }

        if let SessionSource::Internal(source) = &self.state.session_source
            && let Some(parent_thread_id) = responses_metadata.parent_thread_id
        {
            return format!("{source}:{parent_thread_id}");
        }

        responses_metadata.session_id.clone()
    }

    /// Creates a fresh turn-scoped streaming session.
    ///
    /// This constructor does not perform network I/O itself; the session opens a websocket lazily
    /// when the first stream request is issued.
    pub fn new_session(&self) -> ModelClientSession {
        ModelClientSession {
            client: self.clone(),
            websocket_session: self.take_cached_websocket_session(),
            turn_state: Arc::new(OnceLock::new()),
        }
    }

    pub(crate) fn auth_manager(&self) -> Option<Arc<AuthManager>> {
        self.state.provider.auth_manager()
    }

    fn take_cached_websocket_session(&self) -> WebsocketSession {
        let mut cached_websocket_session = self
            .state
            .cached_websocket_session
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        std::mem::take(&mut *cached_websocket_session)
    }

    fn store_cached_websocket_session(&self, websocket_session: WebsocketSession) {
        *self
            .state
            .cached_websocket_session
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = websocket_session;
    }

    pub(crate) fn force_http_fallback(
        &self,
        session_telemetry: &SessionTelemetry,
        _model_info: &ModelInfo,
    ) -> bool {
        let websocket_enabled = self.responses_websocket_enabled();
        let activated =
            websocket_enabled && !self.state.disable_websockets.swap(true, Ordering::Relaxed);
        if activated {
            warn!("falling back to HTTP");
            session_telemetry.counter(
                "codex.transport.fallback_to_http",
                /*inc*/ 1,
                &[("from_wire_api", "responses_websocket")],
            );
        }

        self.store_cached_websocket_session(WebsocketSession::default());
        activated
    }

    /// Compacts the current conversation history using the Compact endpoint.
    ///
    /// This is a unary call (no streaming) that returns a new list of
    /// `ResponseItem`s representing the compacted transcript.
    ///
    /// The model selection and telemetry context are passed explicitly to keep `ModelClient`
    /// session-scoped.
    #[allow(clippy::too_many_arguments)]
    pub(crate) async fn compact_conversation_history(
        &self,
        prompt: &Prompt,
        model_info: &ModelInfo,
        turn_state: Option<Arc<OnceLock<String>>>,
        settings: CompactConversationRequestSettings,
        session_telemetry: &SessionTelemetry,
        compaction_trace: &CompactionTraceContext,
        responses_metadata: &CodexResponsesMetadata,
        provider_policy_context: Option<&ModelProviderPolicyContext<'_>>,
    ) -> Result<Vec<ResponseItem>> {
        if prompt.input.is_empty() {
            return Ok(Vec::new());
        }
        let client_setup = self.current_client_setup().await?;
        let active_provider_policy_context = provider_policy_context.filter(|context| {
            has_active_model_provider_policy(context.registry, context.thread_store)
        });
        let transport = if active_provider_policy_context.is_some() {
            self.build_sensitive_api_transport(
                &client_setup.api_provider,
                RESPONSES_COMPACT_ENDPOINT,
            )?
        } else {
            self.build_api_transport(&client_setup.api_provider, RESPONSES_COMPACT_ENDPOINT)?
        };
        let request_telemetry = Self::build_request_telemetry(
            session_telemetry,
            AuthRequestTelemetryContext::new(
                client_setup.auth.as_ref().map(CodexAuth::auth_mode),
                client_setup.api_auth.as_ref(),
                client_setup.agent_identity_telemetry.clone(),
                PendingUnauthorizedRetry::default(),
            ),
            RequestRouteTelemetry::for_endpoint(RESPONSES_COMPACT_ENDPOINT),
            self.state.auth_env_telemetry.clone(),
        );
        let request = self.build_responses_request(
            prompt,
            model_info,
            settings.effort,
            settings.summary,
            settings.service_tier,
            responses_metadata,
            &client_setup.api_provider,
        )?;
        let ResponsesApiRequest {
            model,
            instructions,
            mut input,
            tools,
            parallel_tool_calls,
            reasoning,
            service_tier,
            prompt_cache_key,
            text,
            ..
        } = request;
        self.prepare_response_items_for_request(&mut input, &client_setup.api_provider);
        let payload = ApiCompactionInput {
            model: &model,
            input: &input,
            instructions: &instructions,
            tools,
            parallel_tool_calls,
            reasoning,
            service_tier: service_tier.as_deref(),
            prompt_cache_key: prompt_cache_key.as_deref(),
            text,
        };

        let mut extra_headers = ApiHeaderMap::new();
        if let Ok(header_value) = HeaderValue::from_str(&responses_metadata.installation_id) {
            extra_headers.insert(X_CODEX_INSTALLATION_ID_HEADER, header_value);
        }
        extra_headers.extend(build_responses_headers(
            self.state.beta_features_header.as_deref(),
            turn_state.as_ref(),
        ));
        add_originator_header(&mut extra_headers, self.state.originator.as_str());
        extra_headers.extend(self.build_responses_compatibility_headers(responses_metadata));
        extra_headers.extend(build_session_headers(
            Some(responses_metadata.session_id.to_string()),
            Some(responses_metadata.thread_id.to_string()),
        ));
        if let Some(header_value) = self.generate_attestation_header_for().await {
            extra_headers.insert(X_OAI_ATTESTATION_HEADER, header_value);
        }
        if let Some(header_value) = self.build_routing_hint_header(
            client_setup.auth.as_ref(),
            &model,
            service_tier.as_deref(),
        ) {
            extra_headers.insert(X_CODEX_ROUTING_HINT_HEADER, header_value);
        }
        add_responses_lite_header(&mut extra_headers, model_info.use_responses_lite);
        let compact_request_timeout = client_setup
            .api_provider
            .stream_idle_timeout
            .saturating_mul(COMPACT_REQUEST_TIMEOUT_IDLE_MULTIPLIER);
        let retry_config = client_setup.api_provider.retry.clone();
        let provider_id = client_setup.api_provider.name.clone();
        let endpoint = client_setup
            .api_provider
            .url_for_path(RESPONSES_COMPACT_ENDPOINT);
        let client =
            ApiCompactClient::new(transport, client_setup.api_provider, client_setup.api_auth)
                .with_telemetry(Some(request_telemetry));
        let trace_attempt = compaction_trace.start_attempt(&payload);
        let Some(provider_policy_context) = active_provider_policy_context else {
            let result = client
                .compact_input(
                    &payload,
                    extra_headers,
                    compact_request_timeout,
                    turn_state.as_deref(),
                )
                .await
                .map_err(|error| self.state.provider.map_api_error(error));
            trace_attempt.record_result(result.as_deref());
            return result;
        };

        let routing_hint =
            ProviderRoutingHint::from_header(extra_headers.get(X_CODEX_ROUTING_HINT_HEADER))
                .map_err(|error| trace_compaction_policy_error(&trace_attempt, error))?;
        let responses_lite = responses_lite_from_http_header(
            extra_headers.get(X_OPENAI_INTERNAL_CODEX_RESPONSES_LITE_HEADER),
        )
        .map_err(|error| trace_compaction_policy_error(&trace_attempt, error))?;
        let logical_request = logical_compaction_request(&payload);

        for retry_index in 0..=retry_config.max_attempts {
            let wire_semantic =
                ProviderWireSemantic::new(&payload, routing_hint.as_ref(), responses_lite);
            let prepared = prepare_model_provider_policy(
                provider_policy_context,
                provider_id.as_str(),
                model.as_str(),
                ModelProviderTransport::Http,
                endpoint.as_str(),
                &logical_request,
                &wire_semantic,
                /*previous_response_id*/ None,
                /*generate*/ true,
            )
            .map_err(|error| trace_compaction_policy_error(&trace_attempt, error))?;
            let mut admitted_provider_attempt = match begin_model_provider_policy(
                provider_policy_context.registry,
                prepared.invocation_input(provider_policy_context),
            )
            .await
            .map_err(|error| trace_compaction_policy_error(&trace_attempt, error))?
            {
                ModelProviderPolicyBegin::NoPolicy => None,
                ModelProviderPolicyBegin::Allow { lease } => {
                    let dispatch = provider_http_dispatch_metadata(&extra_headers);
                    Some(AdmittedProviderAttempt::new(lease, dispatch))
                }
                ModelProviderPolicyBegin::Block {
                    reason_code,
                    message,
                } => {
                    let error = model_provider_policy_blocked(reason_code, message);
                    trace_attempt.record_failed(&error);
                    return Err(error);
                }
            };
            let dispatch_metadata = admitted_provider_attempt
                .as_ref()
                .map(AdmittedProviderAttempt::dispatch_metadata)
                .unwrap_or_default();
            let result = client
                .compact_input_single_attempt(
                    &payload,
                    extra_headers.clone(),
                    compact_request_timeout,
                    turn_state.as_deref(),
                    dispatch_metadata,
                )
                .await;

            match result {
                Ok(output) => {
                    let mut terminal = ProviderResponseTerminal::new(
                        admitted_provider_attempt
                            .take()
                            .map(AdmittedProviderAttempt::into_owner),
                    );
                    if let Err(error) = terminal.finish_completed_unary(&output).await {
                        let error = model_provider_policy_error(error);
                        trace_attempt.record_failed(&error);
                        return Err(error);
                    }
                    trace_attempt.record_completed(&output);
                    return Ok(output);
                }
                Err(error) => {
                    if let Some(attempt) = admitted_provider_attempt.take()
                        && let Err(terminal_error) = attempt
                            .finish_immediate(api_error_http_status(&error), "http")
                            .await
                    {
                        trace_attempt.record_failed(&terminal_error);
                        return Err(terminal_error);
                    }
                    let retry_delay = match &error {
                        ApiError::Transport(transport_error) => {
                            retry_config.retry_delay_after_error(transport_error, retry_index)
                        }
                        _ => None,
                    };
                    if let Some(delay) = retry_delay {
                        tokio::time::sleep(delay).await;
                        continue;
                    }
                    let error = self.state.provider.map_api_error(error);
                    trace_attempt.record_failed(&error);
                    return Err(error);
                }
            }
        }
        unreachable!("provider retry budget must terminate the governed compaction loop")
    }

    pub(crate) async fn create_realtime_call_with_headers(
        &self,
        sdp: String,
        session_config: ApiRealtimeSessionConfig,
        mut extra_headers: ApiHeaderMap,
        api_provider_override: Option<ApiProvider>,
    ) -> Result<RealtimeWebrtcCallStart> {
        // Create the media call over HTTP first, then retain matching auth so realtime can attach
        // the server-side control WebSocket to the call id from that HTTP response.
        let client_setup = self.current_client_setup().await?;
        if let Some(header_value) = self.generate_attestation_header_for().await {
            extra_headers.insert(X_OAI_ATTESTATION_HEADER, header_value);
        }
        let mut sideband_headers = extra_headers.clone();
        sideband_headers.extend(sideband_websocket_auth_headers(
            client_setup.api_auth.as_ref(),
        ));
        let api_provider = api_provider_override.unwrap_or(client_setup.api_provider);
        let transport = self.build_api_transport(&api_provider, REALTIME_CALLS_ENDPOINT)?;
        let response = ApiRealtimeCallClient::new(transport, api_provider, client_setup.api_auth)
            .create_with_session_and_headers(sdp, session_config, extra_headers)
            .await
            .map_err(|error| self.state.provider.map_api_error(error))?;
        Ok(RealtimeWebrtcCallStart {
            sdp: response.sdp,
            call_id: response.call_id,
            sideband_headers,
        })
    }

    pub(crate) async fn realtime_sideband_headers(
        &self,
        mut extra_headers: ApiHeaderMap,
    ) -> Result<ApiHeaderMap> {
        let client_setup = self.current_client_setup().await?;
        if let Some(header_value) = self.generate_attestation_header_for().await {
            extra_headers.insert(X_OAI_ATTESTATION_HEADER, header_value);
        }
        extra_headers.extend(sideband_websocket_auth_headers(
            client_setup.api_auth.as_ref(),
        ));
        Ok(extra_headers)
    }

    /// Builds memory summaries for each provided normalized raw memory.
    ///
    /// This is a unary call (no streaming) to `/v1/memories/trace_summarize`.
    ///
    /// The model selection, reasoning effort, and telemetry context are passed explicitly to keep
    /// `ModelClient` session-scoped.
    pub async fn summarize_memories(
        &self,
        raw_memories: Vec<ApiRawMemory>,
        model_info: &ModelInfo,
        effort: Option<ReasoningEffortConfig>,
        session_telemetry: &SessionTelemetry,
    ) -> Result<Vec<ApiMemorySummarizeOutput>> {
        if raw_memories.is_empty() {
            return Ok(Vec::new());
        }

        let client_setup = self.current_client_setup().await?;
        let transport =
            self.build_api_transport(&client_setup.api_provider, MEMORIES_SUMMARIZE_ENDPOINT)?;
        let request_telemetry = Self::build_request_telemetry(
            session_telemetry,
            AuthRequestTelemetryContext::new(
                client_setup.auth.as_ref().map(CodexAuth::auth_mode),
                client_setup.api_auth.as_ref(),
                client_setup.agent_identity_telemetry.clone(),
                PendingUnauthorizedRetry::default(),
            ),
            RequestRouteTelemetry::for_endpoint(MEMORIES_SUMMARIZE_ENDPOINT),
            self.state.auth_env_telemetry.clone(),
        );
        let client =
            ApiMemoriesClient::new(transport, client_setup.api_provider, client_setup.api_auth)
                .with_telemetry(Some(request_telemetry));

        let payload = ApiMemorySummarizeInput {
            model: model_info.slug.clone(),
            raw_memories,
            reasoning: effort
                .map(reasoning_effort_for_request)
                .map(|effort| Reasoning {
                    effort: Some(effort),
                    summary: None,
                    context: None,
                }),
        };

        client
            .summarize_input(&payload, self.build_subagent_headers())
            .await
            .map_err(|error| self.state.provider.map_api_error(error))
    }

    fn build_subagent_headers(&self) -> ApiHeaderMap {
        let mut extra_headers = ApiHeaderMap::new();
        add_originator_header(&mut extra_headers, self.state.originator.as_str());
        if let Some(subagent) = subagent_header_value(&self.state.session_source)
            && let Ok(val) = HeaderValue::from_str(&subagent)
        {
            extra_headers.insert(X_OPENAI_SUBAGENT_HEADER, val);
        }
        if matches!(
            self.state.session_source,
            SessionSource::Internal(InternalSessionSource::MemoryConsolidation)
        ) {
            extra_headers.insert(
                X_OPENAI_MEMGEN_REQUEST_HEADER,
                HeaderValue::from_static("true"),
            );
        }
        extra_headers
    }

    fn build_responses_compatibility_headers(
        &self,
        responses_metadata: &CodexResponsesMetadata,
    ) -> ApiHeaderMap {
        let mut extra_headers = responses_metadata.compatibility_headers();
        if matches!(
            self.state.session_source,
            SessionSource::Internal(InternalSessionSource::MemoryConsolidation)
        ) {
            extra_headers.insert(
                X_OPENAI_MEMGEN_REQUEST_HEADER,
                HeaderValue::from_static("true"),
            );
        }
        extra_headers
    }

    fn build_ws_client_metadata(
        &self,
        responses_metadata: &CodexResponsesMetadata,
        use_responses_lite: bool,
    ) -> HashMap<String, String> {
        let mut client_metadata = responses_metadata.client_metadata();
        if use_responses_lite {
            client_metadata.insert(
                WS_REQUEST_HEADER_RESPONSES_LITE_CLIENT_METADATA_KEY.to_string(),
                "true".to_string(),
            );
        }
        client_metadata
    }

    async fn generate_attestation_header_for(&self) -> Option<HeaderValue> {
        if !self.state.include_attestation {
            return None;
        }

        self.state
            .attestation_provider
            .as_ref()?
            .header_for_request(AttestationContext {
                thread_id: self.state.thread_id,
            })
            .await
    }

    /// Builds request telemetry for unary API calls (e.g., Compact endpoint).
    fn build_request_telemetry(
        session_telemetry: &SessionTelemetry,
        auth_context: AuthRequestTelemetryContext,
        request_route_telemetry: RequestRouteTelemetry,
        auth_env_telemetry: AuthEnvTelemetry,
    ) -> Arc<dyn RequestTelemetry> {
        let telemetry = Arc::new(ApiTelemetry::new(
            session_telemetry.clone(),
            auth_context,
            request_route_telemetry,
            auth_env_telemetry,
            /*redact_provider_diagnostics*/ false,
        ));
        let request_telemetry: Arc<dyn RequestTelemetry> = telemetry;
        request_telemetry
    }

    fn build_reasoning(
        model_info: &ModelInfo,
        effort: Option<ReasoningEffortConfig>,
        summary: ReasoningSummaryConfig,
    ) -> Reasoning {
        Reasoning {
            effort: effort
                .or_else(|| model_info.default_reasoning_level.clone())
                .map(reasoning_effort_for_request),
            summary: (model_info.supports_reasoning_summary_parameter
                && summary != ReasoningSummaryConfig::None)
                .then_some(summary),
            // When Responses Lite is disabled, omit context so Responses uses the default,
            // which is currently `current_turn`.
            context: model_info
                .use_responses_lite
                .then_some(ReasoningContext::AllTurns),
        }
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "the request builder mirrors independent provider protocol fields"
    )]
    fn build_responses_request(
        &self,
        prompt: &Prompt,
        model_info: &ModelInfo,
        effort: Option<ReasoningEffortConfig>,
        summary: ReasoningSummaryConfig,
        service_tier: Option<String>,
        responses_metadata: &CodexResponsesMetadata,
        api_provider: &ApiProvider,
    ) -> Result<ResponsesApiRequest> {
        let mut input = prompt.get_formatted_input_for_request(model_info.use_responses_lite);
        let is_openai = self.state.provider.info().is_openai();
        let (instructions, tools) = if model_info.use_responses_lite {
            let tools = if self.state.provider.capabilities().namespace_tools {
                create_tools_json_for_responses_lite(&prompt.tools)?
            } else {
                create_tools_json_for_responses_api(&prompt.tools)?
            };
            let mut prefix = vec![ResponseItem::AdditionalTools {
                id: None,
                role: "developer".to_string(),
                tools,
            }];
            if !prompt.base_instructions.text.is_empty() {
                prefix.push(ContextualUserFragment::into(BaseInstructionsFragment(
                    prompt.base_instructions.text.clone(),
                )));
            }
            input.splice(0..0, prefix);
            (String::new(), None)
        } else {
            (
                prompt.base_instructions.text.clone(),
                Some(create_tools_raw_json_for_responses_api(&prompt.tools)?.into()),
            )
        };
        if !is_openai {
            for item in &mut input {
                if let ResponseItem::FunctionCall {
                    encrypted_function_args,
                    ..
                } = item
                {
                    *encrypted_function_args = None;
                }
            }
        }
        if !provider_accepts_internal_chat_message_metadata(&api_provider.base_url) {
            for item in &mut input {
                item.clear_internal_chat_message_metadata_passthrough();
            }
        }
        let reasoning = Self::build_reasoning(model_info, effort, summary);
        let stream_options = (self.state.concurrent_reasoning_summaries_enabled
            && is_openai
            && reasoning.summary.is_some())
        .then_some(StreamOptions {
            reasoning_summary_delivery: codex_api::ReasoningSummaryDelivery::SequentialCutoff,
        });
        let include = vec!["reasoning.encrypted_content".to_string()];
        let verbosity = if model_info.support_verbosity {
            self.state.model_verbosity.or(model_info.default_verbosity)
        } else {
            if self.state.model_verbosity.is_some() {
                warn!(
                    "model_verbosity is set but ignored as the model does not support verbosity: {}",
                    model_info.slug
                );
            }
            None
        };
        let text = create_text_param_for_request(
            verbosity,
            &prompt.output_schema,
            prompt.output_schema_strict,
        );
        let prompt_cache_key = Some(self.prompt_cache_key(responses_metadata));
        let service_tier = model_info.service_tier_for_request(service_tier);
        let request = ResponsesApiRequest {
            model: model_info.slug.clone(),
            instructions,
            input,
            tools,
            tool_choice: "auto".to_string(),
            parallel_tool_calls: prompt.parallel_tool_calls && !model_info.use_responses_lite,
            reasoning: Some(reasoning),
            store: false,
            stream: true,
            stream_options,
            include,
            service_tier,
            prompt_cache_key,
            text,
            client_metadata: Some(responses_metadata.client_metadata()),
        };
        Ok(request)
    }

    fn prepare_response_items_for_request(
        &self,
        input: &mut [ResponseItem],
        api_provider: &ApiProvider,
    ) {
        let strip_internal_metadata =
            !provider_accepts_internal_chat_message_metadata(&api_provider.base_url);
        for item in input {
            if item.id().is_some_and(|id| !id.is_prefixed()) {
                item.set_id(/*new_id*/ None);
            }
            if strip_internal_metadata {
                // The ChatGPT Codex backend does not accept Hepta's local
                // content classification metadata on the wire. Keep it in
                // durable history, but strip it from this provider-specific
                // request copy immediately before serialization.
                item.clear_internal_chat_message_metadata_passthrough();
            }
            if !self.state.content_item_kinds_enabled {
                item.clear_content_item_kinds();
            }
        }
    }

    /// Returns whether the Responses-over-WebSocket transport is active for this session.
    ///
    /// WebSocket use is controlled by provider capability and session-scoped fallback state.
    pub fn responses_websocket_enabled(&self) -> bool {
        if !self.state.provider.info().supports_websockets
            || self.state.disable_websockets.load(Ordering::Relaxed)
        {
            return false;
        }

        true
    }

    /// Returns auth + provider configuration resolved from the current session auth state.
    ///
    /// This centralizes setup used by both prewarm and normal request paths so they stay in
    /// lockstep when auth/provider resolution changes.
    async fn current_client_setup(&self) -> Result<CurrentClientSetup> {
        let auth = self.state.provider.auth().await;
        let api_provider = self.state.provider.api_provider().await?;
        let resolved_auth = self
            .state
            .provider
            .api_auth_for_scope(ProviderAuthScope {
                agent_identity_policy: self.agent_identity_policy,
                session_source: self.state.session_source.clone(),
                agent_identity_session_fallback: self.state.agent_identity_session_fallback.clone(),
            })
            .await?;
        Ok(CurrentClientSetup {
            auth,
            api_provider,
            api_auth: resolved_auth.auth,
            agent_identity_telemetry: resolved_auth.agent_identity_telemetry,
        })
    }

    fn build_routing_hint_header(
        &self,
        auth: Option<&CodexAuth>,
        model: &str,
        service_tier: Option<&str>,
    ) -> Option<HeaderValue> {
        let provider = self.state.provider.info();
        if !auth.is_some_and(CodexAuth::uses_codex_backend)
            || !provider.is_openai()
            || !provider.requires_openai_auth
            || provider.env_key.is_some()
            || provider.experimental_bearer_token.is_some()
            || provider.auth.is_some()
            || provider.aws.is_some()
        {
            return None;
        }

        let routing_hint = match service_tier {
            Some(tier) => format!("model={model};tier={tier}"),
            None => format!("model={model}"),
        };
        HeaderValue::from_str(&routing_hint).ok()
    }

    fn build_api_transport(
        &self,
        api_provider: &ApiProvider,
        endpoint: &str,
    ) -> Result<ReqwestTransport> {
        let request_url = api_provider.url_for_path(endpoint);
        let client = create_client_for_route(
            &self.http_client_factory,
            &request_url,
            ClientRouteClass::Api,
        )
        .map_err(std::io::Error::from)?;
        Ok(ReqwestTransport::from_http_client(client))
    }

    fn build_sensitive_api_transport(
        &self,
        api_provider: &ApiProvider,
        endpoint: &str,
    ) -> Result<ReqwestTransport> {
        let request_url = api_provider.url_for_path(endpoint);
        let client = create_client_for_sensitive_route(
            &self.http_client_factory,
            &request_url,
            ClientRouteClass::Api,
        )
        .map_err(std::io::Error::from)?;
        Ok(ReqwestTransport::from_http_client(client))
    }

    pub(crate) async fn prewarm_auth(&self) -> Result<()> {
        self.current_client_setup().await.map(|_| ())
    }

    /// Opens a websocket connection using the same header and telemetry wiring as normal turns.
    ///
    /// Both startup prewarm and in-turn `needs_new` reconnects call this path so handshake
    /// behavior remains consistent across both flows.
    #[allow(clippy::too_many_arguments)]
    #[inline(never)]
    fn connect_websocket_future<'a>(
        &'a self,
        session_telemetry: &'a SessionTelemetry,
        api_provider: codex_api::Provider,
        api_auth: SharedAuthProvider,
        responses_metadata: &'a CodexResponsesMetadata,
        auth_context: AuthRequestTelemetryContext,
        request_route_telemetry: RequestRouteTelemetry,
    ) -> BoxFuture<'a, std::result::Result<ConnectedWebsocket, ApiError>> {
        self.connect_websocket(
            session_telemetry,
            api_provider,
            api_auth,
            responses_metadata,
            auth_context,
            request_route_telemetry,
        )
        .boxed()
    }

    #[allow(clippy::too_many_arguments)]
    async fn connect_websocket(
        &self,
        session_telemetry: &SessionTelemetry,
        api_provider: codex_api::Provider,
        api_auth: SharedAuthProvider,
        responses_metadata: &CodexResponsesMetadata,
        auth_context: AuthRequestTelemetryContext,
        request_route_telemetry: RequestRouteTelemetry,
    ) -> std::result::Result<ConnectedWebsocket, ApiError> {
        let identity = WebsocketConnectionIdentity::from_provider(
            &api_provider,
            self.state.beta_features_header.as_deref(),
            responses_metadata,
        )?;
        let headers = self.build_websocket_headers(responses_metadata).await;
        let websocket_telemetry = ModelClientSession::build_websocket_telemetry(
            session_telemetry,
            auth_context.clone(),
            request_route_telemetry,
            self.state.auth_env_telemetry.clone(),
        );
        let websocket_connect_timeout = self.state.provider.info().websocket_connect_timeout();
        let start = Instant::now();
        let websocket_client = ApiWebSocketResponsesClient::new(api_provider, api_auth);
        let websocket_connect = websocket_client
            .connect(
                &self.http_client_factory,
                headers,
                codex_login::default_client::default_headers(),
                /*turn_state*/ None,
                Some(websocket_telemetry),
            )
            .boxed();
        let result = match tokio::time::timeout(websocket_connect_timeout, websocket_connect).await
        {
            Ok(result) => result,
            Err(_) => Err(ApiError::Transport(TransportError::Timeout)),
        };
        let error_message = result.as_ref().err().map(telemetry_api_error_message);
        let response_debug = result
            .as_ref()
            .err()
            .map(extract_response_debug_context_from_api_error)
            .unwrap_or_default();
        let status = result.as_ref().err().and_then(api_error_http_status);
        session_telemetry.record_websocket_connect(
            start.elapsed(),
            status,
            error_message.as_deref(),
            auth_context.auth_header_attached,
            auth_context.auth_header_name,
            auth_context.retry_after_unauthorized,
            auth_context.recovery_mode,
            auth_context.recovery_phase,
            request_route_telemetry.endpoint,
            /*connection_reused*/ false,
            response_debug.request_id.as_deref(),
            response_debug.cf_ray.as_deref(),
            response_debug.auth_error.as_deref(),
            response_debug.auth_error_code.as_deref(),
            auth_context.agent_identity_telemetry(),
        );
        emit_feedback_request_tags_with_auth_env(
            &FeedbackRequestTags {
                endpoint: request_route_telemetry.endpoint,
                auth_header_attached: auth_context.auth_header_attached,
                auth_header_name: auth_context.auth_header_name,
                auth_mode: auth_context.auth_mode,
                auth_retry_after_unauthorized: Some(auth_context.retry_after_unauthorized),
                auth_recovery_mode: auth_context.recovery_mode,
                auth_recovery_phase: auth_context.recovery_phase,
                auth_connection_reused: Some(false),
                auth_request_id: response_debug.request_id.as_deref(),
                auth_cf_ray: response_debug.cf_ray.as_deref(),
                auth_error: response_debug.auth_error.as_deref(),
                auth_error_code: response_debug.auth_error_code.as_deref(),
                auth_recovery_followup_success: auth_context
                    .retry_after_unauthorized
                    .then_some(result.is_ok()),
                auth_recovery_followup_status: auth_context
                    .retry_after_unauthorized
                    .then_some(status)
                    .flatten(),
            },
            &self.state.auth_env_telemetry,
        );
        result.and_then(|connection| {
            let actual_routing_hint = ProviderRoutingHint::from_header(connection.routing_hint())
                .map_err(|error| {
                ApiError::Stream(format!(
                    "failed to bind websocket routing hint [{}]: {}",
                    error.reason_code(),
                    error.detail()
                ))
            })?;
            Ok(ConnectedWebsocket {
                connection,
                actual_routing_hint,
                identity,
            })
        })
    }

    /// Builds websocket handshake headers for both prewarm and turn-time reconnect.
    async fn build_websocket_headers(
        &self,
        responses_metadata: &CodexResponsesMetadata,
    ) -> ApiHeaderMap {
        let mut headers = build_responses_headers(
            self.state.beta_features_header.as_deref(),
            /*turn_state*/ None,
        );
        add_originator_header(&mut headers, self.state.originator.as_str());
        if let Ok(header_value) = HeaderValue::from_str(&responses_metadata.thread_id) {
            headers.insert("x-client-request-id", header_value);
        }
        headers.extend(build_session_headers(
            Some(responses_metadata.session_id.to_string()),
            Some(responses_metadata.thread_id.to_string()),
        ));
        headers.extend(self.build_responses_compatibility_headers(responses_metadata));
        if let Some(routing_hint) = &responses_metadata.routing_hint {
            headers.insert(X_CODEX_ROUTING_HINT_HEADER, routing_hint.clone());
        }
        if let Some(header_value) = self.generate_attestation_header_for().await {
            headers.insert(X_OAI_ATTESTATION_HEADER, header_value);
        }
        headers.insert(
            OPENAI_BETA_HEADER,
            HeaderValue::from_static(RESPONSES_WEBSOCKETS_V2_BETA_HEADER_VALUE),
        );
        if self.state.include_timing_metrics {
            headers.insert(
                X_RESPONSESAPI_INCLUDE_TIMING_METRICS_HEADER,
                HeaderValue::from_static("true"),
            );
        }
        headers
    }
}

impl Drop for ModelClientSession {
    fn drop(&mut self) {
        let websocket_session = std::mem::take(&mut self.websocket_session);
        self.client
            .store_cached_websocket_session(websocket_session);
    }
}

impl ModelClientSession {
    pub(crate) fn turn_state(&self) -> Arc<OnceLock<String>> {
        Arc::clone(&self.turn_state)
    }

    fn reset_websocket_session(&mut self) {
        self.websocket_session.connection = None;
        self.websocket_session.last_request = None;
        self.websocket_session.last_response_rx = None;
        self.websocket_session.last_response_from_untraced_warmup = false;
        self.websocket_session
            .set_connection_reused(/*connection_reused*/ false);
    }

    #[allow(clippy::too_many_arguments)]
    /// Builds shared Responses API transport options and request-body options.
    ///
    /// Keeping option construction in one place ensures request-scoped headers are consistent
    /// regardless of transport choice.
    async fn build_responses_options(
        &self,
        responses_metadata: &CodexResponsesMetadata,
        compression: Compression,
        use_responses_lite: bool,
    ) -> ApiResponsesOptions {
        ApiResponsesOptions {
            session_id: Some(responses_metadata.session_id.to_string()),
            thread_id: Some(responses_metadata.thread_id.to_string()),
            session_source: Some(self.client.state.session_source.clone()),
            extra_headers: {
                let mut headers = build_responses_headers(
                    self.client.state.beta_features_header.as_deref(),
                    Some(&self.turn_state),
                );
                add_originator_header(&mut headers, self.client.state.originator.as_str());
                headers.extend(
                    self.client
                        .build_responses_compatibility_headers(responses_metadata),
                );
                if let Some(header_value) = self.client.generate_attestation_header_for().await {
                    headers.insert(X_OAI_ATTESTATION_HEADER, header_value);
                }
                add_responses_lite_header(&mut headers, use_responses_lite);
                headers
            },
            compression,
            turn_state: Some(Arc::clone(&self.turn_state)),
        }
    }

    /// Checks whether the current request is an incremental extension of the previous request.
    /// We only reuse an incremental input delta when non-input request fields are unchanged and
    /// `input` is a strict extension of the previous known input. Server-returned output items
    /// are treated as part of the baseline so we do not resend them.
    fn get_incremental_items(
        &self,
        request: &ResponsesApiRequest,
        last_response: Option<&LastResponse>,
        allow_empty_delta: bool,
    ) -> Option<Vec<ResponseItem>> {
        let previous_request = self.websocket_session.last_request.as_ref()?;
        if !responses_request_properties_match(previous_request, request) {
            trace!("incremental request failed, websocket reuse properties didn't match");
            return None;
        }

        let response_items =
            last_response.map_or(&[][..], |response| response.items_added.as_slice());
        let previous_items_len = previous_request
            .input
            .len()
            .checked_add(response_items.len())?;
        let Some((request_items_to_compare, incremental_items)) =
            request.input.split_at_checked(previous_items_len)
        else {
            trace!("incremental request failed, incompatible request length");
            return None;
        };
        let previous_items = previous_request.input.iter().chain(response_items);
        if !previous_items
            .zip(request_items_to_compare)
            .all(|(previous, current)| {
                response_items_equal_ignoring_internal_metadata(previous, current)
            })
        {
            trace!("incremental request failed, items didn't match");
            return None;
        }
        if !allow_empty_delta && incremental_items.is_empty() {
            return None;
        }
        Some(incremental_items.to_vec())
    }

    fn get_last_response(&mut self) -> Option<LastResponse> {
        self.websocket_session
            .last_response_rx
            .take()
            .and_then(|mut receiver| match receiver.try_recv() {
                Ok(last_response) => Some(last_response),
                Err(TryRecvError::Closed) | Err(TryRecvError::Empty) => None,
            })
    }

    fn prepare_websocket_request(
        &mut self,
        request: &ResponsesApiRequest,
    ) -> (Option<(String, Vec<ResponseItem>)>, bool) {
        let Some(last_response) = self.get_last_response() else {
            return (None, false);
        };
        let previous_response_id_from_untraced_warmup =
            self.websocket_session.last_response_from_untraced_warmup;
        let Some(incremental_items) = self.get_incremental_items(
            request,
            Some(&last_response),
            /*allow_empty_delta*/ true,
        ) else {
            return (None, false);
        };

        if last_response.response_id.is_empty() {
            trace!("incremental request failed, no previous response id");
            return (None, false);
        }

        (
            Some((last_response.response_id, incremental_items)),
            previous_response_id_from_untraced_warmup,
        )
    }

    /// Opportunistically preconnects a websocket for this turn-scoped client session.
    ///
    /// This performs only connection setup; it never sends prompt payloads.
    pub async fn preconnect_websocket(
        &mut self,
        session_telemetry: &SessionTelemetry,
        responses_metadata: &CodexResponsesMetadata,
    ) -> std::result::Result<(), ApiError> {
        if !self.client.responses_websocket_enabled() {
            return Ok(());
        }
        if self.websocket_session.connection.is_some() {
            return Ok(());
        }

        let client_setup = self.client.current_client_setup().await.map_err(|err| {
            ApiError::Stream(format!(
                "failed to build websocket prewarm client setup: {err}"
            ))
        })?;
        let auth_context = AuthRequestTelemetryContext::new(
            client_setup.auth.as_ref().map(CodexAuth::auth_mode),
            client_setup.api_auth.as_ref(),
            client_setup.agent_identity_telemetry.clone(),
            PendingUnauthorizedRetry::default(),
        );
        let connection = self
            .client
            .connect_websocket_future(
                session_telemetry,
                client_setup.api_provider,
                client_setup.api_auth,
                responses_metadata,
                auth_context,
                RequestRouteTelemetry::for_endpoint(RESPONSES_ENDPOINT),
            )
            .await?;
        self.websocket_session.connection = Some(connection);
        self.websocket_session
            .set_connection_reused(/*connection_reused*/ false);
        Ok(())
    }
    /// Returns a websocket connection for this turn.
    #[instrument(
        name = "model_client.websocket_connection",
        level = "info",
        skip_all,
        fields(
            provider = %self.client.state.provider.info().name,
            wire_api = %self.client.state.provider.info().wire_api,
            transport = "responses_websocket",
            api.path = "responses",
            turn.has_metadata_header = params.responses_metadata.has_turn_metadata()
        )
    )]
    async fn websocket_connection(
        &mut self,
        params: WebsocketConnectParams<'_>,
    ) -> std::result::Result<&ConnectedWebsocket, ApiError> {
        let WebsocketConnectParams {
            session_telemetry,
            api_provider,
            api_auth,
            responses_metadata,
            auth_context,
            request_route_telemetry,
        } = params;
        let desired_identity = WebsocketConnectionIdentity::from_provider(
            &api_provider,
            self.client.state.beta_features_header.as_deref(),
            responses_metadata,
        )?;
        let needs_new = match self.websocket_session.connection.as_ref() {
            Some(conn) => conn.identity != desired_identity || conn.connection.is_closed().await,
            None => true,
        };

        if needs_new {
            self.websocket_session.last_request = None;
            self.websocket_session.last_response_rx = None;
            self.websocket_session.last_response_from_untraced_warmup = false;
            let new_conn = match self
                .client
                .connect_websocket_future(
                    session_telemetry,
                    api_provider,
                    api_auth,
                    responses_metadata,
                    auth_context,
                    request_route_telemetry,
                )
                .await
            {
                Ok(new_conn) => new_conn,
                Err(err) => {
                    if matches!(err, ApiError::Transport(TransportError::Timeout)) {
                        self.reset_websocket_session();
                    }
                    return Err(err);
                }
            };
            self.websocket_session.connection = Some(new_conn);
            self.websocket_session
                .set_connection_reused(/*connection_reused*/ false);
        } else {
            self.websocket_session
                .set_connection_reused(/*connection_reused*/ true);
        }

        self.websocket_session
            .connection
            .as_ref()
            .ok_or(ApiError::Stream(
                "websocket connection is unavailable".to_string(),
            ))
    }

    fn responses_request_compression(&self, auth: Option<&CodexAuth>) -> Compression {
        if self.client.state.enable_request_compression
            && auth.is_some_and(CodexAuth::uses_codex_backend)
            && self.client.state.provider.info().is_openai()
        {
            Compression::Zstd
        } else {
            Compression::None
        }
    }

    /// Streams a turn via the OpenAI Responses API.
    ///
    /// Handles reasoning summaries, verbosity, and the `text` controls used for output schemas.
    #[allow(clippy::too_many_arguments)]
    #[instrument(
        name = "model_client.stream_responses_api",
        level = "info",
        skip_all,
        fields(
            model = %model_info.slug,
            wire_api = %self.client.state.provider.info().wire_api,
            transport = "responses_http",
            http.method = "POST",
            api.path = "responses",
            turn.has_metadata_header = responses_metadata.has_turn_metadata()
        )
    )]
    async fn stream_responses_api(
        &self,
        prompt: &Prompt,
        model_info: &ModelInfo,
        session_telemetry: &SessionTelemetry,
        effort: Option<ReasoningEffortConfig>,
        summary: ReasoningSummaryConfig,
        service_tier: Option<String>,
        responses_metadata: &CodexResponsesMetadata,
        inference_trace: &InferenceTraceContext,
        provider_policy_context: Option<&ModelProviderPolicyContext<'_>>,
        turn_recovery_checkpoint: Option<&dyn TurnRecoveryRequestCheckpoint>,
    ) -> Result<ResponseStream> {
        let auth_manager = self.client.state.provider.auth_manager();
        let mut auth_recovery = auth_manager
            .as_ref()
            .map(AuthManager::unauthorized_recovery);
        let mut provider_auth_recovery_attempted = false;
        let mut pending_retry = PendingUnauthorizedRetry::default();
        let mut memory_retry_index = 0;
        loop {
            let client_setup = self.client.current_client_setup().await?;
            let retry_config = client_setup.api_provider.retry.clone();
            let active_provider_policies = provider_policy_context.map(|context| {
                active_model_provider_policies(context.registry, context.thread_store)
            });
            let exact_physical_endpoint_required = turn_recovery_checkpoint.is_some()
                || active_provider_policies
                    .as_ref()
                    .is_some_and(|active| !active.is_empty());
            // A redirect is a second physical endpoint and therefore needs a
            // fresh deployment fingerprint/policy lease. Until host-owned
            // redirect re-authorization exists, governed and recoverable sends
            // use the no-redirect transport and fail closed on 3xx.
            let mut transport = if exact_physical_endpoint_required {
                self.client
                    .build_sensitive_api_transport(&client_setup.api_provider, RESPONSES_ENDPOINT)?
            } else {
                self.client
                    .build_api_transport(&client_setup.api_provider, RESPONSES_ENDPOINT)?
            };
            let request_auth_context = AuthRequestTelemetryContext::new(
                client_setup.auth.as_ref().map(CodexAuth::auth_mode),
                client_setup.api_auth.as_ref(),
                client_setup.agent_identity_telemetry.clone(),
                pending_retry,
            );
            let compression = self.responses_request_compression(client_setup.auth.as_ref());
            let mut options = self
                .build_responses_options(
                    responses_metadata,
                    compression,
                    model_info.use_responses_lite,
                )
                .await;

            let mut request = self.client.build_responses_request(
                prompt,
                model_info,
                effort.clone(),
                summary,
                service_tier.clone(),
                responses_metadata,
                &client_setup.api_provider,
            )?;
            if let Some(header_value) = self.client.build_routing_hint_header(
                client_setup.auth.as_ref(),
                &request.model,
                request.service_tier.as_deref(),
            ) {
                options
                    .extra_headers
                    .insert(X_CODEX_ROUTING_HINT_HEADER, header_value);
            }
            self.client
                .prepare_response_items_for_request(&mut request.input, &client_setup.api_provider);
            let request_session_telemetry =
                session_telemetry_for_request(session_telemetry, &request);
            let mut effective_request = None;
            let mut has_ephemeral_input = false;
            let mut recovery_checkpoint_authorized = false;
            let mut admitted_provider_attempt = if let Some((context, active_policies)) =
                provider_policy_context
                    .zip(active_provider_policies)
                    .filter(|(_, active)| !active.is_empty())
            {
                let routing_hint = ProviderRoutingHint::from_header(
                    options.extra_headers.get(X_CODEX_ROUTING_HINT_HEADER),
                )
                .map_err(model_provider_policy_error)?;
                let responses_lite = responses_lite_from_http_header(
                    options
                        .extra_headers
                        .get(X_OPENAI_INTERNAL_CODEX_RESPONSES_LITE_HEADER),
                )
                .map_err(model_provider_policy_error)?;
                let base_logical_request = logical_responses_request(&request);
                let endpoint = client_setup.api_provider.url_for_path(RESPONSES_ENDPOINT);
                let attempt = prepare_model_provider_attempt(
                    context,
                    client_setup.api_provider.name.as_str(),
                    request.model.as_str(),
                    ModelProviderTransport::Http,
                    endpoint.as_str(),
                    &base_logical_request,
                    /*previous_response_id*/ None,
                    /*generate*/ true,
                )
                .map_err(model_provider_policy_error)?;
                let model_context_window = model_info.resolved_context_window().map(|window| {
                    window.saturating_mul(model_info.effective_context_window_percent) / 100
                });
                let ephemeral_input = resolve_ephemeral_model_input(
                    context,
                    &attempt,
                    &active_policies,
                    model_context_window,
                )
                .await
                .map_err(model_provider_policy_error)?;
                let ephemeral_binding = ephemeral_input.map(|prepared| {
                    let (item, binding) = prepared.into_parts();
                    let request = effective_request.get_or_insert_with(|| request.clone());
                    request.prompt_cache_key = None;
                    request.store = false;
                    request.input.push(item);
                    binding
                });
                has_ephemeral_input = ephemeral_binding.is_some();
                if has_ephemeral_input {
                    transport = self.client.build_sensitive_api_transport(
                        &client_setup.api_provider,
                        RESPONSES_ENDPOINT,
                    )?;
                }
                let request_for_policy = effective_request.as_ref().unwrap_or(&request);
                let effective_logical_request = logical_responses_request(request_for_policy);
                let wire_semantic = ProviderWireSemantic::new(
                    request_for_policy,
                    routing_hint.as_ref(),
                    responses_lite,
                );
                let prepared = attempt
                    .finalize(
                        &effective_logical_request,
                        &wire_semantic,
                        ephemeral_binding,
                    )
                    .map_err(model_provider_policy_error)?;
                if let Some(checkpoint) = turn_recovery_checkpoint {
                    let compatibility = responses_metadata.turn_recovery_compatibility_projection();
                    match prepared.turn_recovery_fingerprint(
                        &client_setup.api_provider.headers,
                        self.client.state.beta_features_header.as_deref(),
                        &compatibility,
                        routing_hint.as_ref(),
                        responses_lite,
                    ) {
                        Ok(fingerprint) => checkpoint.authorize(fingerprint.as_str()).await?,
                        Err(error) => {
                            checkpoint
                                .unavailable(error.reason_code(), error.detail())
                                .await?
                        }
                    }
                    recovery_checkpoint_authorized = true;
                }
                match begin_active_model_provider_policy(
                    active_policies,
                    prepared.invocation_input(context),
                )
                .await
                .map_err(model_provider_policy_error)?
                {
                    ModelProviderPolicyBegin::NoPolicy if has_ephemeral_input => {
                        return Err(model_provider_policy_error(ModelProviderPolicyError::new(
                            "ephemeral_model_input_policy_missing",
                            "ephemeral model input requires an active provider policy lease",
                        )));
                    }
                    ModelProviderPolicyBegin::NoPolicy => None,
                    ModelProviderPolicyBegin::Allow { lease } => {
                        let dispatch = provider_http_dispatch_metadata(&options.extra_headers);
                        Some(AdmittedProviderAttempt::new(lease, dispatch))
                    }
                    ModelProviderPolicyBegin::Block {
                        reason_code,
                        message,
                    } => return Err(model_provider_policy_blocked(reason_code, message)),
                }
            } else {
                None
            };
            if !recovery_checkpoint_authorized
                && let (Some(context), Some(checkpoint)) =
                    (provider_policy_context, turn_recovery_checkpoint)
            {
                let routing_hint = ProviderRoutingHint::from_header(
                    options.extra_headers.get(X_CODEX_ROUTING_HINT_HEADER),
                )
                .map_err(model_provider_policy_error)?;
                let responses_lite = responses_lite_from_http_header(
                    options
                        .extra_headers
                        .get(X_OPENAI_INTERNAL_CODEX_RESPONSES_LITE_HEADER),
                )
                .map_err(model_provider_policy_error)?;
                let logical_request = logical_responses_request(&request);
                let wire_semantic =
                    ProviderWireSemantic::new(&request, routing_hint.as_ref(), responses_lite);
                let endpoint = client_setup.api_provider.url_for_path(RESPONSES_ENDPOINT);
                let prepared = prepare_model_provider_policy(
                    context,
                    client_setup.api_provider.name.as_str(),
                    request.model.as_str(),
                    ModelProviderTransport::Http,
                    endpoint.as_str(),
                    &logical_request,
                    &wire_semantic,
                    /*previous_response_id*/ None,
                    /*generate*/ true,
                )
                .map_err(model_provider_policy_error)?;
                let compatibility = responses_metadata.turn_recovery_compatibility_projection();
                match prepared.turn_recovery_fingerprint(
                    &client_setup.api_provider.headers,
                    self.client.state.beta_features_header.as_deref(),
                    &compatibility,
                    routing_hint.as_ref(),
                    responses_lite,
                ) {
                    Ok(fingerprint) => checkpoint.authorize(fingerprint.as_str()).await?,
                    Err(error) => {
                        checkpoint
                            .unavailable(error.reason_code(), error.detail())
                            .await?
                    }
                }
            }
            let inference_trace_attempt = inference_trace.start_attempt();
            inference_trace_attempt.add_request_headers(&mut options.extra_headers);
            inference_trace_attempt.record_started(&request);
            let request = effective_request.unwrap_or(request);
            let (request_telemetry, sse_telemetry) = Self::build_streaming_telemetry(
                session_telemetry,
                request_auth_context,
                RequestRouteTelemetry::for_endpoint(RESPONSES_ENDPOINT),
                self.client.state.auth_env_telemetry.clone(),
                has_ephemeral_input,
            );
            let client = ApiResponsesClient::new(
                transport,
                client_setup.api_provider,
                client_setup.api_auth,
            )
            .with_telemetry(Some(request_telemetry), Some(sse_telemetry));
            let client = if has_ephemeral_input {
                client.with_redacted_response_diagnostics()
            } else {
                client
            };
            let stream_result = match admitted_provider_attempt.as_ref() {
                Some(attempt) => {
                    client
                        .stream_request_single_attempt(
                            request,
                            options,
                            attempt.dispatch_metadata(),
                        )
                        .await
                }
                None => client.stream_request(request, options).await,
            };
            let governed_memory_attempt = admitted_provider_attempt.is_some()
                && provider_policy_context.is_some_and(|context| {
                    context.request_kind == ModelProviderRequestKind::Memory
                });

            match stream_result {
                Ok(stream) => {
                    let (stream, _) = map_response_stream(
                        stream,
                        request_session_telemetry,
                        inference_trace_attempt,
                        Arc::clone(&self.client.state.provider),
                        admitted_provider_attempt
                            .take()
                            .map(AdmittedProviderAttempt::into_owner),
                        has_ephemeral_input,
                    );
                    return Ok(stream);
                }
                Err(ApiError::Transport(unauthorized_transport))
                    if self
                        .client
                        .state
                        .provider
                        .is_recoverable_auth_error(&unauthorized_transport) =>
                {
                    let http_status = match &unauthorized_transport {
                        TransportError::Http { status, .. } => Some(status.as_u16()),
                        _ => None,
                    };
                    if let Some(attempt) = admitted_provider_attempt.take() {
                        attempt.finish_immediate(http_status, "http").await?;
                    }
                    let response_debug_context = redact_ephemeral_response_debug_context(
                        extract_response_debug_context(&unauthorized_transport),
                        has_ephemeral_input,
                    );
                    let trace_error = if has_ephemeral_input {
                        http_status.map_or_else(
                            || "ephemeral model-provider authentication failed".to_string(),
                            |status| {
                                format!(
                                    "ephemeral model-provider request failed with HTTP {status}"
                                )
                            },
                        )
                    } else {
                        unauthorized_transport.to_string()
                    };
                    inference_trace_attempt.record_failed(
                        trace_error,
                        response_debug_context.request_id.as_deref(),
                        /*output_items*/ &[],
                    );
                    pending_retry = PendingUnauthorizedRetry::from_recovery(
                        handle_unauthorized(
                            unauthorized_transport,
                            &mut auth_recovery,
                            &mut provider_auth_recovery_attempted,
                            session_telemetry,
                            &self.client.state.provider,
                            has_ephemeral_input,
                        )
                        .await?,
                    );
                    continue;
                }
                Err(err) => {
                    let http_status = api_error_http_status(&err);
                    if let Some(attempt) = admitted_provider_attempt.take() {
                        attempt.finish_immediate(http_status, "http").await?;
                    }
                    let retry_delay = if governed_memory_attempt {
                        match &err {
                            ApiError::Transport(transport_error) => retry_config
                                .retry_delay_after_error(transport_error, memory_retry_index),
                            _ => None,
                        }
                    } else {
                        None
                    };
                    let response_debug_context = redact_ephemeral_response_debug_context(
                        extract_response_debug_context_from_api_error(&err),
                        has_ephemeral_input,
                    );
                    let err = redact_ephemeral_provider_error(
                        self.client.state.provider.map_api_error(err),
                        has_ephemeral_input,
                    );
                    let trace_error = if has_ephemeral_input {
                        http_status.map_or_else(
                            || "ephemeral model-provider request failed".to_string(),
                            |status| {
                                format!(
                                    "ephemeral model-provider request failed with HTTP {status}"
                                )
                            },
                        )
                    } else {
                        err.to_string()
                    };
                    inference_trace_attempt.record_failed(
                        trace_error,
                        response_debug_context.request_id.as_deref(),
                        /*output_items*/ &[],
                    );
                    if let Some(delay) = retry_delay {
                        memory_retry_index += 1;
                        tokio::time::sleep(delay).await;
                        continue;
                    }
                    return Err(err);
                }
            }
        }
    }

    /// Streams a turn via the Responses API over WebSocket transport.
    #[allow(clippy::too_many_arguments)]
    #[inline(never)]
    fn stream_responses_websocket_future<'a>(
        &'a mut self,
        prompt: &'a Prompt,
        model_info: &'a ModelInfo,
        session_telemetry: &'a SessionTelemetry,
        effort: Option<ReasoningEffortConfig>,
        summary: ReasoningSummaryConfig,
        service_tier: Option<String>,
        responses_metadata: &'a CodexResponsesMetadata,
        warmup: bool,
        request_trace: Option<W3cTraceContext>,
        inference_trace: &'a InferenceTraceContext,
        provider_policy_context: Option<&'a ModelProviderPolicyContext<'a>>,
        turn_recovery_checkpoint: Option<&'a dyn TurnRecoveryRequestCheckpoint>,
    ) -> BoxFuture<'a, Result<WebsocketStreamOutcome>> {
        self.stream_responses_websocket(
            prompt,
            model_info,
            session_telemetry,
            effort,
            summary,
            service_tier,
            responses_metadata,
            warmup,
            request_trace,
            inference_trace,
            provider_policy_context,
            turn_recovery_checkpoint,
        )
        .boxed()
    }

    /// Streams a turn via the Responses API over WebSocket transport.
    #[allow(clippy::too_many_arguments)]
    #[instrument(
        name = "model_client.stream_responses_websocket",
        level = "info",
        skip_all,
        fields(
            model = %model_info.slug,
            wire_api = %self.client.state.provider.info().wire_api,
            transport = "responses_websocket",
            api.path = "responses",
            turn.has_metadata_header = responses_metadata.has_turn_metadata(),
            websocket.warmup = warmup
        )
    )]
    async fn stream_responses_websocket(
        &mut self,
        prompt: &Prompt,
        model_info: &ModelInfo,
        session_telemetry: &SessionTelemetry,
        effort: Option<ReasoningEffortConfig>,
        summary: ReasoningSummaryConfig,
        service_tier: Option<String>,
        responses_metadata: &CodexResponsesMetadata,
        warmup: bool,
        request_trace: Option<W3cTraceContext>,
        inference_trace: &InferenceTraceContext,
        provider_policy_context: Option<&ModelProviderPolicyContext<'_>>,
        turn_recovery_checkpoint: Option<&dyn TurnRecoveryRequestCheckpoint>,
    ) -> Result<WebsocketStreamOutcome> {
        let provider = Arc::clone(&self.client.state.provider);
        let auth_manager = provider.auth_manager();

        let mut auth_recovery = auth_manager
            .as_ref()
            .map(AuthManager::unauthorized_recovery);
        let mut provider_auth_recovery_attempted = false;
        let mut pending_retry = PendingUnauthorizedRetry::default();
        loop {
            let client_setup = self.client.current_client_setup().await?;
            let active_provider_policies = provider_policy_context.map(|context| {
                active_model_provider_policies(context.registry, context.thread_store)
            });
            let request_auth_context = AuthRequestTelemetryContext::new(
                client_setup.auth.as_ref().map(CodexAuth::auth_mode),
                client_setup.api_auth.as_ref(),
                client_setup.agent_identity_telemetry.clone(),
                pending_retry,
            );
            let mut request = self.client.build_responses_request(
                prompt,
                model_info,
                effort.clone(),
                summary,
                service_tier.clone(),
                responses_metadata,
                &client_setup.api_provider,
            )?;
            let mut websocket_metadata = responses_metadata.clone();
            websocket_metadata.routing_hint = self.client.build_routing_hint_header(
                client_setup.auth.as_ref(),
                &request.model,
                request.service_tier.as_deref(),
            );
            let request_session_telemetry = if warmup {
                // `generate=false` prewarm is connection setup, not an inference request.
                session_telemetry.clone()
            } else {
                session_telemetry_for_request(session_telemetry, &request)
            };
            let mut client_metadata = self
                .client
                .build_ws_client_metadata(responses_metadata, model_info.use_responses_lite);
            if let Some(turn_state) = self.turn_state.get() {
                client_metadata.insert(X_CODEX_TURN_STATE_HEADER.to_string(), turn_state.clone());
            }
            match self
                .websocket_connection(WebsocketConnectParams {
                    session_telemetry,
                    api_provider: client_setup.api_provider.clone(),
                    api_auth: client_setup.api_auth,
                    responses_metadata: &websocket_metadata,
                    auth_context: request_auth_context,
                    request_route_telemetry: RequestRouteTelemetry::for_endpoint(
                        RESPONSES_ENDPOINT,
                    ),
                })
                .await
            {
                Ok(_) => {}
                Err(ApiError::Transport(TransportError::Http { status, .. }))
                    if status == StatusCode::UPGRADE_REQUIRED =>
                {
                    return Ok(WebsocketStreamOutcome::FallbackToHttp);
                }
                Err(ApiError::Transport(unauthorized_transport))
                    if provider.is_recoverable_auth_error(&unauthorized_transport) =>
                {
                    pending_retry = PendingUnauthorizedRetry::from_recovery(
                        handle_unauthorized(
                            unauthorized_transport,
                            &mut auth_recovery,
                            &mut provider_auth_recovery_attempted,
                            session_telemetry,
                            &provider,
                            /*redact_provider_error*/ false,
                        )
                        .await?,
                    );
                    continue;
                }
                Err(err) => return Err(provider.map_api_error(err)),
            }

            let provider_policy_active = active_provider_policies
                .as_ref()
                .is_some_and(|active| !active.is_empty());
            let provider_binding_required =
                provider_policy_active || turn_recovery_checkpoint.is_some();
            let policy_logical_request = if provider_binding_required {
                let mut logical_request = request.clone();
                self.client.prepare_response_items_for_request(
                    &mut logical_request.input,
                    &client_setup.api_provider,
                );
                Some(logical_responses_request(&logical_request))
            } else {
                None
            };

            let (incremental_request, previous_response_id_from_untraced_warmup) =
                self.prepare_websocket_request(&request);
            let inference_trace_attempt = if warmup {
                // Prewarm sends `generate=false`; it is connection setup, not a
                // model inference attempt that should appear in rollout traces.
                InferenceTraceAttempt::disabled()
            } else {
                inference_trace.start_attempt()
            };
            if previous_response_id_from_untraced_warmup && !provider_policy_active {
                // The transport can reuse an untraced warmup response id and omit the
                // already-sent input, but rollout replay needs the logical model-visible
                // request rather than the compressed websocket delta.
                inference_trace_attempt.record_started(&request);
            }

            let (previous_response_id, mut incremental_items) = match incremental_request {
                Some((response_id, items)) => (Some(response_id), Some(items)),
                None => (None, None),
            };
            let previous_response_id_for_policy = previous_response_id.clone();
            let original_item_ids = if let Some(incremental_items) = &mut incremental_items {
                self.client.prepare_response_items_for_request(
                    incremental_items,
                    &client_setup.api_provider,
                );
                None
            } else {
                let original_item_ids = request
                    .input
                    .iter()
                    .map(|item| item.id().cloned())
                    .collect::<Vec<_>>();
                self.client.prepare_response_items_for_request(
                    &mut request.input,
                    &client_setup.api_provider,
                );
                Some(original_item_ids)
            };
            let ws_payload = ResponseCreateWsRequest {
                previous_response_id,
                input: incremental_items.as_deref().unwrap_or(&request.input),
                generate: if warmup { Some(false) } else { None },
                client_metadata: response_create_client_metadata(
                    Some(client_metadata),
                    request_trace.as_ref(),
                ),
                ..ResponseCreateWsRequest::from(&request)
            };
            let mut admitted_provider_attempt =
                if let (Some(context), Some(active_policies), Some(logical_request)) = (
                    provider_policy_context,
                    active_provider_policies,
                    policy_logical_request.as_ref(),
                ) {
                    let responses_lite = responses_lite_from_ws_metadata(
                        ws_payload.client_metadata.as_ref(),
                        WS_REQUEST_HEADER_RESPONSES_LITE_CLIENT_METADATA_KEY,
                    )
                    .map_err(model_provider_policy_error)?;
                    let semantic_payload = provider_websocket_wire_payload(&ws_payload)
                        .map_err(model_provider_policy_error)?;
                    let actual_routing_hint = self
                        .websocket_session
                        .connection
                        .as_ref()
                        .ok_or_else(|| {
                            self.client.state.provider.map_api_error(ApiError::Stream(
                                "websocket connection is unavailable".to_string(),
                            ))
                        })?
                        .actual_routing_hint
                        .clone();
                    let wire_semantic = ProviderWireSemantic::new(
                        &semantic_payload,
                        actual_routing_hint.as_ref(),
                        responses_lite,
                    );
                    let endpoint = client_setup
                        .api_provider
                        .websocket_url_for_path("responses")
                        .map_err(|error| {
                            model_provider_policy_error(ModelProviderPolicyError::new(
                                "model_provider_policy_invalid_websocket_endpoint",
                                format!("failed to build provider WebSocket endpoint: {error}"),
                            ))
                        })?;
                    let prepared = prepare_model_provider_policy(
                        context,
                        client_setup.api_provider.name.as_str(),
                        request.model.as_str(),
                        ModelProviderTransport::WebSocket,
                        endpoint.as_str(),
                        logical_request,
                        &wire_semantic,
                        previous_response_id_for_policy.as_deref(),
                        !warmup,
                    )
                    .map_err(model_provider_policy_error)?;
                    if let Some(checkpoint) = turn_recovery_checkpoint {
                        let compatibility =
                            responses_metadata.turn_recovery_compatibility_projection();
                        match prepared.turn_recovery_fingerprint(
                            &client_setup.api_provider.headers,
                            self.client.state.beta_features_header.as_deref(),
                            &compatibility,
                            actual_routing_hint.as_ref(),
                            responses_lite,
                        ) {
                            Ok(fingerprint) => checkpoint.authorize(fingerprint.as_str()).await?,
                            Err(error) => {
                                checkpoint
                                    .unavailable(error.reason_code(), error.detail())
                                    .await?
                            }
                        }
                    }
                    match begin_active_model_provider_policy(
                        active_policies,
                        prepared.invocation_input(context),
                    )
                    .await
                    .map_err(model_provider_policy_error)?
                    {
                        ModelProviderPolicyBegin::NoPolicy => None,
                        ModelProviderPolicyBegin::Allow { lease } => Some(
                            AdmittedProviderAttempt::new(lease, RequestDispatchMetadata::new()),
                        ),
                        ModelProviderPolicyBegin::Block {
                            reason_code,
                            message,
                        } => return Err(model_provider_policy_blocked(reason_code, message)),
                    }
                } else {
                    None
                };
            if previous_response_id_from_untraced_warmup && provider_policy_active {
                inference_trace_attempt.record_started(&request);
            }
            let mut ws_request = ResponsesWsRequest::ResponseCreate(ws_payload);
            stamp_ws_stream_request_start_ms(&mut ws_request);
            if !previous_response_id_from_untraced_warmup {
                inference_trace_attempt.record_started(&ws_request);
            }

            let Some(websocket_connection) = self.websocket_session.connection.as_ref() else {
                if let Some(attempt) = admitted_provider_attempt.take() {
                    attempt
                        .finish_immediate(/*http_status*/ None, "websocket")
                        .await?;
                }
                return Err(self.client.state.provider.map_api_error(ApiError::Stream(
                    "websocket connection is unavailable".to_string(),
                )));
            };
            let stream_result = match admitted_provider_attempt.as_ref() {
                Some(attempt) => {
                    websocket_connection
                        .connection
                        .stream_request_single_attempt(
                            ws_request,
                            self.websocket_session.connection_reused(),
                            Some(Arc::clone(&self.turn_state)),
                            attempt.dispatch_metadata(),
                        )
                        .await
                }
                None => {
                    websocket_connection
                        .connection
                        .stream_request(
                            ws_request,
                            self.websocket_session.connection_reused(),
                            Some(Arc::clone(&self.turn_state)),
                        )
                        .await
                }
            };
            if let Some(original_item_ids) = original_item_ids {
                for (item, original_item_id) in request.input.iter_mut().zip(original_item_ids) {
                    item.set_id(original_item_id);
                }
            }
            self.websocket_session.last_request = Some(request);
            self.websocket_session.last_response_from_untraced_warmup = warmup;
            let stream_result = match stream_result {
                Ok(stream) => stream,
                Err(err) => {
                    if let Some(attempt) = admitted_provider_attempt.take() {
                        attempt
                            .finish_immediate(api_error_http_status(&err), "websocket")
                            .await?;
                    }
                    let response_debug_context =
                        extract_response_debug_context_from_api_error(&err);
                    let err = self.client.state.provider.map_api_error(err);
                    inference_trace_attempt.record_failed(
                        &err,
                        response_debug_context.request_id.as_deref(),
                        /*output_items*/ &[],
                    );
                    return Err(err);
                }
            };
            let (stream, last_request_rx) = map_response_stream(
                stream_result,
                request_session_telemetry,
                inference_trace_attempt,
                Arc::clone(&self.client.state.provider),
                admitted_provider_attempt
                    .take()
                    .map(AdmittedProviderAttempt::into_owner),
                /*redact_provider_errors*/ false,
            );
            self.websocket_session.last_response_rx = Some(last_request_rx);
            return Ok(WebsocketStreamOutcome::Stream(stream));
        }
    }

    /// Builds request and SSE telemetry for streaming API calls.
    fn build_streaming_telemetry(
        session_telemetry: &SessionTelemetry,
        auth_context: AuthRequestTelemetryContext,
        request_route_telemetry: RequestRouteTelemetry,
        auth_env_telemetry: AuthEnvTelemetry,
        redact_provider_diagnostics: bool,
    ) -> (Arc<dyn RequestTelemetry>, Arc<dyn SseTelemetry>) {
        let telemetry = Arc::new(ApiTelemetry::new(
            session_telemetry.clone(),
            auth_context,
            request_route_telemetry,
            auth_env_telemetry,
            redact_provider_diagnostics,
        ));
        let request_telemetry: Arc<dyn RequestTelemetry> = telemetry.clone();
        let sse_telemetry: Arc<dyn SseTelemetry> = telemetry;
        (request_telemetry, sse_telemetry)
    }

    /// Builds telemetry for the Responses API WebSocket transport.
    fn build_websocket_telemetry(
        session_telemetry: &SessionTelemetry,
        auth_context: AuthRequestTelemetryContext,
        request_route_telemetry: RequestRouteTelemetry,
        auth_env_telemetry: AuthEnvTelemetry,
    ) -> Arc<dyn WebsocketTelemetry> {
        let telemetry = Arc::new(ApiTelemetry::new(
            session_telemetry.clone(),
            auth_context,
            request_route_telemetry,
            auth_env_telemetry,
            /*redact_provider_diagnostics*/ false,
        ));
        let websocket_telemetry: Arc<dyn WebsocketTelemetry> = telemetry;
        websocket_telemetry
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn prewarm_websocket(
        &mut self,
        prompt: &Prompt,
        model_info: &ModelInfo,
        session_telemetry: &SessionTelemetry,
        effort: Option<ReasoningEffortConfig>,
        summary: ReasoningSummaryConfig,
        service_tier: Option<String>,
        responses_metadata: &CodexResponsesMetadata,
    ) -> Result<()> {
        self.prewarm_websocket_with_policy(
            prompt,
            model_info,
            session_telemetry,
            effort,
            summary,
            service_tier,
            responses_metadata,
            /*provider_policy_context*/ None,
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) async fn prewarm_websocket_with_policy(
        &mut self,
        prompt: &Prompt,
        model_info: &ModelInfo,
        session_telemetry: &SessionTelemetry,
        effort: Option<ReasoningEffortConfig>,
        summary: ReasoningSummaryConfig,
        service_tier: Option<String>,
        responses_metadata: &CodexResponsesMetadata,
        provider_policy_context: Option<&ModelProviderPolicyContext<'_>>,
    ) -> Result<()> {
        if !self.client.responses_websocket_enabled() {
            return Ok(());
        }
        // Turn-input contributors finish preparing their turn-local state before this
        // context is handed to the provider client. Freeze the same active-contributor
        // predicate used by the physical-send resolver: an active ephemeral input may
        // only travel through the HTTP path that resolves and binds it. A WebSocket
        // prewarm would otherwise establish transport state that bypasses that path.
        if provider_policy_context.is_some_and(has_active_ephemeral_model_input_contributor) {
            return Ok(());
        }
        if self.websocket_session.last_request.is_some() {
            return Ok(());
        }

        let disabled_trace = InferenceTraceContext::disabled();
        match self
            .stream_responses_websocket(
                prompt,
                model_info,
                session_telemetry,
                effort,
                summary,
                service_tier,
                responses_metadata,
                /*warmup*/ true,
                current_span_w3c_trace_context(),
                &disabled_trace,
                provider_policy_context,
                /*turn_recovery_checkpoint*/ None,
            )
            .await
        {
            Ok(WebsocketStreamOutcome::Stream(mut stream)) => {
                // Wait for the v2 warmup request to complete before sending the first turn request.
                while let Some(event) = stream.next().await {
                    match event {
                        Ok(ResponseEvent::Completed { .. }) => break,
                        Err(err) => return Err(err),
                        _ => {}
                    }
                }
                Ok(())
            }
            Ok(WebsocketStreamOutcome::FallbackToHttp) => {
                self.try_switch_fallback_transport(session_telemetry, model_info);
                Ok(())
            }
            Err(err) => Err(err),
        }
    }

    /// Ungoverned low-level stream entrypoint retained only for transport and
    /// header integration tests. Production callsites must use a host-owned
    /// policy context or a narrow governed capability.
    #[doc(hidden)]
    #[allow(clippy::too_many_arguments)]
    pub async fn stream_unguarded_for_test(
        &mut self,
        prompt: &Prompt,
        model_info: &ModelInfo,
        session_telemetry: &SessionTelemetry,
        effort: Option<ReasoningEffortConfig>,
        summary: ReasoningSummaryConfig,
        service_tier: Option<String>,
        responses_metadata: &CodexResponsesMetadata,
        inference_trace: &InferenceTraceContext,
    ) -> Result<ResponseStream> {
        self.stream_with_policy(
            prompt,
            model_info,
            session_telemetry,
            effort,
            summary,
            service_tier,
            responses_metadata,
            inference_trace,
            /*provider_policy_context*/ None,
            /*turn_recovery_checkpoint*/ None,
        )
        .await
    }

    /// Streams one detached Memory request through the exact admitted parent
    /// session/thread/turn scopes retained by `provider_policy`.
    #[allow(clippy::too_many_arguments)]
    pub async fn stream_memory_with_policy(
        &mut self,
        prompt: &Prompt,
        model_info: &ModelInfo,
        session_telemetry: &SessionTelemetry,
        effort: Option<ReasoningEffortConfig>,
        summary: ReasoningSummaryConfig,
        service_tier: Option<String>,
        responses_metadata: &CodexResponsesMetadata,
        inference_trace: &InferenceTraceContext,
        provider_policy: &crate::MemoryModelProviderPolicyHandle,
    ) -> Result<ResponseStream> {
        let policy_thread_id = provider_policy.thread_id();
        let policy_session_id = provider_policy.session_id();
        if self.client.state.thread_id != policy_thread_id
            || responses_metadata.thread_id != policy_thread_id.to_string()
            || responses_metadata.session_id != policy_session_id.to_string()
        {
            return Err(CodexErr::InvalidRequest(
                "memory provider client, metadata, and policy session/thread identities must match"
                    .to_string(),
            ));
        }
        if responses_metadata.turn_id.is_some()
            || !matches!(
                responses_metadata.request_kind,
                Some(CodexResponsesRequestKind::Memory)
            )
        {
            return Err(CodexErr::InvalidRequest(
                "memory provider policy requires detached Memory response metadata".to_string(),
            ));
        }

        let provider_policy_context = provider_policy.context();
        self.stream_with_policy(
            prompt,
            model_info,
            session_telemetry,
            effort,
            summary,
            service_tier,
            responses_metadata,
            inference_trace,
            Some(&provider_policy_context),
            /*turn_recovery_checkpoint*/ None,
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    #[inline(never)]
    pub(crate) fn stream_with_policy_future<'a>(
        &'a mut self,
        prompt: &'a Prompt,
        model_info: &'a ModelInfo,
        session_telemetry: &'a SessionTelemetry,
        effort: Option<ReasoningEffortConfig>,
        summary: ReasoningSummaryConfig,
        service_tier: Option<String>,
        responses_metadata: &'a CodexResponsesMetadata,
        inference_trace: &'a InferenceTraceContext,
        provider_policy_context: Option<&'a ModelProviderPolicyContext<'a>>,
        turn_recovery_checkpoint: Option<&'a dyn TurnRecoveryRequestCheckpoint>,
    ) -> BoxFuture<'a, Result<ResponseStream>> {
        self.stream_with_policy(
            prompt,
            model_info,
            session_telemetry,
            effort,
            summary,
            service_tier,
            responses_metadata,
            inference_trace,
            provider_policy_context,
            turn_recovery_checkpoint,
        )
        .boxed()
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) async fn stream_with_policy(
        &mut self,
        prompt: &Prompt,
        model_info: &ModelInfo,
        session_telemetry: &SessionTelemetry,
        effort: Option<ReasoningEffortConfig>,
        summary: ReasoningSummaryConfig,
        service_tier: Option<String>,
        responses_metadata: &CodexResponsesMetadata,
        inference_trace: &InferenceTraceContext,
        provider_policy_context: Option<&ModelProviderPolicyContext<'_>>,
        turn_recovery_checkpoint: Option<&dyn TurnRecoveryRequestCheckpoint>,
    ) -> Result<ResponseStream> {
        if turn_recovery_checkpoint.is_some() && provider_policy_context.is_none() {
            return Err(CodexErr::Fatal(
                "turn recovery checkpoint requires an exact provider policy context".to_string(),
            ));
        }
        // This synchronous check freezes the exact turn-local contributor state after
        // turn-input preparation and before any transport await. WebSocket sends do not
        // run `resolve_ephemeral_model_input`, so an active contributor must use the
        // existing sensitive HTTP path instead of silently losing attempt-local input.
        let ephemeral_model_input_requires_http =
            provider_policy_context.is_some_and(has_active_ephemeral_model_input_contributor);
        let wire_api = self.client.state.provider.info().wire_api;
        match wire_api {
            WireApi::Responses => {
                if self.client.responses_websocket_enabled() && !ephemeral_model_input_requires_http
                {
                    let request_trace = current_span_w3c_trace_context();
                    match self
                        .stream_responses_websocket_future(
                            prompt,
                            model_info,
                            session_telemetry,
                            effort.clone(),
                            summary,
                            service_tier.clone(),
                            responses_metadata,
                            /*warmup*/ false,
                            request_trace,
                            inference_trace,
                            provider_policy_context,
                            turn_recovery_checkpoint,
                        )
                        .await?
                    {
                        WebsocketStreamOutcome::Stream(stream) => return Ok(stream),
                        WebsocketStreamOutcome::FallbackToHttp => {
                            self.try_switch_fallback_transport(session_telemetry, model_info);
                        }
                    }
                }

                self.stream_responses_api(
                    prompt,
                    model_info,
                    session_telemetry,
                    effort,
                    summary,
                    service_tier,
                    responses_metadata,
                    inference_trace,
                    provider_policy_context,
                    turn_recovery_checkpoint,
                )
                .await
            }
        }
    }

    /// Permanently disables WebSockets for this Codex session and resets WebSocket state.
    ///
    /// This is used after exhausting the provider retry budget, to force subsequent requests onto
    /// the HTTP transport.
    ///
    /// Returns `true` if this call activated fallback, or `false` if fallback was already active.
    pub(crate) fn try_switch_fallback_transport(
        &mut self,
        session_telemetry: &SessionTelemetry,
        model_info: &ModelInfo,
    ) -> bool {
        let activated = self
            .client
            .force_http_fallback(session_telemetry, model_info);
        self.websocket_session = WebsocketSession::default();
        activated
    }
}

/// Stamp a ResponsesWsRequest with the current time.
///
/// Meant to be called just before sending the request over the socket, to capture realistic
/// transport timing.
fn stamp_ws_stream_request_start_ms(request: &mut ResponsesWsRequest<'_>) {
    let ResponsesWsRequest::ResponseCreate(payload) = request;
    payload
        .client_metadata
        .get_or_insert_with(HashMap::new)
        .insert(
            X_CODEX_WS_STREAM_REQUEST_START_MS_CLIENT_METADATA_KEY.to_string(),
            crate::turn_timing::now_unix_timestamp_ms().to_string(),
        );
}

/// Builds the extra headers attached to Responses API requests.
///
/// These headers implement Codex-specific conventions:
///
/// - `x-codex-beta-features`: comma-separated beta feature keys enabled for the session.
/// - `x-codex-turn-state`: sticky routing token captured earlier in the turn.
fn build_responses_headers(
    beta_features_header: Option<&str>,
    turn_state: Option<&Arc<OnceLock<String>>>,
) -> ApiHeaderMap {
    let mut headers = ApiHeaderMap::new();
    if let Some(value) = beta_features_header
        && !value.is_empty()
        && let Ok(header_value) = HeaderValue::from_str(value)
    {
        headers.insert("x-codex-beta-features", header_value);
    }
    if let Some(turn_state) = turn_state
        && let Some(state) = turn_state.get()
        && let Ok(header_value) = HeaderValue::from_str(state)
    {
        headers.insert(X_CODEX_TURN_STATE_HEADER, header_value);
    }
    headers
}

fn add_responses_lite_header(headers: &mut ApiHeaderMap, use_responses_lite: bool) {
    if use_responses_lite {
        headers.insert(
            X_OPENAI_INTERNAL_CODEX_RESPONSES_LITE_HEADER,
            HeaderValue::from_static("true"),
        );
    }
}

fn provider_http_dispatch_metadata(headers: &ApiHeaderMap) -> RequestDispatchMetadata {
    RequestDispatchMetadata::new_with_expected_headers(
        [
            X_CODEX_ROUTING_HINT_HEADER,
            X_OPENAI_INTERNAL_CODEX_RESPONSES_LITE_HEADER,
        ]
        .into_iter()
        .map(|name| (HeaderName::from_static(name), headers.get(name).cloned()))
        .collect(),
    )
}

const RESPONSE_STREAM_CHANNEL_CAPACITY: usize = 1600;
const STREAM_DROPPED_REASON: &str = "response stream dropped before provider terminal event";

fn map_response_stream(
    api_stream: codex_api::ResponseStream,
    session_telemetry: SessionTelemetry,
    inference_trace_attempt: InferenceTraceAttempt,
    provider: SharedModelProvider,
    provider_attempt: Option<ProviderAttemptOwner>,
    redact_provider_errors: bool,
) -> (ResponseStream, oneshot::Receiver<LastResponse>) {
    let codex_api::ResponseStream {
        rx_event,
        upstream_request_id,
    } = api_stream;
    let upstream_request_id = if redact_provider_errors {
        None
    } else {
        upstream_request_id
    };
    let api_stream = codex_api::ResponseStream {
        rx_event,
        upstream_request_id: None,
    };
    map_response_events(
        upstream_request_id,
        api_stream,
        session_telemetry,
        inference_trace_attempt,
        provider,
        provider_attempt,
        redact_provider_errors,
    )
}

fn map_response_events<S>(
    upstream_request_id: Option<String>,
    api_stream: S,
    session_telemetry: SessionTelemetry,
    inference_trace_attempt: InferenceTraceAttempt,
    provider: SharedModelProvider,
    provider_attempt: Option<ProviderAttemptOwner>,
    redact_provider_errors: bool,
) -> (ResponseStream, oneshot::Receiver<LastResponse>)
where
    S: futures::Stream<Item = std::result::Result<ResponseEvent, ApiError>>
        + Unpin
        + Send
        + 'static,
{
    let (tx_event, rx_event) =
        mpsc::channel::<Result<ResponseEvent>>(RESPONSE_STREAM_CHANNEL_CAPACITY);
    let (tx_last_response, rx_last_response) = oneshot::channel::<LastResponse>();
    let consumer_dropped = CancellationToken::new();
    let consumer_dropped_for_stream = consumer_dropped.clone();

    tokio::spawn(async move {
        let mut logged_error = false;
        let mut tx_last_response = Some(tx_last_response);
        let mut items_added: Vec<ResponseItem> = Vec::new();
        let (request_start, mut ttft_ms) = (Instant::now(), None);
        let mut api_stream = api_stream;
        let mut provider_terminal = ProviderResponseTerminal::new(provider_attempt);
        let upstream_request_id = upstream_request_id.as_deref();
        if let Some(upstream_request_id) = upstream_request_id {
            feedback_tags!(last_model_request_id = upstream_request_id);
        }
        loop {
            let event = tokio::select! {
                _ = consumer_dropped.cancelled() => {
                    finish_abandoned_provider_response(
                        &mut provider_terminal,
                        "provider_response_consumer_dropped",
                        &items_added,
                    ).await;
                    inference_trace_attempt.record_cancelled(
                        STREAM_DROPPED_REASON,
                        upstream_request_id,
                        &items_added,
                    );
                    return;
                }
                event = api_stream.next() => event,
            };
            let Some(event) = event else {
                break;
            };
            match event {
                Ok(ResponseEvent::OutputItemDone(item)) => {
                    items_added.push(item.clone());
                    if tx_event
                        .send(Ok(ResponseEvent::OutputItemDone(item)))
                        .await
                        .is_err()
                    {
                        finish_abandoned_provider_response(
                            &mut provider_terminal,
                            "provider_response_consumer_dropped",
                            &items_added,
                        )
                        .await;
                        inference_trace_attempt.record_cancelled(
                            STREAM_DROPPED_REASON,
                            upstream_request_id,
                            &items_added,
                        );
                        return;
                    }
                }
                Ok(ResponseEvent::Completed {
                    response_id,
                    token_usage,
                    end_turn,
                }) => {
                    let provider_terminal_committed = match provider_terminal
                        .finish_completed(&response_id, &items_added, &token_usage, end_turn)
                        .await
                    {
                        Ok(committed) => committed,
                        Err(error) => {
                            let error = model_provider_policy_error(error);
                            inference_trace_attempt.record_failed(
                                &error,
                                upstream_request_id,
                                &items_added,
                            );
                            session_telemetry.see_event_completed_failed(&error);
                            let _ = tx_event.send(Err(error)).await;
                            return;
                        }
                    };
                    feedback_tags!(last_model_response_id = &response_id);
                    if let Some(usage) = &token_usage {
                        session_telemetry.sse_event_completed(usage, ttft_ms);
                    }
                    inference_trace_attempt.record_completed(
                        &response_id,
                        upstream_request_id,
                        &token_usage,
                        &items_added,
                    );
                    if let Some(sender) = tx_last_response.take() {
                        let _ = sender.send(LastResponse {
                            response_id: response_id.clone(),
                            items_added: std::mem::take(&mut items_added),
                        });
                    }
                    if tx_event
                        .send(Ok(ResponseEvent::Completed {
                            response_id,
                            token_usage,
                            end_turn,
                        }))
                        .await
                        .is_err()
                    {
                        return;
                    }
                    if provider_terminal_committed {
                        return;
                    }
                }
                Ok(event) => {
                    if matches!(&event, ResponseEvent::OutputItemAdded(_)) && ttft_ms.is_none() {
                        ttft_ms = Some(
                            i64::try_from(request_start.elapsed().as_millis()).unwrap_or(i64::MAX),
                        );
                    }
                    if tx_event.send(Ok(event)).await.is_err() {
                        finish_abandoned_provider_response(
                            &mut provider_terminal,
                            "provider_response_consumer_dropped",
                            &items_added,
                        )
                        .await;
                        inference_trace_attempt.record_cancelled(
                            STREAM_DROPPED_REASON,
                            upstream_request_id,
                            &items_added,
                        );
                        return;
                    }
                }
                Err(err) => {
                    let provider_terminal_result = if api_error_http_status(&err)
                        == Some(StatusCode::UNAUTHORIZED.as_u16())
                    {
                        provider_terminal
                            .finish_rejected("provider_response_unauthorized")
                            .await
                    } else {
                        provider_terminal
                            .finish_indeterminate("provider_response_stream_error", &items_added)
                            .await
                    };
                    let response_debug_context = redact_ephemeral_response_debug_context(
                        extract_response_debug_context_from_api_error(&err),
                        redact_provider_errors,
                    );
                    let upstream_request_id =
                        upstream_request_id.or(response_debug_context.request_id.as_deref());
                    if let Some(upstream_request_id) = upstream_request_id {
                        feedback_tags!(last_model_request_id = upstream_request_id);
                    }
                    let provider_terminal_committed = match provider_terminal_result {
                        Ok(committed) => committed,
                        Err(error) => {
                            let error = model_provider_policy_error(error);
                            inference_trace_attempt.record_failed(
                                &error,
                                upstream_request_id,
                                &items_added,
                            );
                            session_telemetry.see_event_completed_failed(&error);
                            let _ = tx_event.send(Err(error)).await;
                            return;
                        }
                    };
                    let mapped = redact_ephemeral_provider_error(
                        provider.map_api_error(err),
                        redact_provider_errors,
                    );
                    inference_trace_attempt.record_failed(
                        &mapped,
                        upstream_request_id,
                        &items_added,
                    );
                    if !logged_error {
                        session_telemetry.see_event_completed_failed(&mapped);
                        logged_error = true;
                    }
                    if tx_event.send(Err(mapped)).await.is_err() {
                        return;
                    }
                    if provider_terminal_committed {
                        return;
                    }
                }
            }
        }
        if let Err(error) = provider_terminal
            .finish_indeterminate("provider_response_stream_closed", &items_added)
            .await
        {
            let error = model_provider_policy_error(error);
            inference_trace_attempt.record_failed(&error, upstream_request_id, &items_added);
            session_telemetry.see_event_completed_failed(&error);
            let _ = tx_event.send(Err(error)).await;
            return;
        }
        inference_trace_attempt.record_failed(
            "stream closed before response.completed",
            upstream_request_id,
            &items_added,
        );
    });

    (
        ResponseStream {
            rx_event,
            consumer_dropped: consumer_dropped_for_stream,
        },
        rx_last_response,
    )
}

async fn finish_abandoned_provider_response(
    provider_terminal: &mut ProviderResponseTerminal,
    reason_code: &'static str,
    response_items: &[ResponseItem],
) {
    if let Err(error) = provider_terminal
        .finish_indeterminate(reason_code, response_items)
        .await
    {
        warn!(
            reason_code = error.reason_code(),
            detail = error.detail(),
            "failed to persist abandoned provider response terminal"
        );
    }
}

fn model_provider_policy_error(error: ModelProviderPolicyError) -> CodexErr {
    CodexErr::Fatal(format!(
        "model provider policy failed [{}]: {}",
        error.reason_code(),
        error.detail()
    ))
}

fn trace_compaction_policy_error(
    trace_attempt: &CompactionTraceAttempt,
    error: ModelProviderPolicyError,
) -> CodexErr {
    let error = model_provider_policy_error(error);
    trace_attempt.record_failed(&error);
    error
}

fn model_provider_policy_blocked(reason_code: String, message: String) -> CodexErr {
    CodexErr::Fatal(format!(
        "model provider request blocked by policy [{reason_code}]: {message}"
    ))
}

/// Handles a 401 response by optionally refreshing ChatGPT tokens once.
///
/// When refresh succeeds, the caller should retry the API call; otherwise
/// the mapped `CodexErr` is returned to the caller.
#[derive(Clone, Copy, Debug)]
struct UnauthorizedRecoveryExecution {
    mode: &'static str,
    phase: &'static str,
}

#[derive(Clone, Copy, Debug, Default)]
struct PendingUnauthorizedRetry {
    retry_after_unauthorized: bool,
    recovery_mode: Option<&'static str>,
    recovery_phase: Option<&'static str>,
}

impl PendingUnauthorizedRetry {
    fn from_recovery(recovery: UnauthorizedRecoveryExecution) -> Self {
        Self {
            retry_after_unauthorized: true,
            recovery_mode: Some(recovery.mode),
            recovery_phase: Some(recovery.phase),
        }
    }
}

#[derive(Clone, Debug, Default)]
struct AuthRequestTelemetryContext {
    auth_mode: Option<&'static str>,
    auth_header_attached: bool,
    auth_header_name: Option<&'static str>,
    agent_identity_telemetry: Option<AgentIdentityTelemetry>,
    retry_after_unauthorized: bool,
    recovery_mode: Option<&'static str>,
    recovery_phase: Option<&'static str>,
}

impl AuthRequestTelemetryContext {
    fn new(
        auth_mode: Option<AuthMode>,
        api_auth: &dyn AuthProvider,
        agent_identity_telemetry: Option<AgentIdentityTelemetry>,
        retry: PendingUnauthorizedRetry,
    ) -> Self {
        let auth_telemetry = auth_header_telemetry(api_auth);
        Self {
            auth_mode: auth_mode.map(|mode| match mode {
                AuthMode::ApiKey | AuthMode::BedrockApiKey | AuthMode::BedrockAccessKeys => {
                    "ApiKey"
                }
                AuthMode::Chatgpt
                | AuthMode::ChatgptAuthTokens
                | AuthMode::Headers
                | AuthMode::AgentIdentity
                | AuthMode::PersonalAccessToken => "Chatgpt",
            }),
            auth_header_attached: auth_telemetry.attached,
            auth_header_name: auth_telemetry.name,
            agent_identity_telemetry,
            retry_after_unauthorized: retry.retry_after_unauthorized,
            recovery_mode: retry.recovery_mode,
            recovery_phase: retry.recovery_phase,
        }
    }

    fn agent_identity_telemetry(&self) -> Option<&AgentIdentityTelemetry> {
        self.agent_identity_telemetry.as_ref()
    }
}

struct WebsocketConnectParams<'a> {
    session_telemetry: &'a SessionTelemetry,
    api_provider: codex_api::Provider,
    api_auth: SharedAuthProvider,
    responses_metadata: &'a CodexResponsesMetadata,
    auth_context: AuthRequestTelemetryContext,
    request_route_telemetry: RequestRouteTelemetry,
}

async fn handle_unauthorized(
    transport: TransportError,
    auth_recovery: &mut Option<UnauthorizedRecovery>,
    provider_auth_recovery_attempted: &mut bool,
    session_telemetry: &SessionTelemetry,
    provider: &SharedModelProvider,
    redact_provider_error: bool,
) -> Result<UnauthorizedRecoveryExecution> {
    let debug = redact_ephemeral_response_debug_context(
        extract_response_debug_context(&transport),
        redact_provider_error,
    );
    if !*provider_auth_recovery_attempted {
        *provider_auth_recovery_attempted = true;
        match provider.recover_from_unauthorized().await {
            Ok(ProviderUnauthorizedRecovery::Recovered) => {
                return Ok(UnauthorizedRecoveryExecution {
                    mode: "provider",
                    phase: "provider_refresh",
                });
            }
            Ok(ProviderUnauthorizedRecovery::NotConfigured) => {}
            Err(error) => {
                let recovery_error_is_retryable = error.is_retryable();
                let original = redact_ephemeral_provider_error(
                    provider.map_api_error(ApiError::Transport(transport)),
                    redact_provider_error,
                );
                let error = redact_ephemeral_provider_error(error, redact_provider_error);
                warn!(
                    error = %error,
                    original_error = %original,
                    "provider authentication recovery failed"
                );
                return Err(if recovery_error_is_retryable {
                    original
                } else {
                    error
                });
            }
        }
    }

    if let Some(recovery) = auth_recovery
        && recovery.has_next()
    {
        let mode = recovery.mode_name();
        let phase = recovery.step_name();
        return match recovery.next().await {
            Ok(step_result) => {
                session_telemetry.record_auth_recovery(
                    mode,
                    phase,
                    "recovery_succeeded",
                    debug.request_id.as_deref(),
                    debug.cf_ray.as_deref(),
                    debug.auth_error.as_deref(),
                    debug.auth_error_code.as_deref(),
                    /*recovery_reason*/ None,
                    step_result.auth_state_changed(),
                );
                emit_feedback_auth_recovery_tags(
                    mode,
                    phase,
                    "recovery_succeeded",
                    debug.request_id.as_deref(),
                    debug.cf_ray.as_deref(),
                    debug.auth_error.as_deref(),
                    debug.auth_error_code.as_deref(),
                );
                Ok(UnauthorizedRecoveryExecution { mode, phase })
            }
            Err(RefreshTokenError::Permanent(failed)) => {
                session_telemetry.record_auth_recovery(
                    mode,
                    phase,
                    "recovery_failed_permanent",
                    debug.request_id.as_deref(),
                    debug.cf_ray.as_deref(),
                    debug.auth_error.as_deref(),
                    debug.auth_error_code.as_deref(),
                    /*recovery_reason*/ None,
                    /*auth_state_changed*/ None,
                );
                emit_feedback_auth_recovery_tags(
                    mode,
                    phase,
                    "recovery_failed_permanent",
                    debug.request_id.as_deref(),
                    debug.cf_ray.as_deref(),
                    debug.auth_error.as_deref(),
                    debug.auth_error_code.as_deref(),
                );
                Err(CodexErr::RefreshTokenFailed(failed))
            }
            Err(RefreshTokenError::Transient(other)) => {
                session_telemetry.record_auth_recovery(
                    mode,
                    phase,
                    "recovery_failed_transient",
                    debug.request_id.as_deref(),
                    debug.cf_ray.as_deref(),
                    debug.auth_error.as_deref(),
                    debug.auth_error_code.as_deref(),
                    /*recovery_reason*/ None,
                    /*auth_state_changed*/ None,
                );
                emit_feedback_auth_recovery_tags(
                    mode,
                    phase,
                    "recovery_failed_transient",
                    debug.request_id.as_deref(),
                    debug.cf_ray.as_deref(),
                    debug.auth_error.as_deref(),
                    debug.auth_error_code.as_deref(),
                );
                Err(CodexErr::Io(other))
            }
        };
    }

    let (mode, phase, recovery_reason) = match auth_recovery.as_ref() {
        Some(recovery) => (
            recovery.mode_name(),
            recovery.step_name(),
            Some(recovery.unavailable_reason()),
        ),
        None => ("none", "none", Some("auth_manager_missing")),
    };
    session_telemetry.record_auth_recovery(
        mode,
        phase,
        "recovery_not_run",
        debug.request_id.as_deref(),
        debug.cf_ray.as_deref(),
        debug.auth_error.as_deref(),
        debug.auth_error_code.as_deref(),
        recovery_reason,
        /*auth_state_changed*/ None,
    );
    emit_feedback_auth_recovery_tags(
        mode,
        phase,
        "recovery_not_run",
        debug.request_id.as_deref(),
        debug.cf_ray.as_deref(),
        debug.auth_error.as_deref(),
        debug.auth_error_code.as_deref(),
    );

    Err(redact_ephemeral_provider_error(
        provider.map_api_error(ApiError::Transport(transport)),
        redact_provider_error,
    ))
}

fn api_error_http_status(error: &ApiError) -> Option<u16> {
    match error {
        ApiError::Transport(TransportError::Http { status, .. }) => Some(status.as_u16()),
        _ => None,
    }
}

fn redacted_transport_error_message(error: &TransportError) -> String {
    match error {
        TransportError::Http { status, .. } => format!("http {}", status.as_u16()),
        TransportError::RetryLimit => "retry limit reached".to_string(),
        TransportError::Timeout => "timeout".to_string(),
        TransportError::Network(_) => "network error".to_string(),
        TransportError::Connection(_) => "connection error".to_string(),
        TransportError::Build(_) => "request build error".to_string(),
    }
}

const EPHEMERAL_PROVIDER_ERROR: &str = "ephemeral model-provider request failed";

fn redact_ephemeral_provider_error(error: CodexErr, redact: bool) -> CodexErr {
    if !redact {
        return error;
    }
    let retry_delay = error.retry_delay();
    let redacted = match error.details() {
        CodexErrorDetails::UnexpectedStatus(response) => {
            CodexErr::UnexpectedStatus(UnexpectedResponseError {
                status: response.status,
                body: EPHEMERAL_PROVIDER_ERROR.to_string(),
                user_message: None,
                url: None,
                cf_ray: None,
                request_id: None,
                identity_authorization_error: None,
                identity_error_code: None,
            })
        }
        CodexErrorDetails::InvalidRequest(_) => {
            CodexErr::InvalidRequest(EPHEMERAL_PROVIDER_ERROR.to_string())
        }
        CodexErrorDetails::CyberPolicy { .. } => CodexErr::new(CodexErrorDetails::CyberPolicy {
            message: "ephemeral model-provider request rejected by cyber policy".to_string(),
        }),
        CodexErrorDetails::Stream(_)
        | CodexErrorDetails::ResponseStreamFailed(_)
        | CodexErrorDetails::ConnectionFailed(_) => {
            CodexErr::Stream(EPHEMERAL_PROVIDER_ERROR.to_string())
        }
        CodexErrorDetails::RetryLimit(retry) => CodexErr::RetryLimit(RetryLimitReachedError {
            status: retry.status,
            request_id: None,
        }),
        CodexErrorDetails::UsageLimitReached(usage) => {
            CodexErr::UsageLimitReached(UsageLimitReachedError {
                plan_type: usage.plan_type.clone(),
                resets_at: usage.resets_at.to_owned(),
                rate_limits: None,
                promo_message: None,
                rate_limit_reached_type: usage.rate_limit_reached_type.to_owned(),
            })
        }
        CodexErrorDetails::ContextWindowExceeded
        | CodexErrorDetails::Timeout
        | CodexErrorDetails::RequestTimeout
        | CodexErrorDetails::InvalidImageRequest()
        | CodexErrorDetails::ServerOverloaded
        | CodexErrorDetails::QuotaExceeded
        | CodexErrorDetails::UsageNotIncluded
        | CodexErrorDetails::InternalServerError => return error,
        _ => CodexErr::Stream(EPHEMERAL_PROVIDER_ERROR.to_string()),
    };
    match retry_delay {
        Some(delay) => redacted.with_retry_delay(delay),
        None => redacted,
    }
}

fn redact_ephemeral_response_debug_context(
    mut context: ResponseDebugContext,
    redact: bool,
) -> ResponseDebugContext {
    if !redact {
        return context;
    }
    context.request_id = None;
    context.cf_ray = None;
    context.auth_error = None;
    context.auth_error_code = None;
    context
}

struct ApiTelemetry {
    session_telemetry: SessionTelemetry,
    auth_context: AuthRequestTelemetryContext,
    request_route_telemetry: RequestRouteTelemetry,
    auth_env_telemetry: AuthEnvTelemetry,
    redact_provider_diagnostics: bool,
}

impl ApiTelemetry {
    fn new(
        session_telemetry: SessionTelemetry,
        auth_context: AuthRequestTelemetryContext,
        request_route_telemetry: RequestRouteTelemetry,
        auth_env_telemetry: AuthEnvTelemetry,
        redact_provider_diagnostics: bool,
    ) -> Self {
        Self {
            session_telemetry,
            auth_context,
            request_route_telemetry,
            auth_env_telemetry,
            redact_provider_diagnostics,
        }
    }
}

impl RequestTelemetry for ApiTelemetry {
    fn on_request(
        &self,
        attempt: u64,
        status: Option<StatusCode>,
        error: Option<&TransportError>,
        duration: Duration,
    ) {
        let error_message = error.map(|error| {
            if self.redact_provider_diagnostics {
                redacted_transport_error_message(error)
            } else {
                telemetry_transport_error_message(error)
            }
        });
        let status = status.map(|s| s.as_u16());
        let debug = redact_ephemeral_response_debug_context(
            error
                .map(extract_response_debug_context)
                .unwrap_or_default(),
            self.redact_provider_diagnostics,
        );
        self.session_telemetry.record_api_request(
            attempt,
            status,
            error_message.as_deref(),
            duration,
            self.auth_context.auth_header_attached,
            self.auth_context.auth_header_name,
            self.auth_context.retry_after_unauthorized,
            self.auth_context.recovery_mode,
            self.auth_context.recovery_phase,
            self.request_route_telemetry.endpoint,
            debug.request_id.as_deref(),
            debug.cf_ray.as_deref(),
            debug.auth_error.as_deref(),
            debug.auth_error_code.as_deref(),
            self.auth_context.agent_identity_telemetry(),
        );
        emit_feedback_request_tags_with_auth_env(
            &FeedbackRequestTags {
                endpoint: self.request_route_telemetry.endpoint,
                auth_header_attached: self.auth_context.auth_header_attached,
                auth_header_name: self.auth_context.auth_header_name,
                auth_mode: self.auth_context.auth_mode,
                auth_retry_after_unauthorized: Some(self.auth_context.retry_after_unauthorized),
                auth_recovery_mode: self.auth_context.recovery_mode,
                auth_recovery_phase: self.auth_context.recovery_phase,
                auth_connection_reused: None,
                auth_request_id: debug.request_id.as_deref(),
                auth_cf_ray: debug.cf_ray.as_deref(),
                auth_error: debug.auth_error.as_deref(),
                auth_error_code: debug.auth_error_code.as_deref(),
                auth_recovery_followup_success: self
                    .auth_context
                    .retry_after_unauthorized
                    .then_some(error.is_none()),
                auth_recovery_followup_status: self
                    .auth_context
                    .retry_after_unauthorized
                    .then_some(status)
                    .flatten(),
            },
            &self.auth_env_telemetry,
        );
    }
}

impl SseTelemetry for ApiTelemetry {
    fn on_sse_poll(
        &self,
        result: &std::result::Result<
            Option<std::result::Result<Event, EventStreamError<TransportError>>>,
            tokio::time::error::Elapsed,
        >,
        duration: Duration,
    ) {
        if self.redact_provider_diagnostics {
            self.session_telemetry
                .log_redacted_sse_event(result, duration);
        } else {
            self.session_telemetry.log_sse_event(result, duration);
        }
    }
}

impl WebsocketTelemetry for ApiTelemetry {
    fn on_ws_request(&self, duration: Duration, error: Option<&ApiError>, connection_reused: bool) {
        let error_message = error.map(telemetry_api_error_message);
        let status = error.and_then(api_error_http_status);
        let debug = error
            .map(extract_response_debug_context_from_api_error)
            .unwrap_or_default();
        self.session_telemetry.record_websocket_request(
            duration,
            error_message.as_deref(),
            connection_reused,
            self.auth_context.agent_identity_telemetry(),
        );
        emit_feedback_request_tags_with_auth_env(
            &FeedbackRequestTags {
                endpoint: self.request_route_telemetry.endpoint,
                auth_header_attached: self.auth_context.auth_header_attached,
                auth_header_name: self.auth_context.auth_header_name,
                auth_mode: self.auth_context.auth_mode,
                auth_retry_after_unauthorized: Some(self.auth_context.retry_after_unauthorized),
                auth_recovery_mode: self.auth_context.recovery_mode,
                auth_recovery_phase: self.auth_context.recovery_phase,
                auth_connection_reused: Some(connection_reused),
                auth_request_id: debug.request_id.as_deref(),
                auth_cf_ray: debug.cf_ray.as_deref(),
                auth_error: debug.auth_error.as_deref(),
                auth_error_code: debug.auth_error_code.as_deref(),
                auth_recovery_followup_success: self
                    .auth_context
                    .retry_after_unauthorized
                    .then_some(error.is_none()),
                auth_recovery_followup_status: self
                    .auth_context
                    .retry_after_unauthorized
                    .then_some(status)
                    .flatten(),
            },
            &self.auth_env_telemetry,
        );
    }

    fn on_ws_event(
        &self,
        result: &std::result::Result<Option<std::result::Result<Message, Error>>, ApiError>,
        duration: Duration,
    ) {
        self.session_telemetry
            .record_websocket_event(result, duration);
    }
}

#[cfg(test)]
#[path = "client_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "client_provider_policy_tests.rs"]
mod provider_policy_tests;
