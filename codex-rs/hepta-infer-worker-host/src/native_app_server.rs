//! Hosted model execution through the existing exact-generation Agent/App Server.
//!
//! This profile observes real turn events and token usage. It makes no claim
//! about local weights, accelerator memory, artifact selection or training.

use std::collections::HashMap;
use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_app_server_client::AppServerEvent;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_client::RemoteAppServerObservedEvent;
use codex_app_server_client::RemoteObservedTypedRequestError;
use codex_app_server_protocol::AdditionalContextEntry;
use codex_app_server_protocol::AdditionalContextKind;
use codex_app_server_protocol::AskForApproval;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::SandboxMode;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::ThreadUnsubscribeParams;
use codex_app_server_protocol::TurnInterruptParams;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::HealthSnapshot;
use codex_hepta_codex_adapter::APP_SERVER_V2_PROTOCOL_ID;
use codex_hepta_codex_adapter::AdapterStatus;
use codex_hepta_codex_adapter::AppServerRequestBinding;
use codex_hepta_codex_adapter::CodexOperationIntent;
use codex_hepta_codex_adapter::TURN_START_METHOD_ID;
use codex_hepta_codex_adapter::adapt_observed_event;
use codex_hepta_codex_adapter::adapt_observed_server_rejection;
use codex_hepta_codex_adapter::adapt_observed_thread_read_reconciliation;
use codex_hepta_codex_adapter::adapt_request;
use codex_hepta_codex_adapter::request_digest as codex_request_digest;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::EnteredUseToken;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
pub use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeDispatchRejection;
use codex_hepta_infer_core::durable_control::native::NativeDispatchRejectionStatus;
pub use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
pub use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
pub use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_utils_absolute_path::AbsolutePathBuf;

#[path = "native_run_control.rs"]
mod control;
pub use control::NativeAdmission;
use tokio::time::Instant;
use tokio::time::timeout;
use tokio::time::timeout_at;
use tokio_util::sync::CancellationToken;

const MAX_PROMPT_BYTES: usize = 32 * 1024;
const MAX_OUTPUT_BYTES: usize = 1024 * 1024;
const MAX_MODEL_CONTEXT_BYTES: usize = 8 * 1024;
const RPC_TIMEOUT: Duration = Duration::from_secs(5);
const INTERRUPT_GRACE: Duration = Duration::from_secs(3);
const TURN_START_RECONCILE_GRACE: Duration = Duration::from_secs(2);
const LOCAL_CANCELLED: &str = "cancelled";
const LOCAL_DEADLINE_ELAPSED: &str = "deadline elapsed";

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

pub type TurnStartAuthorityFuture<'a> =
    Pin<Box<dyn Future<Output = Result<VerifiedUseToken>> + Send + 'a>>;

/// Host-owned final-use port. runtime.codex can request a claim for the exact
/// final binding, but it cannot construct a VerifiedUseToken itself.
pub trait TurnStartAuthorizer: Send + Sync {
    fn claim<'a>(&'a self, binding: FinalUseBinding) -> TurnStartAuthorityFuture<'a>;
}

/// Local operator-selected connection, fenced by the existing Agent identity.
pub struct NativeWorkerConfig {
    pub agentd_socket: PathBuf,
    pub agent_id: AgentId,
    pub generation: u64,
    pub model: String,
    pub timeout: Duration,
}

/// A real provider client. Each new request uses a fresh ephemeral thread
/// behind the exact Agent identity. The control journal owns dispatch identity,
/// local slot admission and settlement; duplicate requests never start a turn.
pub struct AppServerModelDriver {
    config: NativeWorkerConfig,
    turn_start_authorizer: Option<Arc<dyn TurnStartAuthorizer>>,
}

#[derive(Clone)]
struct CodexTurnBinding {
    intent: CodexOperationIntent,
    turn_id: StableId,
}

impl AppServerModelDriver {
    pub fn new(config: NativeWorkerConfig) -> Result<Self> {
        if !config.agentd_socket.is_absolute()
            || config.generation == 0
            || config.model.is_empty()
            || config.model.len() > 256
            || config.timeout.is_zero()
            || config.timeout > Duration::from_secs(3600)
        {
            return Err("invalid native worker configuration".into());
        }
        Ok(Self {
            config,
            turn_start_authorizer: None,
        })
    }

    /// Attach the trusted-host final-use port. The production CLI requires this
    /// port and never owns an issuer private key.
    pub fn with_turn_start_authorizer(mut self, authorizer: Arc<dyn TurnStartAuthorizer>) -> Self {
        self.turn_start_authorizer = Some(authorizer);
        self
    }

