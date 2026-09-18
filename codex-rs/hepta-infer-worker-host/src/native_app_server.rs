//! Hosted model execution through the existing exact-generation Agent/App Server.
//!
//! This profile observes real turn events and token usage. Hosted threads are
//! private but durable so a worker restart can reconcile the stable user-message
//! identity against App Server history instead of blindly replaying a provider
//! request. Local weights/device execution belongs to `local_process`.

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
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::ThreadTurnsListParams;
use codex_app_server_protocol::ThreadTurnsListResponse;
use codex_app_server_protocol::ThreadUnsubscribeParams;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnInterruptParams;
use codex_app_server_protocol::TurnItemsView;
use codex_app_server_protocol::TurnRecoverParams;
use codex_app_server_protocol::TurnRecoverResponse;
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
const USAGE_REPLAY_GRACE: Duration = Duration::from_millis(250);

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

/// Local operator-selected connection, fenced by the existing Agent identity.
pub struct NativeWorkerConfig {
    pub agentd_socket: PathBuf,
    pub agent_id: AgentId,
    pub generation: u64,
    pub model: String,
    pub timeout: Duration,
}

/// A real provider client. Each request uses a private durable App Server thread.
/// The journal commits thread identity before turn admission; reopen reconciles
/// the stable `client_user_message_id` and canonical input digest before any
/// recovery or retry is permitted.
pub struct AppServerModelDriver {
    pub(crate) config: NativeWorkerConfig,
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

    async fn owner(&self) -> Result<(AgentdClient, HealthSnapshot)> {
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let health = owner.health().await?;
        if !health.ready || health.fenced {
            return Err("Agent is not ready".into());
        }
        Ok((owner, health))
    }

    async fn connect(
        &self,
        owner: &AgentdClient,
        health: &HealthSnapshot,
    ) -> Result<RemoteAppServerClient> {
        let ingress = owner.session_ingress().await?;
        let socket_path = AbsolutePathBuf::from_absolute_path(ingress.socket_path)?;
        let client = timeout(
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
            return Err("App Server home does not match the owning Agent".into());
        }
        Ok(client)
    }

    async fn additional_context(
        &self,
        owner: &AgentdClient,
        context_query: Option<String>,
    ) -> Result<Option<HashMap<String, AdditionalContextEntry>>> {
        let Some(query) = context_query else {
            return Ok(None);
        };
        let snapshot = owner.cognitive_context(query, /*limit*/ 4).await?;
        let value = serde_json::to_string(&snapshot)?;
        if value.len() > MAX_MODEL_CONTEXT_BYTES {
            return Err("verified context exceeds the model attachment byte limit".into());
        }
        Ok(Some(HashMap::from([(
            "hepta-cognitive-owner".to_string(),
            AdditionalContextEntry {
                value,
                kind: AdditionalContextKind::Untrusted,
            },
        )])))
    }

    fn input(prompt: String) -> Vec<UserInput> {
        vec![UserInput::Text {
            text: prompt,
            text_elements: Vec::new(),
        }]
    }

    fn input_digest(input: &[UserInput]) -> Result<String> {
        let core = input
            .iter()
            .cloned()
            .map(UserInput::into_core)
            .collect::<Vec<_>>();
        Ok(user_input_payload_sha256(&core)?)
    }

