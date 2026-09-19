//! Post-crash reconciliation for the durable App Server execution profile.
//!
//! A dispatched request is never replayed. Instead, the worker reconnects to
//! the exact owning Agent generation and reads the durable dedicated thread.
//! The persisted client-user-message id binds a turn to the original request
//! when the turn/start response was lost before its turn id could be journaled.

use std::time::Duration;

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnStatus;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio::time::Instant;
use tokio::time::sleep;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::AppServerModelDriver;
use super::MAX_OUTPUT_BYTES;
use super::NativeOwnerAuthority;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::RPC_TIMEOUT;
use super::Result;
use super::verify_owner_health;

const RECONCILE_POLL_INTERVAL: Duration = Duration::from_millis(500);

impl AppServerModelDriver {
    pub(super) async fn reconcile(
        &self,
        record: &NativeRunRecord,
        cancellation: &CancellationToken,
    ) -> Result<Option<NativeRunOutput>> {
        let dispatch = record
            .dispatch
            .as_ref()
            .ok_or("cannot reconcile without a durable dispatch binding")?;
        if cancellation.is_cancelled() {
            return Ok(None);
        }

        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let health = owner.health().await?;
        if !health.ready || health.fenced {
            return Err("owning Agent is not ready for reconciliation".into());
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
                    channel_capacity: 8,
                },
                /*event_channel_capacity*/ 32,
            ),
        )
        .await??;
        if client.codex_home() != health.home_root.to_str() {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("App Server home does not match the owning Agent".into());
        }
        // Recheck the exact owner generation after reconnecting.
        owner.session_ingress().await?;

        let deadline = Instant::now() + self.config.timeout;
        let mut rpc_id = 100_i64;
        loop {
            if cancellation.is_cancelled() {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(None);
            }
            if Instant::now() >= deadline {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(None);
            }

            let read = timeout(
                RPC_TIMEOUT,
                client.request_typed::<ThreadReadResponse>(ClientRequest::ThreadRead {
                    request_id: RequestId::Integer(rpc_id),
                    params: ThreadReadParams {
                        thread_id: dispatch.thread_id.clone(),
                        include_turns: true,
                    },
                }),
            )
            .await;
            rpc_id = rpc_id.saturating_add(1);
            let read = match read {
                Ok(Ok(read)) => read,
                Ok(Err(error)) => {
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Err(format!("thread/read reconciliation failed: {error}").into());
                }
                Err(_) => {
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Err("thread/read reconciliation timed out".into());
                }
            };

            if read.thread.id != dispatch.thread_id
                || read.thread.model_provider != dispatch.model_provider
            {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err("reconciliation returned a different thread/provider".into());
            }

            if let Some(turn) = select_turn(&read, record)? {
                if turn.status != TurnStatus::InProgress {
                    let mut output = terminal_output(record, turn)?;
                    // A prior observed authority loss is sticky: verify_owner_health
                    // refuses to upgrade it. Otherwise establish current exact-owner
                    // readiness before this recovered result can be successful.
                    let _ = verify_owner_health(
                        &mut output,
                        owner.health(),
                        Instant::now() + RPC_TIMEOUT,
                    )
                    .await;
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Ok(Some(output));
                }
            }

            sleep(RECONCILE_POLL_INTERVAL.min(deadline.saturating_duration_since(Instant::now())))
                .await;
        }
    }
}

fn select_turn<'a>(
    read: &'a ThreadReadResponse,
    record: &NativeRunRecord,
) -> Result<Option<&'a Turn>> {
    if let Some(turn_id) = record.turn_id.as_deref() {
        return Ok(read.thread.turns.iter().find(|turn| turn.id == turn_id));
    }

    // turn/start may have reached the App Server while its response was lost.
    // The thread is dedicated to exactly one inference request, and the stable
    // request id was sent as client_user_message_id. Use that persisted binding
    // instead of guessing from turn order.
    let mut matches = read.thread.turns.iter().filter(|turn| {
        turn.items.iter().any(|item| {
            matches!(
                item,
                ThreadItem::UserMessage {
                    client_id: Some(client_id),
                    ..
                } if client_id == &record.request.request_id
            )
        })
    });
    let first = matches.next();
    if matches.next().is_some() {
        return Err("multiple persisted turns match one inference request id".into());
    }
    Ok(first)
}