    /// Reconcile a previously prepared/dispatched operation without issuing a
    /// new turn/start. Only an opaque thread/read response from the current
    /// exact-generation Agent/App Server may settle the durable record.
    pub(super) async fn reconcile_existing(
        &self,
        record: &NativeRunRecord,
        expected_prompt: &str,
    ) -> Result<Option<NativeRunOutput>> {
        if record.request.principal_id != self.config.agent_id.to_string()
            || record.request.worker_generation != self.config.generation
            || record.request.model != self.config.model
        {
            return Err("durable native request no longer matches configured Agent/model".into());
        }
        let Some(dispatch) = record.dispatch.as_ref() else {
            return Ok(None);
        };
        let (
            Some(payload_digest),
            Some(expected_request_digest),
            Some(app_server_version),
            Some(protocol_id),
            Some(source_admission_digest),
            Some(codex_home_digest),
            Some(original_connection_id),
            Some(session_id),
            Some(deadline_ms),
            Some(_authority_witness),
        ) = (
            dispatch.codex_payload_digest.as_deref(),
            dispatch.codex_request_digest.as_deref(),
            dispatch.app_server_version.as_deref(),
            dispatch.protocol_id.as_deref(),
            dispatch.codex_source_admission_digest.as_deref(),
            dispatch.codex_home_digest.as_deref(),
            dispatch.codex_connection_id,
            dispatch.codex_session_id.as_deref(),
            dispatch.codex_deadline_ms,
            dispatch.codex_authority_witness_sha256.as_deref(),
        )
        else {
            // Historical dispatches predate exact runtime.codex recovery binding.
            return Ok(None);
        };
        if protocol_id != APP_SERVER_V2_PROTOCOL_ID {
            return Err("durable runtime.codex protocol is not App Server v2".into());
        }

        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let health = owner.health().await?;
        if !health.ready || health.fenced {
            return Ok(None);
        }
        let ingress = owner.session_ingress().await?;
        let socket_path = AbsolutePathBuf::from_absolute_path(ingress.socket_path)?;
        let mut client = match timeout(
            RPC_TIMEOUT,
            RemoteAppServerClient::connect_with_bounded_events(
                RemoteAppServerConnectArgs {
                    endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
                    client_name: "hepta-infer-worker-reconciler".to_string(),
                    client_version: env!("CARGO_PKG_VERSION").to_string(),
                    experimental_api: true,
                    mcp_server_openai_form_elicitation: false,
                    opt_out_notification_methods: Vec::new(),
                    channel_capacity: 32,
                },
                /*event_channel_capacity*/ 64,
            ),
        )
        .await
        {
            Ok(Ok(client)) => client,
            _ => return Ok(None),
        };
        let observed_home = match client.codex_home() {
            Some(home) => home.to_string(),
            None => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(None);
            }
        };
        let expected_home_digest: Digest32 = codex_home_digest.parse()?;
        if Digest32::of_bytes(observed_home.as_bytes()) != expected_home_digest
            || Some(observed_home.as_str()) != health.home_root.to_str()
            || client.server_version() != Some(app_server_version)
        {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(
                "reconciliation App Server identity does not match durable dispatch".into(),
            );
        }

        let expected_input = vec![UserInput::Text {
            text: expected_prompt.to_string(),
            text_elements: Vec::new(),
        }];
        let payload_digest: Digest32 = payload_digest.parse()?;
        let source_admission_digest: Digest32 = source_admission_digest.parse()?;
        if source_admission_digest.to_string() != record.request.payload_digest {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("durable runtime.codex source admission binding drifted".into());
        }
        let intent = CodexOperationIntent {
            operation_id: StableId::new(format!(
                "native:{}",
                Digest32::of_bytes(record.request.request_id.as_bytes())
            ))?,
            thread_id: StableId::new(dispatch.thread_id.clone())?,
            method_id: StableId::new(TURN_START_METHOD_ID)?,
            payload_digest,
            lease_payload_digest: payload_digest,
            deadline_ms,
            app_server_binding: Some(AppServerRequestBinding {
                source_admission_digest,
                agent_generation: Generation::new(record.request.worker_generation)?,
                session_id: StableId::new(session_id.to_string())?,
                client_user_message_id: StableId::new(record.request.request_id.clone())?,
                user_input_digest: Digest32::of_bytes(&serde_json::to_vec(&expected_input)?),
                protocol_id: StableId::new(protocol_id.to_string())?,
                app_server_version: app_server_version.to_string(),
                codex_home_digest: expected_home_digest,
                connection_id: original_connection_id,
            }),
        };
        if codex_request_digest(&intent).to_string() != expected_request_digest {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("durable runtime.codex request digest mismatch during recovery".into());
        }