    /// First dispatch. The thread is durable because recovery must have a
    /// provider-owned record to query after process loss. The thread remains
    /// read-only/no-approval and enables the App Server's guarded turn recovery.
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
        let (owner, health) = self.owner().await?;
        let additional_context = self.additional_context(&owner, context_query).await?;
        let mut client = self.connect(&owner, &health).await?;
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
                    config: Some(HashMap::from([(
                        "features.hepta_turn_recovery".to_string(),
                        serde_json::json!(true),
                    )])),
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
        control.dispatch_native(
            request_id,
            NativeDispatch {
                thread_id: started.thread.id.clone(),
                model_provider: started.model_provider.clone(),
                context_digest: control::digest(&serde_json::to_vec(&additional_context)?),
            },
        )?;
        let input = Self::input(prompt);
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
                    stop_reason: Some(
                        "turn/start response lost; reconcile stable provider identity before retry"
                            .to_string(),
                    ),
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
        self.observe_with_interrupts(
            control,
            request_id,
            &owner,
            &mut client,
            &mut output,
            cancellation,
        )
        .await?;
        Ok(output)
    }

    /// Reconcile a durable dispatch against App Server's persisted user-message
    /// identity. `Missing` is the only state that permits a same-thread retry,
    /// and only if the exact additional-context digest is unchanged. Persisted
    /// turns are read or recovered in place; they are never started as a new turn.
    async fn reconcile_once(
        &self,
        control: &mut DurableInferenceControl,
        request_id: &str,
        prompt: String,
        context_query: Option<String>,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        let record = control
            .native_record(request_id)
            .cloned()
            .ok_or("missing native record")?;
        let dispatch = record
            .dispatch
            .clone()
            .ok_or("missing durable dispatch binding")?;
        let (owner, health) = self.owner().await?;
        let mut client = self.connect(&owner, &health).await?;
        let resumed: ThreadResumeResponse = timeout(
            RPC_TIMEOUT,
            client.request_typed(ClientRequest::ThreadResume {
                request_id: RequestId::Integer(10),
                params: ThreadResumeParams {
                    thread_id: dispatch.thread_id.clone(),
                    ..Default::default()
                },
            }),
        )
        .await??;
        if resumed.model != record.request.model
            || resumed.model_provider != dispatch.model_provider
            || resumed.thread.id != dispatch.thread_id
        {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("reconciled App Server thread binding changed".into());
        }
        let input = Self::input(prompt.clone());
        let payload_sha256 = Self::input_digest(&input)?;
        let reconciled: ThreadQueueReconcileResponse = timeout(
            RPC_TIMEOUT,
            client.request_typed(ClientRequest::ThreadQueueReconcile {
                request_id: RequestId::Integer(11),
                params: ThreadQueueReconcileParams {
                    thread_id: dispatch.thread_id.clone(),
                    input: input.clone(),
                    client_user_message_id: request_id.to_string(),
                    expected_payload_sha256: payload_sha256,
                    mode: ThreadQueueReconcileMode::ReconcileOnly,
                },
            }),
        )
        .await??;
        match reconciled.outcome {
            ThreadQueueReconcileOutcome::Persisted { turn_id } => {
                if record
                    .turn_id
                    .as_deref()
                    .is_some_and(|known| known != turn_id.as_str())
                {
                    return Err("provider reconciliation returned a different turn id".into());
                }
                if record.turn_id.is_none() {
                    control.native_started(request_id, turn_id.clone())?;
                }
                let turn = self
                    .read_persisted_turn(&mut client, &dispatch.thread_id, &turn_id)
                    .await?;
                let mut output = persisted_output(&record, &dispatch, turn)?;
                if output.status == NativeRunStatus::Interrupted
                    && !record.cancel_requested
                    && !cancellation.is_cancelled()
                {
                    let recovery = timeout(
                        RPC_TIMEOUT,
                        client.request_typed::<TurnRecoverResponse>(ClientRequest::TurnRecover {
                            request_id: RequestId::Integer(12),
                            params: TurnRecoverParams {
                                thread_id: dispatch.thread_id.clone(),
                                turn_id: turn_id.clone(),
                            },
                        }),
                    )
                    .await;
                    if let Ok(Ok(recovered)) = recovery {
                        if recovered.turn.id != turn_id
                            || recovered.turn.status != TurnStatus::InProgress
                        {
                            return Err("turn/recover changed logical turn identity".into());
                        }
                        output.status = NativeRunStatus::Indeterminate;
                        output.terminal_observed = false;
                        output.output.clear();
                        output.stop_reason = None;
                        self.observe_with_interrupts(
                            control,
                            request_id,
                            &owner,
                            &mut client,
                            &mut output,
                            cancellation,
                        )
                        .await?;
                        return Ok(output);
                    }
                }
                if output.status == NativeRunStatus::Indeterminate {
                    self.observe_with_interrupts(
                        control,
                        request_id,
                        &owner,
                        &mut client,
                        &mut output,
                        cancellation,
                    )
                    .await?;
                    return Ok(output);
                }
                // A cold resume may replay persisted token-count events after the
                // response. Drain only a bounded grace window and never infer zero.
                self.drain_usage_replay(&mut client, &mut output).await;
                let _ =
                    verify_owner_health(&mut output, owner.health(), Instant::now() + RPC_TIMEOUT)
                        .await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                Ok(output)
            }
            ThreadQueueReconcileOutcome::Missing => {
                if record.turn_id.is_some() {
                    return Err("provider history lost a previously bound turn".into());
                }
                if cancellation.is_cancelled() || record.cancel_requested {
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Ok(indeterminate_from_record(
                        &record,
                        &dispatch,
                        "provider proved no persisted turn after cancellation",
                    ));
                }
                let additional_context = self.additional_context(&owner, context_query).await?;
                let context_digest = control::digest(&serde_json::to_vec(&additional_context)?);
                if context_digest != dispatch.context_digest {
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Ok(indeterminate_from_record(
                        &record,
                        &dispatch,
                        "provider proved no turn, but context snapshot drifted; retry denied",
                    ));
                }
                let response: TurnStartResponse = timeout(
                    RPC_TIMEOUT,
                    client.request_typed(ClientRequest::TurnStart {
                        request_id: RequestId::Integer(13),
                        params: TurnStartParams {
                            thread_id: dispatch.thread_id.clone(),
                            client_user_message_id: Some(request_id.to_string()),
                            input,
                            additional_context,
                            environments: Some(Vec::new()),
                            ..Default::default()
                        },
                    }),
                )
                .await??;
                if response.turn.id.is_empty() {
                    return Err("provider returned empty reconciled turn id".into());
                }
                control.native_started(request_id, response.turn.id.clone())?;
                let mut output = NativeRunOutput {
                    thread_id: dispatch.thread_id,
                    turn_id: response.turn.id,
                    model: record.request.model,
                    model_provider: dispatch.model_provider,
                    status: NativeRunStatus::Indeterminate,
                    output: String::new(),
                    observed_output_tokens: record
                        .observation
                        .as_ref()
                        .and_then(|value| value.observed_output_tokens),
                    terminal_observed: false,
                    stop_reason: None,
                    owner_authority: record
                        .observation
                        .as_ref()
                        .map(|value| value.owner_authority.clone())
                        .unwrap_or_default(),
                };
                self.observe_with_interrupts(
                    control,
                    request_id,
                    &owner,
                    &mut client,
                    &mut output,
                    cancellation,
                )
                .await?;
                Ok(output)
            }
            ThreadQueueReconcileOutcome::Queued { .. } => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                Ok(indeterminate_from_record(
                    &record,
                    &dispatch,
                    "stable provider identity is queued; no duplicate dispatch permitted",
                ))
            }
            ThreadQueueReconcileOutcome::Cancelled => {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                Ok(indeterminate_from_record(
                    &record,
                    &dispatch,
                    "stable provider identity was cancelled before persisted terminal evidence",
                ))
            }
        }
    }

    async fn read_persisted_turn(
        &self,
        client: &mut RemoteAppServerClient,
        thread_id: &str,
        turn_id: &str,
    ) -> Result<Turn> {
        let turns: ThreadTurnsListResponse = timeout(
            RPC_TIMEOUT,
            client.request_typed(ClientRequest::ThreadTurnsList {
                request_id: RequestId::Integer(14),
                params: ThreadTurnsListParams {
                    thread_id: thread_id.to_string(),
                    cursor: None,
                    limit: Some(100),
                    sort_direction: None,
                    items_view: Some(TurnItemsView::Full),
                },
            }),
        )
        .await??;
        turns
            .data
            .into_iter()
            .find(|turn| turn.id == turn_id)
            .ok_or_else(|| "reconciled turn missing from provider history".into())
    }

    async fn observe_with_interrupts(
        &self,
        control: &mut DurableInferenceControl,
        request_id: &str,
        owner: &AgentdClient,
        client: &mut RemoteAppServerClient,
        output: &mut NativeRunOutput,
        cancellation: &CancellationToken,
    ) -> Result<()> {
        let deadline = Instant::now() + self.config.timeout;
        let result = self
            .observe(
                control,
                request_id,
                client,
                output,
                deadline,
                cancellation,
                Some(owner),
            )
            .await;
        if let Err(reason) = result {
            output.stop_reason = Some(reason);
            let loss_recorded =
                if matches!(output.owner_authority, NativeOwnerAuthority::Lost { .. }) {
                    control
                        .settle_native(request_id, output.clone())
                        .map(|_| ())
                } else {
                    Ok(())
                };
            let cancel_recorded = control.cancel_native(request_id);
            interrupt(client, output).await;
            let grace = CancellationToken::new();
            let _ = self
                .observe(
                    control,
                    request_id,
                    client,
                    output,
                    Instant::now() + INTERRUPT_GRACE,
                    &grace,
                    /*owner*/ None,
                )
                .await;
            loss_recorded?;
            cancel_recorded?;
        }
        if output.terminal_observed && output.observed_output_tokens.is_none() {
            self.drain_usage_replay(client, output).await;
        }
        if output.terminal_observed {
            let _ = timeout(
                RPC_TIMEOUT,
                client.request(ClientRequest::ThreadUnsubscribe {
                    request_id: RequestId::Integer(15),
                    params: ThreadUnsubscribeParams {
                        thread_id: output.thread_id.clone(),
                    },
                }),
            )
            .await;
        }
        let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
        if output.terminal_observed {
            let _ = verify_owner_health(output, owner.health(), Instant::now() + RPC_TIMEOUT).await;
        }
        Ok(())
    }

    async fn observe(
        &self,
        control: &mut DurableInferenceControl,
        request_id: &str,
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
                    let previous_usage = output.observed_output_tokens;
                    if observe_notification(output, *notification)? {
                        return Ok(());
                    }
                    if output.observed_output_tokens != previous_usage {
                        control
                            .settle_native(request_id, output.clone())
                            .map_err(|error| format!("persist provider usage: {error}"))?;
                    }
                }
                AppServerEvent::ServerRequest(request) => {
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

    async fn drain_usage_replay(
        &self,
        client: &mut RemoteAppServerClient,
        output: &mut NativeRunOutput,
    ) {
        let deadline = Instant::now() + USAGE_REPLAY_GRACE;
        loop {
            let Ok(Some(event)) = timeout_at(deadline, client.next_event()).await else {
                return;
            };
            match event {
                AppServerEvent::ServerNotification(notification) => {
                    let _ = observe_notification(output, *notification);
                }
                AppServerEvent::ServerRequest(request) => {
                    let _ = client
                        .reject_server_request(
                            request.id().clone(),
                            JSONRPCErrorError {
                                code: -32000,
                                message: "native inference worker does not grant approvals"
                                    .to_string(),
                                data: None,
                            },
                        )
                        .await;
                }
                AppServerEvent::Lagged { .. } | AppServerEvent::Disconnected { .. } => return,
            }
            if output.observed_output_tokens.is_some() {
                return;
            }
        }
    }
}