fn terminal_output(record: &NativeRunRecord, turn: &Turn) -> Result<NativeRunOutput> {
    let dispatch = record
        .dispatch
        .as_ref()
        .ok_or("missing durable dispatch during reconciliation")?;
    let status = match turn.status {
        TurnStatus::Completed => NativeRunStatus::Completed,
        TurnStatus::Failed => NativeRunStatus::Failed,
        TurnStatus::Interrupted => NativeRunStatus::Interrupted,
        TurnStatus::InProgress => return Err("cannot settle an in-progress turn".into()),
    };

    let mut output = String::new();
    for item in &turn.items {
        if let ThreadItem::AgentMessage { text, .. } = item {
            if text.len() > MAX_OUTPUT_BYTES.saturating_sub(output.len()) {
                return Err("persisted provider output exceeds worker bound".into());
            }
            output.push_str(text);
        }
    }

    let previous = record.observation.as_ref();
    let stop_reason = turn
        .error
        .as_ref()
        .map(|error| error.message.chars().take(1024).collect())
        .or_else(|| previous.and_then(|output| output.stop_reason.clone()));

    Ok(NativeRunOutput {
        thread_id: dispatch.thread_id.clone(),
        turn_id: turn.id.clone(),
        model: record.request.model.clone(),
        model_provider: dispatch.model_provider.clone(),
        status,
        output,
        // thread/read currently does not expose authoritative per-turn token
        // usage. Preserve an earlier matching observation when one exists, and
        // otherwise leave usage unknown rather than inventing zero.
        observed_output_tokens: previous.and_then(|output| output.observed_output_tokens),
        terminal_observed: true,
        owner_authority: previous
            .map(|output| output.owner_authority.clone())
            .unwrap_or(NativeOwnerAuthority::Unverified),
        stop_reason,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_app_server_protocol::Thread;
    use codex_app_server_protocol::ThreadHistoryMode;
    use codex_app_server_protocol::ThreadStatus;
    use codex_app_server_protocol::TurnItemsView;
    use codex_hepta_infer_core::durable_control::native::NativeDispatch;
    use codex_hepta_infer_core::durable_control::native::NativeRequest;
    use codex_hepta_infer_core::durable_control::native::NativeReservationState;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use codex_app_server_protocol::SessionSource;

    fn record(turn_id: Option<&str>) -> NativeRunRecord {
        NativeRunRecord {
            request: NativeRequest {
                request_id: "request-1".to_string(),
                principal_id: "principal-1".to_string(),
                worker_generation: 1,
                model: "model".to_string(),
                payload_digest: "a".repeat(64),
            },
            revision: 2,
            state: NativeReservationState::Dispatching,
            dispatch: Some(NativeDispatch {
                thread_id: "thread-1".to_string(),
                model_provider: "provider".to_string(),
                context_digest: "b".repeat(64),
            }),
            turn_id: turn_id.map(str::to_string),
            cancel_requested: false,
            pre_dispatch_stop: None,
            observation: None,
        }
    }

    fn turn(id: &str, client_id: Option<&str>, status: TurnStatus) -> Turn {
        Turn {
            id: id.to_string(),
            items: vec![ThreadItem::UserMessage {
                id: "item-user".to_string(),
                client_id: client_id.map(str::to_string),
                content: Vec::new(),
            }],
            items_view: TurnItemsView::Full,
            status,
            error: None,
            started_at: None,
            completed_at: None,
            duration_ms: None,
        }
    }

    fn response(turns: Vec<Turn>) -> ThreadReadResponse {
        ThreadReadResponse {
            thread: Thread {
                id: "thread-1".to_string(),
                extra: None,
                session_id: "session-1".to_string(),
                forked_from_id: None,
                parent_thread_id: None,
                preview: String::new(),
                ephemeral: false,
                section: None,
                section_entered_at: None,
                project_id: None,
                history_mode: ThreadHistoryMode::Legacy,
                model_provider: "provider".to_string(),
                created_at: 0,
                updated_at: 0,
                recency_at: None,
                status: ThreadStatus::Idle,
                path: None,
                cwd: AbsolutePathBuf::from_absolute_path(
                    std::env::temp_dir().canonicalize().expect("temp path"),
                )
                .expect("absolute cwd"),
                cli_version: "test".to_string(),
                source: SessionSource::AppServer,
                can_accept_direct_input: Some(true),
                thread_source: None,
                agent_nickname: None,
                agent_role: None,
                git_info: None,
                name: None,
                turns,
            },
        }
    }

    #[test]
    fn unknown_turn_id_reconciles_only_by_stable_client_request_id() {
        let read = response(vec![
            turn("turn-other", Some("other-request"), TurnStatus::Completed),
            turn("turn-1", Some("request-1"), TurnStatus::Completed),
        ]);
        assert_eq!(
            select_turn(&read, &record(None))
                .expect("selection")
                .expect("turn")
                .id,
            "turn-1"
        );
    }

    #[test]
    fn known_turn_id_uses_durable_turn_binding() {
        let read = response(vec![turn(
            "turn-1",
            Some("old-client-field"),
            TurnStatus::Failed,
        )]);
        assert_eq!(
            select_turn(&read, &record(Some("turn-1")))
                .expect("selection")
                .expect("turn")
                .status,
            TurnStatus::Failed
        );
    }
}