        let observed = match timeout(
            RPC_TIMEOUT,
            client.request_typed_observed_response::<ThreadReadResponse>(
                ClientRequest::ThreadRead {
                    request_id: RequestId::Integer(20),
                    params: ThreadReadParams {
                        thread_id: dispatch.thread_id.clone(),
                        include_turns: true,
                    },
                },
            ),
        )
        .await
        {
            Ok(Ok(observed)) => observed,
            _ => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(None);
            }
        };
        if observed.response().thread.model_provider != dispatch.model_provider {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("reconciled model provider does not match durable dispatch".into());
        }
        let receipt = adapt_observed_thread_read_reconciliation(
            &intent,
            &record.request.request_id,
            &expected_input,
            &observed,
        )?;
        let Some(receipt) = receipt else {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Ok(None);
        };
        let turn_id = receipt
            .turn_id
            .as_ref()
            .ok_or("reconciled terminal receipt omitted turn id")?
            .as_str();
        let turn = observed
            .response()
            .thread
            .turns
            .iter()
            .find(|turn| turn.id == turn_id)
            .ok_or("reconciled terminal receipt turn disappeared")?;

        let mut output_text = String::new();
        for item in &turn.items {
            if let ThreadItem::AgentMessage { text, .. } = item {
                if text.len() > MAX_OUTPUT_BYTES.saturating_sub(output_text.len()) {
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Err("reconciled output byte limit exceeded".into());
                }
                output_text.push_str(text);
            }
        }
        let (status, boundary_status) = match receipt.status {
            AdapterStatus::Succeeded => {
                (NativeRunStatus::Completed, NativeBoundaryStatus::Succeeded)
            }
            AdapterStatus::Failed => (NativeRunStatus::Failed, NativeBoundaryStatus::Failed),
            AdapterStatus::Interrupted => (
                NativeRunStatus::Interrupted,
                NativeBoundaryStatus::Interrupted,
            ),
            _ => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err("thread/read reconciliation produced nonterminal status".into());
            }
        };
        let mut output = NativeRunOutput {
            thread_id: dispatch.thread_id.clone(),
            turn_id: turn.id.clone(),
            model: record.request.model.clone(),
            model_provider: dispatch.model_provider.clone(),
            status,
            boundary_status,
            output: output_text,
            observed_output_tokens: None,
            terminal_observed: true,
            owner_authority: NativeOwnerAuthority::Unverified,
            stop_reason: turn
                .error
                .as_ref()
                .map(|error| error.message.chars().take(1024).collect()),
            codex_terminal_correlation_digest: Some(
                receipt
                    .correlation_digest
                    .ok_or("reconciled terminal receipt omitted correlation digest")?
                    .to_string(),
            ),
        };
        let _ =
            verify_owner_health(&mut output, owner.health(), Instant::now() + RPC_TIMEOUT).await;
        downgrade_for_owner_loss(&mut output);
        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
        Ok(Some(output))
    }

    /// Execute once. Transport loss after turn/start remains indeterminate and
    /// must never be automatically replayed as a fresh request.
    async fn run_once(
        &self,
        control: &mut DurableInferenceControl,
        request_id: &str,
        prompt: String,
        context_query: Option<String>,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        if prompt.is_empty() || prompt.len() > MAX_PROMPT_BYTES {
            return Err("prompt must contain 1..32768 bytes".into());
        }
        if cancellation.is_cancelled() {
            return Err("cancelled before admission".into());
        }
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let health = owner.health().await?;
        if !health.ready || health.fenced {
            return Err("Agent is not ready".into());
        }
        let context = match context_query {
            Some(query) => Some(owner.cognitive_context(query, /*limit*/ 4).await?),
            None => None,
        };
        let additional_context = context
            .map(|snapshot| -> Result<_> {
                let value = serde_json::to_string(&snapshot)?;
                if value.len() > MAX_MODEL_CONTEXT_BYTES {
                    return Err("verified context exceeds the model attachment byte limit".into());
                }
                Ok(HashMap::from([(
                    "hepta-cognitive-owner".to_string(),
                    AdditionalContextEntry {
                        value,
                        kind: AdditionalContextKind::Untrusted,
                    },
                )]))
            })
            .transpose()?;
        let ingress = owner.session_ingress().await?;
        let ingress_socket_path = ingress.socket_path;
        let socket_path = AbsolutePathBuf::from_absolute_path(ingress_socket_path.clone())?;
        let mut client = timeout(
            RPC_TIMEOUT,
            RemoteAppServerClient::connect_with_bounded_events(
                RemoteAppServerConnectArgs {
                    endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
                    client_name: "hepta-infer-worker".to_string(),
                    client_version: env!("CARGO_PKG_VERSION").to_string(),
                    experimental_api: true,
                    mcp_server_openai_form_elicitation: false,
                    opt_out_notification_methods: Vec::new(),
                    channel_capacity: 32,
                },
                /*event_channel_capacity*/ 256,
            ),
        )
        .await??;
        let codex_home = client
            .codex_home()
            .ok_or("App Server initialize response omitted codex home")?
            .to_string();
        if Some(codex_home.as_str()) != health.home_root.to_str() {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("App Server home does not match the owning Agent".into());
        }
        let codex_home_digest = Digest32::of_bytes(codex_home.as_bytes());
        let connection_id = client.connection_id();
        let app_server_version = client
            .server_version()
            .ok_or("App Server initialize response omitted server version")?
            .to_string();
        let started: ThreadStartResponse = timeout(
            RPC_TIMEOUT,
            client.request_typed(ClientRequest::ThreadStart {
                request_id: RequestId::Integer(1),
                params: ThreadStartParams {
                    model: Some(self.config.model.clone()),
                    cwd: health.workspace.to_str().map(str::to_string),
                    approval_policy: Some(AskForApproval::Never),
                    sandbox: Some(SandboxMode::ReadOnly),
                    ephemeral: Some(true),
                    environments: Some(Vec::new()),
                    ..Default::default()
                },
            }),
        )
        .await??;
        if started.model != self.config.model {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("provider substituted the requested model".into());
        }
        // Recheck the actual generation after acquiring context and connecting.
        owner.session_ingress().await?;
        if cancellation.is_cancelled() {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("cancelled before model dispatch".into());
        }
        let turn_params = TurnStartParams {
            thread_id: started.thread.id.clone(),
            client_user_message_id: Some(request_id.to_string()),
            input: vec![UserInput::Text {
                text: prompt,
                text_elements: Vec::new(),
            }],
            additional_context,
            environments: Some(Vec::new()),
            ..Default::default()
        };
        let turn_payload = serde_json::to_vec(&turn_params)?;
        let payload_digest = Digest32::of_bytes(&turn_payload);
        let user_input_digest = Digest32::of_bytes(&serde_json::to_vec(&turn_params.input)?);
        let adapted_at_ms = unix_time_ms()?;
        let execution_timeout_ms = u64::try_from(self.config.timeout.as_millis())
            .map_err(|_| "native execution timeout does not fit u64 milliseconds")?;
        let source_admission_digest: Digest32 = control
            .native_record(request_id)
            .ok_or("missing durable native admission")?
            .request
            .payload_digest
            .parse()?;
        let adapter_intent = CodexOperationIntent {
            operation_id: StableId::new(format!(
                "native:{}",
                Digest32::of_bytes(request_id.as_bytes())
            ))?,
            thread_id: StableId::new(started.thread.id.clone())?,
            method_id: StableId::new(TURN_START_METHOD_ID)?,
            payload_digest,
            lease_payload_digest: payload_digest,
            deadline_ms: adapted_at_ms
                .checked_add(execution_timeout_ms)
                .ok_or("native execution deadline overflow")?,
            app_server_binding: Some(AppServerRequestBinding {
                source_admission_digest,
                agent_generation: Generation::new(self.config.generation)?,
                session_id: StableId::new(started.thread.session_id.clone())?,
                client_user_message_id: StableId::new(request_id.to_string())?,
                user_input_digest,
                protocol_id: StableId::new(APP_SERVER_V2_PROTOCOL_ID)?,
                app_server_version: app_server_version.clone(),
                codex_home_digest,
                connection_id,
            }),
        };
        let request_receipt = adapt_request(adapted_at_ms, adapter_intent.clone())?;
        let authority_binding = final_use_binding(
            &self.config.agent_id,
            &adapter_intent,
            &started.model,
            &started.model_provider,
        )?;
        let authorizer = self
            .turn_start_authorizer
            .as_ref()
            .ok_or("runtime.codex turn/start final-use authorizer is required")?;
        let claim_budget = remaining_before(adapter_intent.deadline_ms)?;
        let verified_use = timeout(claim_budget, authorizer.claim(authority_binding.clone()))
            .await
            .map_err(|_| "final-use authority request exceeded runtime.codex deadline")??;
        let authority_witness = Digest32::from_array(verified_use.witness_sha256()).to_string();

        let (_, pre_effect_abort) = control.dispatch_native_with_pre_effect_abort(
            request_id,
            NativeDispatch {
                thread_id: started.thread.id.clone(),
                model_provider: started.model_provider.clone(),
                context_digest: control::digest(&serde_json::to_vec(
                    &turn_params.additional_context,
                )?),
                codex_payload_digest: Some(payload_digest.to_string()),
                codex_request_digest: Some(request_receipt.request_digest.to_string()),
                app_server_version: Some(app_server_version.clone()),
                protocol_id: Some(APP_SERVER_V2_PROTOCOL_ID.to_string()),
                codex_source_admission_digest: Some(source_admission_digest.to_string()),
                codex_home_digest: Some(codex_home_digest.to_string()),
                codex_connection_id: Some(connection_id),
                codex_session_id: Some(started.thread.session_id.clone()),
                codex_deadline_ms: Some(adapter_intent.deadline_ms),
                codex_authority_witness_sha256: Some(authority_witness.clone()),
            },
        )?;
        verify_persisted_dispatch_binding(
            control,
            request_id,
            payload_digest,
            request_receipt.request_digest,
            source_admission_digest,
            codex_home_digest,
            connection_id,
            &started.thread.session_id,
            adapter_intent.deadline_ms,
            &authority_witness,
            &app_server_version,
        )?;

        let post_health = match owner.health().await {
            Ok(health) => health,
            Err(error) => {
                let reason = format!("owner health failed before final-use entry: {error}");
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
            }
        };
        let current_ingress = match owner.session_ingress().await {
            Ok(ingress) => ingress,
            Err(error) => {
                let reason = format!("owner ingress failed before final-use entry: {error}");
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
            }
        };
        if let Err(error) = validate_post_authority_fence(
            &post_health,
            &ingress_socket_path,
            &current_ingress.socket_path,
            cancellation.is_cancelled(),
            unix_time_ms()?,
            adapter_intent.deadline_ms,
        ) {
            let reason: String = error.to_string().chars().take(1024).collect();
            control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(reason.into());
        }
        let send_budget = remaining_before(adapter_intent.deadline_ms)?.min(RPC_TIMEOUT);
        let entered_use = match verified_use.enter(&authority_binding) {
            Ok(entered) if entered.matches(&authority_binding) => entered,
            Ok(_) => {
                let reason = "kernel.authority final-use binding mismatch at entry".to_string();
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
            }
            Err(error) => {
                let reason = format!("kernel.authority final-use entry denied: {error}");
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
            }
        };
        // From here on, a missing acknowledgement is reconcile-only. Recovery
        // cannot recreate the local pre-effect proof that is deliberately lost.
        drop(pre_effect_abort);
        let response = timeout(
            send_budget,
            send_authorized_turn_start(&mut client, entered_use, turn_params),
        )
        .await;
        let turn = match response {
            Ok(Ok(response)) => response.turn,
            Ok(Err(RemoteObservedTypedRequestError::Server { observed })) => {
                let receipt = adapt_observed_server_rejection(&adapter_intent, &observed)?;
                let (status, retry_safe_before_admission) = match receipt.status {
                    AdapterStatus::Overloaded => (NativeDispatchRejectionStatus::Overloaded, true),
                    AdapterStatus::Rejected => (NativeDispatchRejectionStatus::Rejected, false),
                    _ => return Err("unexpected adapter rejection status".into()),
                };
                let response_digest = receipt
                    .response_digest
                    .ok_or("server rejection receipt omitted response digest")?;
                let reason: String = observed.error().message.chars().take(1024).collect();
                control.reject_native_before_start(
                    request_id,
                    NativeDispatchRejection {
                        status,
                        reason: reason.clone(),
                        response_digest: response_digest.to_string(),
                        retry_safe_before_admission,
                    },
                )?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(format!("turn/start rejected by App Server: {reason}").into());
            }
            Ok(Err(error)) => {
                if let Some(turn) = reconcile_turn_start(&mut client, &started.thread.id).await? {
                    turn
                } else {
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Ok(indeterminate_start_output(
                        started,
                        format!(
                            "turn/start transport outcome unknown ({error}); reconciliation found no exact turn; do not replay"
                        ),
                    ));
                }
            }
            Err(_) => {
                if let Some(turn) = reconcile_turn_start(&mut client, &started.thread.id).await? {
                    turn
                } else {
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Ok(indeterminate_start_output(
                        started,
                        "turn/start timed out; reconciliation found no exact turn; do not replay"
                            .to_string(),
                    ));
                }
            }
        };
        let binding = CodexTurnBinding {
            intent: adapter_intent,
            turn_id: StableId::new(turn.id.clone())?,
        };
        let mut output = NativeRunOutput {
            thread_id: started.thread.id,
            turn_id: turn.id,
            model: started.model,
            model_provider: started.model_provider,
            status: NativeRunStatus::Indeterminate,
            boundary_status: NativeBoundaryStatus::Indeterminate,
            output: String::new(),
            observed_output_tokens: None,
            terminal_observed: false,
            owner_authority: NativeOwnerAuthority::Unverified,
            stop_reason: None,
            codex_terminal_correlation_digest: None,
        };
        if let Err(error) = control.native_started(request_id, output.turn_id.clone()) {
            interrupt(&mut client, &output).await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(error.into());
        }
        let deadline =
            Instant::now() + observation_budget_from(unix_time_ms()?, binding.intent.deadline_ms);
        let result = self
            .observe(
                &mut client,
                &mut output,
                deadline,
                cancellation,
                Some(&owner),
                &binding,
            )
            .await;
        if let Err(reason) = result {
            output.boundary_status = match reason.as_str() {
                LOCAL_CANCELLED => NativeBoundaryStatus::Cancelled,
                LOCAL_DEADLINE_ELAPSED => NativeBoundaryStatus::TimedOut,
                _ => NativeBoundaryStatus::Quarantined,
            };
            output.stop_reason = Some(reason);
            // Persist cancellation intent, but still interrupt if that write
            // fails. A failed journal write fences later admission/settlement.
            // Commit observed authority loss before waiting for interruption:
            // a process crash must not erase it from a later settlement.
            let loss_recorded =
                if matches!(output.owner_authority, NativeOwnerAuthority::Lost { .. }) {
                    control
                        .settle_native(request_id, output.clone())
                        .map(|_| ())
                } else {
                    Ok(())
                };
            let cancel_recorded = control.cancel_native(request_id);
            interrupt(&mut client, &output).await;
            let grace = CancellationToken::new();
            let _ = self
                .observe(
                    &mut client,
                    &mut output,
                    Instant::now() + INTERRUPT_GRACE,
                    &grace,
                    /*owner*/ None,
                    &binding,
                )
                .await;
            loss_recorded?;
            cancel_recorded?;
        }
        if output.terminal_observed {
            let _ = timeout(
                RPC_TIMEOUT,
                client.request(ClientRequest::ThreadUnsubscribe {
                    request_id: RequestId::Integer(4),
                    params: ThreadUnsubscribeParams {
                        thread_id: output.thread_id.clone(),
                    },
                }),
            )
            .await;
        }
        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
        if output.terminal_observed {
            // Even if select! saw Completed before a ready health tick, verify
            // this exact owner again unless already lost. Grace observes facts and
            // cannot restore authority lost earlier in the run.
            let _ = verify_owner_health(&mut output, owner.health(), Instant::now() + RPC_TIMEOUT)
                .await;
            downgrade_for_owner_loss(&mut output);
        }
        Ok(output)
    }

    async fn observe(
        &self,
        client: &mut RemoteAppServerClient,
        output: &mut NativeRunOutput,
        deadline: Instant,
        cancellation: &CancellationToken,
        owner: Option<&AgentdClient>,
        binding: &CodexTurnBinding,
    ) -> std::result::Result<(), String> {
        let mut health_tick = tokio::time::interval(Duration::from_millis(500));
        loop {
            let event = tokio::select! {
                _ = cancellation.cancelled() => return Err(LOCAL_CANCELLED.to_string()),
                _ = health_tick.tick(), if owner.is_some() => {
                    if let Some(owner) = owner {
                        verify_owner_health(output, owner.health(), deadline).await?;
                    }
                    continue;
                },
                event = timeout_at(deadline, client.next_observed_event()) => event
                    .map_err(|_| LOCAL_DEADLINE_ELAPSED.to_string())?
                    .ok_or_else(|| "provider event stream ended".to_string())?,
            };
            match event.event() {
                AppServerEvent::ServerNotification(_) => {
                    if observe_event(output, &event, binding)? {
                        return Ok(());
                    }
                }
                AppServerEvent::ServerRequest(request) => {
                    // Inference does not grant tool/approval authority.
                    timeout_at(
                        deadline,
                        client.reject_server_request(
                            request.id().clone(),
                            JSONRPCErrorError {
                                code: -32000,
                                message: "native inference worker does not grant approvals"
                                    .to_string(),
                                data: None,
                            },
                        ),
                    )
                    .await
                    .map_err(|_| "approval rejection timed out".to_string())?
                    .map_err(|error| error.to_string())?;
                }
                AppServerEvent::Lagged { .. } => return Err("provider events lost".to_string()),
                AppServerEvent::Disconnected { message } => return Err(message.clone()),
            }
        }
    }
}

