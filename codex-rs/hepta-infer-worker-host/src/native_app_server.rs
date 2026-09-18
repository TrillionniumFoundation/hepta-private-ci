//! Hosted model execution through the existing exact-generation Agent/App Server.
//!
//! This profile observes real turn events and token usage. It makes no claim
//! about local weights, accelerator memory, artifact selection or training.

use std::collections::HashMap;
use std::future::Future;
use std::path::PathBuf;
use std::time::Duration;

use codex_app_server_client::AppServerEvent;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_protocol::AdditionalContextEntry;
use codex_app_server_protocol::AdditionalContextKind;
use codex_app_server_protocol::AskForApproval;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::SandboxMode;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileOutcome;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_app_server_protocol::ThreadQueueReconcileResponse;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
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
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
pub use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
pub use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
pub use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_protocol::user_input::user_input_payload_sha256;
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

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

/// Local operator-selected connection, fenced by the existing Agent identity.
pub struct NativeWorkerConfig {
    pub agentd_socket: PathBuf,
    pub agent_id: AgentId,
    pub generation: u64,
    pub model: String,
    pub timeout: Duration,
}

/// A real provider client. Each new request uses a fresh persistent, single-use
/// thread behind the exact Agent identity. Persistence is intentional: the
/// stable client message identity can be reconciled after worker/App Server
/// transport loss without submitting a replacement turn. The control journal
/// owns dispatch identity, local slot admission and settlement.
pub struct AppServerModelDriver {
    config: NativeWorkerConfig,
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
        Ok(Self { config })
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
        let socket_path = AbsolutePathBuf::from_absolute_path(ingress.socket_path)?;
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
        if client.codex_home() != health.home_root.to_str() {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("App Server home does not match the owning Agent".into());
        }
        let started: ThreadStartResponse = timeout(
            RPC_TIMEOUT,
            client.request_typed(ClientRequest::ThreadStart {
                request_id: RequestId::Integer(1),
                params: ThreadStartParams {
                    model: Some(self.config.model.clone()),
                    cwd: health.workspace.to_str().map(str::to_string),
                    approval_policy: Some(AskForApproval::Never),
                    sandbox: Some(SandboxMode::ReadOnly),
                    ephemeral: Some(false),
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
        let input = vec![UserInput::Text {
            text: prompt,
            text_elements: Vec::new(),
        }];
        let input_payload_sha256 = canonical_input_digest(&input)?;
        control.dispatch_native(
            request_id,
            NativeDispatch {
                thread_id: started.thread.id.clone(),
                model_provider: started.model_provider.clone(),
                context_digest: control::digest(&serde_json::to_vec(&additional_context)?),
                client_user_message_id: Some(request_id.to_string()),
                input_payload_sha256: Some(input_payload_sha256),
            },
        )?;
        let response = timeout(
            RPC_TIMEOUT,
            client.request_typed::<TurnStartResponse>(ClientRequest::TurnStart {
                request_id: RequestId::Integer(2),
                params: TurnStartParams {
                    thread_id: started.thread.id.clone(),
                    client_user_message_id: Some(request_id.to_string()),
                    input,
                    additional_context,
                    environments: Some(Vec::new()),
                    ..Default::default()
                },
            }),
        )
        .await;
        let turn = match response {
            Ok(Ok(response)) => response.turn,
            _ => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(NativeRunOutput {
                    thread_id: started.thread.id,
                    turn_id: String::new(),
                    model: started.model,
                    model_provider: started.model_provider,
                    status: NativeRunStatus::Indeterminate,
                    output: String::new(),
                    observed_output_tokens: None,
                    terminal_observed: false,
                    owner_authority: NativeOwnerAuthority::Unverified,
                    stop_reason: Some("turn/start outcome unknown; do not replay".to_string()),
                });
            }
        };
        let mut output = NativeRunOutput {
            thread_id: started.thread.id,
            turn_id: turn.id,
            model: started.model,
            model_provider: started.model_provider,
            status: NativeRunStatus::Indeterminate,
            output: String::new(),
            observed_output_tokens: None,
            terminal_observed: false,
            owner_authority: NativeOwnerAuthority::Unverified,
            stop_reason: None,
        };
        if let Err(error) = control.native_started(request_id, output.turn_id.clone()) {
            interrupt(&mut client, &output).await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(error.into());
        }
        let deadline = Instant::now() + self.config.timeout;
        let result = self
            .observe(
                &mut client,
                &mut output,
                deadline,
                cancellation,
                Some(&owner),
            )
            .await;
        if let Err(reason) = result {
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
        }
        Ok(output)
    }

    /// Reconcile a previously synced dispatch intent against Core's exact
    /// client-message identity. This never creates a queue row or a new turn.
    /// A missing/cancelled binding is therefore proof that no durable model
    /// admission exists for this request; a persisted binding yields the exact
    /// original turn identity and stored terminal output when available.
    pub(super) async fn reconcile_once(
        &self,
        control: &mut DurableInferenceControl,
        request_id: &str,
        prompt: &str,
        cancellation: &CancellationToken,
    ) -> Result<Option<NativeRunOutput>> {
        let record = control
            .native_record(request_id)
            .cloned()
            .ok_or("missing native reconciliation record")?;
        let dispatch = record
            .dispatch
            .clone()
            .ok_or("missing durable dispatch binding")?;
        let client_id = dispatch
            .client_user_message_id
            .clone()
            .ok_or("legacy dispatch has no exact client-message reconciliation binding")?;
        if client_id != request_id {
            return Err("durable client-message identity drifted from request".into());
        }
        let input = vec![UserInput::Text {
            text: prompt.to_string(),
            text_elements: Vec::new(),
        }];
        let input_payload_sha256 = canonical_input_digest(&input)?;
        if dispatch.input_payload_sha256.as_deref() != Some(input_payload_sha256.as_str()) {
            return Err("durable Core input digest does not match retry payload".into());
        }

        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let health = owner.health().await?;
        if !health.ready || health.fenced {
            return Err("Agent is not ready for provider reconciliation".into());
        }
        let ingress = owner.session_ingress().await?;
        let socket_path = AbsolutePathBuf::from_absolute_path(ingress.socket_path)?;
        let mut client = timeout(
            RPC_TIMEOUT,
            RemoteAppServerClient::connect_with_bounded_events(
                RemoteAppServerConnectArgs {
                    endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
                    client_name: "hepta-infer-worker-reconcile".to_string(),
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
        if client.codex_home() != health.home_root.to_str() {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("App Server home does not match the owning Agent".into());
        }

        let _: ThreadResumeResponse = timeout(
            RPC_TIMEOUT,
            client.request_typed(ClientRequest::ThreadResume {
                request_id: RequestId::Integer(101),
                params: ThreadResumeParams {
                    thread_id: dispatch.thread_id.clone(),
                    exclude_turns: true,
                    ..Default::default()
                },
            }),
        )
        .await??;

        let reconciled: ThreadQueueReconcileResponse = timeout(
            RPC_TIMEOUT,
            client.request_typed(ClientRequest::ThreadQueueReconcile {
                request_id: RequestId::Integer(102),
                params: ThreadQueueReconcileParams {
                    thread_id: dispatch.thread_id.clone(),
                    input,
                    client_user_message_id: client_id.clone(),
                    expected_payload_sha256: input_payload_sha256.clone(),
                    mode: ThreadQueueReconcileMode::ReconcileOnly,
                },
            }),
        )
        .await??;
        if reconciled.client_user_message_id != client_id
            || reconciled.payload_sha256 != input_payload_sha256
        {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("Core reconciliation returned a mismatched admission identity".into());
        }

        let turn_id = match reconciled.outcome {
            ThreadQueueReconcileOutcome::Persisted { turn_id } if !turn_id.is_empty() => turn_id,
            ThreadQueueReconcileOutcome::Missing | ThreadQueueReconcileOutcome::Cancelled => {
                let reason =
                    "Core exact client-message reconciliation proved no durable admission"
                        .to_string();
                control.reconcile_native_no_admission(request_id, reason)?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(None);
            }
            ThreadQueueReconcileOutcome::Persisted { .. } => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err("Core reconciliation returned an empty turn identity".into());
            }
            ThreadQueueReconcileOutcome::Queued { .. } => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(
                    "Core reconciliation found a queued identity for a direct inference turn".into(),
                );
            }
        };
        control.native_started(request_id, turn_id.clone())?;

        let read: ThreadReadResponse = timeout(
            RPC_TIMEOUT,
            client.request_typed(ClientRequest::ThreadRead {
                request_id: RequestId::Integer(103),
                params: ThreadReadParams {
                    thread_id: dispatch.thread_id.clone(),
                    include_turns: true,
                },
            }),
        )
        .await??;
        let persisted_turn = read.thread.turns.iter().find(|turn| turn.id == turn_id);

        let mut output = record.observation.unwrap_or(NativeRunOutput {
            thread_id: dispatch.thread_id.clone(),
            turn_id: turn_id.clone(),
            model: record.request.model.clone(),
            model_provider: dispatch.model_provider.clone(),
            status: NativeRunStatus::Indeterminate,
            output: String::new(),
            observed_output_tokens: None,
            terminal_observed: false,
            owner_authority: NativeOwnerAuthority::Unverified,
            stop_reason: None,
        });
        if output.thread_id != dispatch.thread_id
            || output.model != record.request.model
            || output.model_provider != dispatch.model_provider
            || (!output.turn_id.is_empty() && output.turn_id != turn_id)
        {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("stored provider observation does not match reconciled assignment".into());
        }
        output.turn_id = turn_id.clone();

        if let Some(turn) = persisted_turn {
            match turn.status {
                TurnStatus::Completed | TurnStatus::Failed | TurnStatus::Interrupted => {
                    output.status = match turn.status {
                        TurnStatus::Completed => NativeRunStatus::Completed,
                        TurnStatus::Failed => NativeRunStatus::Failed,
                        TurnStatus::Interrupted => NativeRunStatus::Interrupted,
                        TurnStatus::InProgress => unreachable!(),
                    };
                    if let Some(text) = turn.items.iter().rev().find_map(|item| match item {
                        ThreadItem::AgentMessage { text, .. } if !text.is_empty() => {
                            Some(text.clone())
                        }
                        _ => None,
                    }) {
                        if text.len() > MAX_OUTPUT_BYTES {
                            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                            return Err("reconciled output byte limit exceeded".into());
                        }
                        output.output = text;
                    }
                    output.stop_reason = turn
                        .error
                        .as_ref()
                        .map(|error| error.message.chars().take(1024).collect());
                    output.terminal_observed = true;

                    // thread/resume replays the current token usage snapshot.
                    // Drain a short bounded window so a terminal recovered run
                    // can refine missing usage without making usage mandatory.
                    let replay_cancel = CancellationToken::new();
                    let _ = self
                        .observe(
                            &mut client,
                            &mut output,
                            Instant::now() + Duration::from_millis(250),
                            &replay_cancel,
                            /*owner*/ None,
                        )
                        .await;
                }
                TurnStatus::InProgress => {
                    output.status = NativeRunStatus::Indeterminate;
                    output.terminal_observed = false;
                    output.stop_reason =
                        Some("Core admission reconciled; original turn is still in progress".into());
                }
            }
        } else {
            output.status = NativeRunStatus::Indeterminate;
            output.terminal_observed = false;
            output.stop_reason =
                Some("Core admission reconciled; persisted turn history is not yet visible".into());
        }

        if !matches!(output.owner_authority, NativeOwnerAuthority::Lost { .. }) {
            let _ = verify_owner_health(
                &mut output,
                owner.health(),
                Instant::now() + RPC_TIMEOUT,
            )
            .await;
        }
        if cancellation.is_cancelled() && !output.terminal_observed {
            control.cancel_native(request_id)?;
            interrupt(&mut client, &output).await;
        }
        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
        Ok(Some(output))
    }

    async fn observe(
        &self,
        client: &mut RemoteAppServerClient,
        output: &mut NativeRunOutput,
        deadline: Instant,
        cancellation: &CancellationToken,
        owner: Option<&AgentdClient>,
    ) -> std::result::Result<(), String> {
        let mut health_tick = tokio::time::interval(Duration::from_millis(500));
        loop {
            let event = tokio::select! {
                _ = cancellation.cancelled() => return Err("cancelled".to_string()),
                _ = health_tick.tick(), if owner.is_some() => {
                    if let Some(owner) = owner {
                        verify_owner_health(output, owner.health(), deadline).await?;
                    }
                    continue;
                },
                event = timeout_at(deadline, client.next_event()) => event
                    .map_err(|_| "deadline elapsed".to_string())?
                    .ok_or_else(|| "provider event stream ended".to_string())?,
            };
            match event {
                AppServerEvent::ServerNotification(notification) => {
                    if observe_notification(output, *notification)? {
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
                AppServerEvent::Disconnected { message } => return Err(message),
            }
        }
    }
}

fn canonical_input_digest(input: &[UserInput]) -> Result<String> {
    let core = input
        .iter()
        .cloned()
        .map(UserInput::into_core)
        .collect::<Vec<_>>();
    Ok(user_input_payload_sha256(&core)?)
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
    Err(reason)
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

fn observe_notification(
    output: &mut NativeRunOutput,
    notification: ServerNotification,
) -> std::result::Result<bool, String> {
    match notification {
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
            let observed = u64::try_from(usage.token_usage.total.output_tokens)
                .map_err(|_| "invalid negative provider usage".to_string())?;
            if output
                .observed_output_tokens
                .is_some_and(|previous| observed < previous)
            {
                return Err("provider cumulative usage regressed".to_string());
            }
            output.observed_output_tokens = Some(observed);
        }
        ServerNotification::TurnCompleted(completed)
            if completed.thread_id == output.thread_id && completed.turn.id == output.turn_id =>
        {
            output.status = match completed.turn.status {
                TurnStatus::Completed => NativeRunStatus::Completed,
                TurnStatus::Failed => NativeRunStatus::Failed,
                TurnStatus::Interrupted => NativeRunStatus::Interrupted,
                TurnStatus::InProgress => return Err("nonterminal completion event".to_string()),
            };
            if let Some(error) = completed.turn.error {
                // Bound the provider's diagnostic without discarding the
                // actually observed terminal status or token count.
                output.stop_reason = Some(error.message.chars().take(1024).collect());
            }
            output.terminal_observed = true;
            return Ok(true);
        }
        _ => {}
    }
    Ok(false)
}

#[cfg(test)]
#[path = "native_app_server_tests.rs"]
mod tests;