fn indeterminate_from_record(
    record: &codex_hepta_infer_core::durable_control::native::NativeRunRecord,
    dispatch: &NativeDispatch,
    reason: &str,
) -> NativeRunOutput {
    NativeRunOutput {
        thread_id: dispatch.thread_id.clone(),
        turn_id: record.turn_id.clone().unwrap_or_default(),
        model: record.request.model.clone(),
        model_provider: dispatch.model_provider.clone(),
        status: NativeRunStatus::Indeterminate,
        output: record
            .observation
            .as_ref()
            .map(|value| value.output.clone())
            .unwrap_or_default(),
        observed_output_tokens: record
            .observation
            .as_ref()
            .and_then(|value| value.observed_output_tokens),
        terminal_observed: false,
        owner_authority: record
            .observation
            .as_ref()
            .map(|value| value.owner_authority.clone())
            .unwrap_or_default(),
        stop_reason: Some(reason.to_string()),
    }
}

fn persisted_output(
    record: &codex_hepta_infer_core::durable_control::native::NativeRunRecord,
    dispatch: &NativeDispatch,
    turn: Turn,
) -> Result<NativeRunOutput> {
    let mut text = String::new();
    for item in &turn.items {
        if let ThreadItem::AgentMessage { text: value, .. } = item {
            if value.len() > MAX_OUTPUT_BYTES.saturating_sub(text.len()) {
                return Err("persisted output byte limit exceeded".into());
            }
            text.push_str(value);
        }
    }
    let terminal_observed = turn.status != TurnStatus::InProgress;
    let status = match turn.status {
        TurnStatus::Completed => NativeRunStatus::Completed,
        TurnStatus::Failed => NativeRunStatus::Failed,
        TurnStatus::Interrupted => NativeRunStatus::Interrupted,
        TurnStatus::InProgress => NativeRunStatus::Indeterminate,
    };
    Ok(NativeRunOutput {
        thread_id: dispatch.thread_id.clone(),
        turn_id: turn.id,
        model: record.request.model.clone(),
        model_provider: dispatch.model_provider.clone(),
        status,
        output: text,
        observed_output_tokens: record
            .observation
            .as_ref()
            .and_then(|value| value.observed_output_tokens),
        terminal_observed,
        stop_reason: turn
            .error
            .map(|error| error.message.chars().take(1024).collect()),
        owner_authority: record
            .observation
            .as_ref()
            .map(|value| value.owner_authority.clone())
            .unwrap_or_default(),
    })
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
    if output.turn_id.is_empty() {
        return;
    }
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