fn final_use_binding(
    agent_id: &AgentId,
    intent: &CodexOperationIntent,
    model: &str,
    model_provider: &str,
) -> Result<FinalUseBinding> {
    let binding = intent
        .app_server_binding
        .as_ref()
        .ok_or("runtime.codex product binding is required for final-use authority")?;
    let scope = serde_json::to_vec(&(
        "hepta.runtime.codex.turn-start.scope.v2",
        agent_id.to_string(),
        binding.session_id.as_str(),
        intent.thread_id.as_str(),
        model,
        model_provider,
        binding.agent_generation.get(),
        binding.protocol_id.as_str(),
        binding.app_server_version.as_str(),
        binding.codex_home_digest.to_string(),
        binding.connection_id,
    ))?;
    Ok(FinalUseBinding {
        subject_id: agent_id.to_string(),
        destination_id: format!("codex-app-server:{}", binding.connection_id),
        request_sha256: codex_request_digest(intent).into_array(),
        scope_sha256: Digest32::of_bytes(&scope).into_array(),
        payload_sha256: intent.payload_digest.into_array(),
    })
}

fn remaining_before(deadline_ms: u64) -> Result<Duration> {
    let now_ms = unix_time_ms()?;
    if now_ms >= deadline_ms {
        return Err("runtime.codex request deadline elapsed before effect entry".into());
    }
    Ok(Duration::from_millis(deadline_ms - now_ms))
}

