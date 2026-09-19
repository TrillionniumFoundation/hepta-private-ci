//! Hosted model execution through the existing exact-generation Agent/App Server.
//!
//! This profile observes real turn events and token usage. It makes no claim
//! about local weights, accelerator memory, artifact selection or training.

use std::collections::HashMap;
use std::future::Future;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

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
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::ThreadUnsubscribeParams;
use codex_app_server_protocol::TurnInterruptParams;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdContextAttachment;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdRunPhase;
use codex_hepta_agentd::AgentdRunReceipt;
use codex_hepta_agentd::AgentdRunSnapshot;
use codex_hepta_agentd::HealthSnapshot;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
pub use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
pub use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
pub use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
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

/// A real provider client. Each new request uses a fresh ephemeral thread
/// behind the exact Agent identity. The control journal owns dispatch identity,
/// local slot admission and settlement; duplicate requests never start a turn.
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
        let context = match context_query.as_ref() {
            Some(query) => Some(owner.cognitive_context(query.clone(), /*limit*/ 4).await?),
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
        let context_bytes = serde_json::to_vec(&additional_context)?;
        let context_digest = control::digest(&context_bytes);
        let compilation_receipt_digest = control::digest(&serde_json::to_vec(&(
            "hepta.agentd-context-attachment.v1",
            &context_digest,
            &additional_context,
        ))?);

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

        // Recheck the owner immediately before lifecycle admission. The
        // response current_generation is the authority epoch carried by the
        // run snapshot; spawn_generation alone is only the process identity.
        owner.session_ingress().await?;
        let (latest_health, authority_epoch) = owner.health_with_generation().await?;
        if !latest_health.ready || latest_health.fenced {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("Agent is no longer ready before model dispatch".into());
        }
        if cancellation.is_cancelled() {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("cancelled before lifecycle admission".into());
        }

        let deadline = Instant::now() + self.config.timeout;
        let deadline_ms = deadline_unix_ms(self.config.timeout)?;
        let request_digest = control::digest(&serde_json::to_vec(&(
            "hepta.agentd-run-request.v1",
            request_id,
            &self.config.agent_id,
            self.config.generation,
        ))?);
        let objective_digest = control::digest(&serde_json::to_vec(&(
            "hepta.agentd-run-objective.v1",
            &self.config.model,
        ))?);
        let body_digest = control::digest(&serde_json::to_vec(&(
            "hepta.agentd-run-body.v1",
            &prompt,
            &context_query,
        ))?);
        let artifact_set_digest = control::digest(&serde_json::to_vec(&(
            "hepta.agentd-run-artifacts.v1",
            &started.model,
            &started.model_provider,
        ))?);
        let run_snapshot = AgentdRunSnapshot {
            run_id: request_id.to_string(),
            request_digest: request_digest.clone(),
            objective_digest: objective_digest.clone(),
            body_digest: body_digest.clone(),
            artifact_set_digest: artifact_set_digest.clone(),
            authority_epoch,
            deadline_ms,
        };
        let lifecycle_started = owner.run_start(run_snapshot).await?;
        let lifecycle_attached = match owner
            .run_attach_context(
                lifecycle_started.revision,
                AgentdContextAttachment {
                    run_id: request_id.to_string(),
                    request_digest,
                    objective_digest,
                    body_digest,
                    artifact_set_digest,
                    authority_epoch,
                    deadline_ms,
                    context_digest: context_digest.clone(),
                    compilation_receipt_digest,
                },
            )
            .await
        {
            Ok(receipt) => receipt,
            Err(error) => {
                let _ = owner
                    .run_cancel(
                        request_id.to_string(),
                        lifecycle_started.revision,
                        "context_attachment_rejected".to_string(),
                    )
                    .await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(error.into());
            }
        };
        let mut lifecycle_revision = lifecycle_attached.revision;

        if cancellation.is_cancelled() {
            let _ = owner
                .run_cancel(
                    request_id.to_string(),
                    lifecycle_revision,
                    "cancelled_before_model_dispatch".to_string(),
                )
                .await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("cancelled before model dispatch".into());
        }

        if let Err(error) = control.dispatch_native(
            request_id,
            NativeDispatch {
                thread_id: started.thread.id.clone(),
                model_provider: started.model_provider.clone(),
                context_digest,
            },
        ) {
            let _ = owner
                .run_cancel(
                    request_id.to_string(),
                    lifecycle_revision,
                    "inference_dispatch_journal_failed".to_string(),
                )
                .await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(error.into());
        }

        let lifecycle_dispatched = match owner
            .run_mark_dispatched(request_id.to_string(), lifecycle_revision)
            .await
        {
            Ok(receipt) => receipt,
            Err(error) => {
                let _ = owner
                    .run_cancel(
                        request_id.to_string(),
                        lifecycle_revision,
                        "lifecycle_dispatch_boundary_rejected".to_string(),
                    )
                    .await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(error.into());
            }
        };
        lifecycle_revision = lifecycle_dispatched.revision;

        let response = timeout(
            RPC_TIMEOUT,
            client.request_typed::<TurnStartResponse>(ClientRequest::TurnStart {
                request_id: RequestId::Integer(2),
                params: TurnStartParams {
                    thread_id: started.thread.id.clone(),
                    client_user_message_id: Some(request_id.to_string()),
                    input: vec![UserInput::Text {
                        text: prompt,
                        text_elements: Vec::new(),
                    }],
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
                let _ = reconcile_lifecycle_observation(
                    &owner,
                    request_id,
                    lifecycle_revision,
                    None,
                )
                .await;
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
            lifecycle_revision = prepare_lifecycle_cancel(
                &owner,
                request_id,
                lifecycle_revision,
                "native_started_journal_failure",
            )
            .await;
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
            let _ = reconcile_lifecycle_observation(
                &owner,
                request_id,
                lifecycle_revision,
                Some(&output),
            )
            .await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(error.into());
        }

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
            output.stop_reason = Some(reason.clone());
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
            lifecycle_revision =
                prepare_lifecycle_cancel(&owner, request_id, lifecycle_revision, &reason).await;
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

        let _ = reconcile_lifecycle_observation(
            &owner,
            request_id,
            lifecycle_revision,
            Some(&output),
        )
        .await;

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

fn deadline_unix_ms(timeout: Duration) -> Result<u64> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?;
    let deadline = now
        .checked_add(timeout)
        .ok_or("native lifecycle deadline overflow")?;
    u64::try_from(deadline.as_millis())
        .map_err(|_| "native lifecycle deadline exceeds u64 milliseconds".into())
}

fn bounded_lifecycle_reason(reason: &str) -> String {
    let value: String = reason.chars().take(128).collect();
    if value.trim().is_empty() {
        "native_worker_cancel".to_string()
    } else {
        value
    }
}

async fn prepare_lifecycle_cancel(
    owner: &AgentdClient,
    run_id: &str,
    fallback_revision: u64,
    reason: &str,
) -> u64 {
    let current = owner.run_get(run_id.to_string()).await.ok().flatten();
    let Some(current) = current else {
        return fallback_revision;
    };
    match current.phase {
        AgentdRunPhase::Admitted
        | AgentdRunPhase::ContextAttached
        | AgentdRunPhase::Dispatched => owner
            .run_cancel(
                run_id.to_string(),
                current.revision,
                bounded_lifecycle_reason(reason),
            )
            .await
            .map(|(_disposition, receipt)| receipt.revision)
            .unwrap_or(current.revision),
        AgentdRunPhase::Cancelling
        | AgentdRunPhase::Cancelled
        | AgentdRunPhase::Succeeded
        | AgentdRunPhase::Failed
        | AgentdRunPhase::Indeterminate => current.revision,
    }
}

async fn reconcile_lifecycle_observation(
    owner: &AgentdClient,
    run_id: &str,
    _fallback_revision: u64,
    output: Option<&NativeRunOutput>,
) -> std::result::Result<AgentdRunReceipt, AgentdError> {
    let current = owner
        .run_get(run_id.to_string())
        .await?
        .ok_or_else(|| AgentdError::Protocol("Agentd lifecycle run disappeared".to_string()))?;
    if matches!(
        current.phase,
        AgentdRunPhase::Cancelled | AgentdRunPhase::Succeeded | AgentdRunPhase::Failed
    ) {
        return Ok(current);
    }
    let revision = current.revision;
    match output {
        Some(output) if output.terminal_observed => {
            let phase = lifecycle_phase_for_output(output.status);
            owner
                .run_observe_terminal(run_id.to_string(), revision, phase, true)
                .await
        }
        _ => {
            owner
                .run_observe_terminal(
                    run_id.to_string(),
                    revision,
                    AgentdRunPhase::Indeterminate,
                    false,
                )
                .await
        }
    }
}

fn lifecycle_phase_for_output(status: NativeRunStatus) -> AgentdRunPhase {
    match status {
        NativeRunStatus::Completed => AgentdRunPhase::Succeeded,
        NativeRunStatus::Failed => AgentdRunPhase::Failed,
        NativeRunStatus::Interrupted => AgentdRunPhase::Cancelled,
        NativeRunStatus::Indeterminate => AgentdRunPhase::Indeterminate,
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