fn observation_budget_from(now_ms: u64, deadline_ms: u64) -> Duration {
    Duration::from_millis(deadline_ms.saturating_sub(now_ms))
}

fn validate_post_authority_fence(
    health: &HealthSnapshot,
    expected_ingress: &std::path::Path,
    current_ingress: &std::path::Path,
    cancelled: bool,
    now_ms: u64,
    deadline_ms: u64,
) -> Result<()> {
    if !health.ready || health.fenced {
        return Err("Agent owner is not ready at final-use entry".into());
    }
    if expected_ingress != current_ingress {
        return Err("Agent App Server ingress changed before final-use entry".into());
    }
    if cancelled {
        return Err("cancelled before final-use entry".into());
    }
    if now_ms >= deadline_ms {
        return Err("runtime.codex deadline elapsed before final-use entry".into());
    }
    Ok(())
}

async fn send_authorized_turn_start(
    client: &mut RemoteAppServerClient,
    _entered: EnteredUseToken,
    params: TurnStartParams,
) -> std::result::Result<TurnStartResponse, RemoteObservedTypedRequestError> {
    client
        .request_typed_observed(ClientRequest::TurnStart {
            request_id: RequestId::Integer(2),
            params,
        })
        .await
}

fn verify_persisted_dispatch_binding(
    control: &DurableInferenceControl,
    request_id: &str,
    payload_digest: Digest32,
    request_digest: Digest32,
    source_admission_digest: Digest32,
    codex_home_digest: Digest32,
    connection_id: u64,
    session_id: &str,
    deadline_ms: u64,
    authority_witness: &str,
    app_server_version: &str,
) -> Result<()> {
    let dispatch = control
        .native_record(request_id)
        .and_then(|record| record.dispatch.as_ref())
        .ok_or("runtime.codex dispatch binding was not durably published")?;
    let payload_digest = payload_digest.to_string();
    let request_digest = request_digest.to_string();
    let source_admission_digest = source_admission_digest.to_string();
    let codex_home_digest = codex_home_digest.to_string();
    let exact = dispatch.codex_payload_digest.as_deref() == Some(payload_digest.as_str())
        && dispatch.codex_request_digest.as_deref() == Some(request_digest.as_str())
        && dispatch.codex_source_admission_digest.as_deref()
            == Some(source_admission_digest.as_str())
        && dispatch.codex_home_digest.as_deref() == Some(codex_home_digest.as_str())
        && dispatch.codex_connection_id == Some(connection_id)
        && dispatch.codex_session_id.as_deref() == Some(session_id)
        && dispatch.codex_deadline_ms == Some(deadline_ms)
        && dispatch.codex_authority_witness_sha256.as_deref() == Some(authority_witness)
        && dispatch.app_server_version.as_deref() == Some(app_server_version)
        && dispatch.protocol_id.as_deref() == Some(APP_SERVER_V2_PROTOCOL_ID);
    if !exact {
        return Err("durable runtime.codex dispatch binding changed before physical send".into());
    }
    Ok(())
}

fn unix_time_ms() -> Result<u64> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system clock is before the Unix epoch")?;
    u64::try_from(elapsed.as_millis()).map_err(|_| "system clock milliseconds overflow".into())
}

fn indeterminate_start_output(started: ThreadStartResponse, reason: String) -> NativeRunOutput {
    NativeRunOutput {
        thread_id: started.thread.id,
        turn_id: String::new(),
        model: started.model,
        model_provider: started.model_provider,
        status: NativeRunStatus::Indeterminate,
        boundary_status: NativeBoundaryStatus::Indeterminate,
        output: String::new(),
        observed_output_tokens: None,
        terminal_observed: false,
        owner_authority: NativeOwnerAuthority::Unverified,
        stop_reason: Some(reason.chars().take(1024).collect()),
        codex_terminal_correlation_digest: None,
    }
}

/// A lost turn/start response is not replayed. On the same exact App Server
/// connection, the worker may recover only from the authoritative
/// turn/started notification for this fresh per-request thread.
async fn reconcile_turn_start(
    client: &mut RemoteAppServerClient,
    thread_id: &str,
) -> Result<Option<codex_app_server_protocol::Turn>> {
    let deadline = Instant::now() + TURN_START_RECONCILE_GRACE;
    loop {
        let event = match timeout_at(deadline, client.next_observed_event()).await {
            Ok(Some(event)) => event,
            Ok(None) | Err(_) => return Ok(None),
        };
        match event.event() {
            AppServerEvent::ServerNotification(_) => {
                if let Some(turn) = exact_reconciled_turn(thread_id, &event)? {
                    return Ok(Some(turn));
                }
            }
            AppServerEvent::ServerRequest(request) => {
                timeout_at(
                    deadline,
                    client.reject_server_request(
                        request.id().clone(),
                        JSONRPCErrorError {
                            code: -32000,
                            message: "native inference worker does not grant approvals".to_string(),
                            data: None,
                        },
                    ),
                )
                .await
                .map_err(|_| "approval rejection timed out during turn/start reconciliation")??;
            }
            AppServerEvent::Lagged { .. } | AppServerEvent::Disconnected { .. } => {
                return Ok(None);
            }
        }
    }
}

fn exact_reconciled_turn(
    thread_id: &str,
    observed: &RemoteAppServerObservedEvent,
) -> std::result::Result<Option<codex_app_server_protocol::Turn>, String> {
    let AppServerEvent::ServerNotification(notification) = observed.event() else {
        return Ok(None);
    };
    match notification.as_ref() {
        ServerNotification::TurnStarted(started) if started.thread_id == thread_id => {
            if started.turn.status != TurnStatus::InProgress {
                return Err("turn/started carried a non-in-progress status".to_string());
            }
            Ok(Some(started.turn.clone()))
        }
        _ => Ok(None),
    }
}

async fn verify_owner_health(
    output: &mut NativeRunOutput,
    health: impl Future<Output = std::result::Result<HealthSnapshot, AgentdError>>,
    deadline: Instant,
) -> std::result::Result<(), String> {
    if let NativeOwnerAuthority::Lost { reason } = &output.owner_authority {
        return Err(reason.clone());
    }
    let checked = timeout_at(deadline.min(Instant::now() + RPC_TIMEOUT), health).await;
    let failure = match checked {
        Ok(Ok(health)) if health.ready && !health.fenced => {
            output.owner_authority = NativeOwnerAuthority::ObservedReady;
            return Ok(());
        }
        Ok(Ok(_)) => "owning Agent is no longer ready or is fenced".to_string(),
        Ok(Err(error)) => format!("owner health check failed: {error}"),
        Err(_) => "owner health check timed out".to_string(),
    };
    let reason: String = failure.chars().take(1024).collect();
    output.owner_authority = NativeOwnerAuthority::Lost {
        reason: reason.clone(),
    };
    downgrade_for_owner_loss(output);
    Err(reason)
}

fn downgrade_for_owner_loss(output: &mut NativeRunOutput) {
    if matches!(output.owner_authority, NativeOwnerAuthority::Lost { .. }) {
        output.boundary_status = NativeBoundaryStatus::Quarantined;
    }
}

async fn interrupt(client: &mut RemoteAppServerClient, output: &NativeRunOutput) {
    // An interrupt acknowledgement is not a terminal model outcome.
    let _ = timeout(
        RPC_TIMEOUT,
        client.request(ClientRequest::TurnInterrupt {
            request_id: RequestId::Integer(3),
            params: TurnInterruptParams {
                thread_id: output.thread_id.clone(),
                turn_id: output.turn_id.clone(),
            },
        }),
    )
    .await;
}

fn observe_event(
    output: &mut NativeRunOutput,
    observed: &RemoteAppServerObservedEvent,
    binding: &CodexTurnBinding,
) -> std::result::Result<bool, String> {
    let AppServerEvent::ServerNotification(notification) = observed.event() else {
        return Ok(false);
    };
    match notification.as_ref() {
        ServerNotification::AgentMessageDelta(delta)
            if delta.thread_id == output.thread_id && delta.turn_id == output.turn_id =>
        {
            if delta.delta.len() > MAX_OUTPUT_BYTES.saturating_sub(output.output.len()) {
                return Err("output byte limit exceeded".to_string());
            }
            output.output.push_str(&delta.delta);
        }
        ServerNotification::ThreadTokenUsageUpdated(usage)
            if usage.thread_id == output.thread_id && usage.turn_id == output.turn_id =>
        {
            let observed_tokens = u64::try_from(usage.token_usage.total.output_tokens)
                .map_err(|_| "invalid negative provider usage".to_string())?;
            if output
                .observed_output_tokens
                .is_some_and(|previous| observed_tokens < previous)
            {
                return Err("provider cumulative usage regressed".to_string());
            }
            output.observed_output_tokens = Some(observed_tokens);
        }
        ServerNotification::TurnCompleted(completed)
            if completed.thread_id == output.thread_id && completed.turn.id == output.turn_id =>
        {
            let receipt = adapt_observed_event(&binding.intent, &binding.turn_id, observed)
                .map_err(|error| format!("invalid App Server terminal witness: {error}"))?
                .ok_or_else(|| "turn/completed did not produce terminal receipt".to_string())?;
            let physical_boundary = match receipt.status {
                AdapterStatus::Succeeded => {
                    output.status = NativeRunStatus::Completed;
                    NativeBoundaryStatus::Succeeded
                }
                AdapterStatus::Failed => {
                    output.status = NativeRunStatus::Failed;
                    NativeBoundaryStatus::Failed
                }
                AdapterStatus::Interrupted => {
                    output.status = NativeRunStatus::Interrupted;
                    NativeBoundaryStatus::Interrupted
                }
                _ => return Err("nonterminal adapter status for turn/completed".to_string()),
            };
            if output.boundary_status == NativeBoundaryStatus::Indeterminate {
                output.boundary_status = physical_boundary;
            }
            output.codex_terminal_correlation_digest = Some(
                receipt
                    .correlation_digest
                    .ok_or_else(|| "terminal receipt omitted correlation digest".to_string())?
                    .to_string(),
            );
            if let Some(error) = &completed.turn.error {
                output.stop_reason = Some(error.message.chars().take(1024).collect());
            }
            output.terminal_observed = true;
            downgrade_for_owner_loss(output);
            return Ok(true);
        }
        _ => {}
    }
    Ok(false)
}

#[cfg(test)]
#[path = "native_app_server_tests.rs"]
mod tests;
