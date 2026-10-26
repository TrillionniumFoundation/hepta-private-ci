//! Original transport and pending-call resolution. The Core/App Server owner
//! retains the conversation and dynamic-tool callback; this task adds no log.
use codex_app_server_client::AppServerEvent;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::DynamicToolCallOutputContentItem;
use codex_app_server_protocol::DynamicToolCallParams;
use codex_app_server_protocol::DynamicToolCallResponse;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ServerRequest;
use codex_app_server_protocol::SortDirection;
use codex_app_server_protocol::ThreadItemsListParams;
use codex_app_server_protocol::ThreadItemsListResponse;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use serde::de::DeserializeOwned;
use tokio_util::sync::CancellationToken;

use super::*;

#[derive(Clone, Copy)]
enum OriginalItemSelection<'a> {
    Call(&'a str),
    FirstReplace,
    UserInput,
}

struct OriginalConnection {
    client: RemoteAppServerClient,
    route: AgentdTextSessionConfig,
    next_request: i64,
}

impl OriginalConnection {
    async fn connect(route: AgentdTextSessionConfig) -> Result<Self, AgentdError> {
        let control = crate::AgentdClient::new(
            route.control_socket.clone(),
            route.agent_id.clone(),
            route.spawn_generation,
        )?;
        let ingress = control.session_ingress().await?;
        let client = RemoteAppServerClient::connect_with_bounded_events(
            RemoteAppServerConnectArgs {
                endpoint: RemoteAppServerEndpoint::UnixSocket {
                    socket_path: ingress
                        .socket_path
                        .as_path()
                        .try_into()
                        .map_err(|_| invalid("original App Server path"))?,
                },
                client_name: "hepta-original-notes-thread-tools".into(),
                client_version: env!("CARGO_PKG_VERSION").into(),
                experimental_api: true,
                mcp_server_openai_form_elicitation: false,
                opt_out_notification_methods: vec![],
                channel_capacity: 8,
            },
            128,
        )
        .await?;
        if client.codex_home() != route.codex_home.to_str() {
            return Err(invalid(
                "original Notes tool connected to another Codex home",
            ));
        }
        let mut connection = Self {
            client,
            route,
            next_request: 1,
        };
        let thread_id = connection.route.thread_id.clone();
        let response: ThreadResumeResponse = connection
            .call(|request_id| ClientRequest::ThreadResume {
                request_id,
                params: ThreadResumeParams {
                    thread_id,
                    exclude_turns: true,
                    ..Default::default()
                },
            })
            .await?;
        if response.thread.id != connection.route.thread_id
            || response.thread.session_id != connection.route.app_server_session_id
            || response.thread.ephemeral
        {
            return Err(invalid(
                "original Notes tool resumed a different thread/session",
            ));
        }
        Ok(connection)
    }

    async fn call<T: DeserializeOwned>(
        &mut self,
        request: impl FnOnce(RequestId) -> ClientRequest,
    ) -> Result<T, AgentdError> {
        let id = self.next_request;
        self.next_request = id
            .checked_add(1)
            .ok_or_else(|| invalid("original tool request counter exhausted"))?;
        tokio::time::timeout(
            Duration::from_secs(5),
            self.client.request_typed(request(RequestId::Integer(id))),
        )
        .await
        .map_err(|_| invalid("original thread readback deadline elapsed"))?
        .map_err(|_| invalid("original thread readback failed"))
    }

    async fn verify(
        &mut self,
        params: &DynamicToolCallParams,
    ) -> Result<VerifiedNotesThreadCall, AgentdError> {
        VerifiedNotesThreadCall::validate_callback(&self.route, params)?;
        let item = self.original_item(&params.turn_id, &params.call_id).await?;
        VerifiedNotesThreadCall::from_original_item(&self.route, params, &item)
    }

    async fn original_item(
        &mut self,
        original_turn_id: &str,
        original_call_id: &str,
    ) -> Result<codex_app_server_protocol::ThreadItem, AgentdError> {
        self.find_original_item(
            original_turn_id,
            OriginalItemSelection::Call(original_call_id),
        )
        .await
    }

    async fn first_original_replace(
        &mut self,
        turn_id: &str,
    ) -> Result<VerifiedNotesThreadOperation, AgentdError> {
        let item = self
            .find_original_item(turn_id, OriginalItemSelection::FirstReplace)
            .await?;
        let codex_app_server_protocol::ThreadItem::DynamicToolCall { id, .. } = &item else {
            return Err(invalid("original Notes turn item changed kind"));
        };
        VerifiedNotesThreadOperation::from_original_item(&self.route, turn_id, id, &item)
    }

    async fn verify_human_turn(
        &mut self,
        state: &crate::AgentdState,
        adapter: &AgentdNotesLiteralAdapter,
        turn_id: &str,
    ) -> Result<VerifiedHumanTurn, AgentdError> {
        let user = self
            .find_original_item(turn_id, OriginalItemSelection::UserInput)
            .await?;
        let client_id = human::original_client_id(&user)?.to_owned();
        let delivery_id = client_id
            .strip_prefix("hepta.authbus:")
            .ok_or_else(|| invalid("missing original human delivery"))?
            .parse()
            .map_err(|_| invalid("invalid original human delivery"))?;
        crate::authbus_ingress::require_ready(state)?;
        let host = crate::authbus_ingress::attached(state)?;
        host.sync_replay_checkpoint().await?;
        let retained = host
            .evidence
            .retained_authbus_delivery(delivery_id)
            .await
            .map_err(|_| invalid("original admitted human input is absent"))?;
        if retained.status.subject_id != host.subject || retained.status.scope_digest != host.scope
        {
            return Err(invalid(
                "original human delivery belongs to another Agentd scope",
            ));
        }
        let human =
            VerifiedHumanTurn::from_original_input(adapter, &self.route, &user, retained).await?;
        let input = vec![codex_app_server_protocol::UserInput::Text {
            text: human.ingress().body.text.clone(),
            text_elements: vec![],
        }];
        let expected = codex_protocol::user_input::user_input_payload_sha256(
            &input
                .iter()
                .cloned()
                .map(codex_app_server_protocol::UserInput::into_core)
                .collect::<Vec<_>>(),
        )
        .map_err(|_| invalid("original human input cannot be canonically hashed"))?;
        let thread_id = self.route.thread_id.clone();
        let response: codex_app_server_protocol::ThreadQueueReconcileResponse = self
            .call(|request_id| ClientRequest::ThreadQueueReconcile {
                request_id,
                params: codex_app_server_protocol::ThreadQueueReconcileParams {
                    thread_id,
                    input,
                    client_user_message_id: client_id.clone(),
                    expected_payload_sha256: expected.clone(),
                    mode: codex_app_server_protocol::ThreadQueueReconcileMode::ReconcileOnly,
                },
            })
            .await?;
        human::confirm_original_queue(&response, &client_id, &expected, turn_id)?;
        host.sync_replay_checkpoint().await?;
        crate::authbus_ingress::require_ready(state)?;
        Ok(human)
    }

    async fn find_original_item(
        &mut self,
        original_turn_id: &str,
        selection: OriginalItemSelection<'_>,
    ) -> Result<codex_app_server_protocol::ThreadItem, AgentdError> {
        let end = tokio::time::Instant::now() + Duration::from_secs(5);
        let mut cursor = None;
        for _ in 0..16 {
            let thread_id = self.route.thread_id.clone();
            let turn_id = original_turn_id.to_owned();
            let page: ThreadItemsListResponse = tokio::time::timeout_at(
                end,
                self.call(|request_id| ClientRequest::ThreadItemsList {
                    request_id,
                    params: ThreadItemsListParams {
                        thread_id,
                        turn_id: Some(turn_id),
                        cursor,
                        limit: Some(128),
                        sort_direction: Some(SortDirection::Asc),
                    },
                }),
            )
            .await
            .map_err(|_| invalid("original callback preview deadline elapsed"))??;
            if page.data.len() > 128
                || page
                    .data
                    .iter()
                    .any(|item| item.turn_id != original_turn_id)
            {
                return Err(invalid("original callback page escaped its turn"));
            }
            for item in page.data {
                if matches!(selection, OriginalItemSelection::UserInput)
                    && matches!(
                        &item.item,
                        codex_app_server_protocol::ThreadItem::UserMessage { .. }
                    )
                {
                    return Ok(item.item);
                }
                if let codex_app_server_protocol::ThreadItem::DynamicToolCall {
                    id,
                    namespace,
                    tool,
                    ..
                } = &item.item
                {
                    let selected = match selection {
                        OriginalItemSelection::Call(call_id) => id == call_id,
                        OriginalItemSelection::FirstReplace => {
                            namespace.is_none() && tool == REPLACE_TOOL
                        }
                        OriginalItemSelection::UserInput => false,
                    };
                    if selected {
                        return Ok(item.item);
                    }
                }
            }
            cursor = page.next_cursor;
            if cursor.is_none() {
                break;
            }
        }
        Err(invalid(
            "original Core item is absent; no Notes operation prepared",
        ))
    }
}

impl AgentdNotesThreadToolRuntime {
    pub(crate) async fn run(
        mut self,
        state: Arc<crate::AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let session = self.session.take().ok_or_else(|| {
            invalid("original Notes thread mode requires its held Session lifetime")
        })?;
        session.check_alive()?;
        tokio::select! {
            biased;
            _ = cancellation.cancelled() => Ok(()),
            _ = session.readable() => Err(invalid("original Notes Session lifetime ended")),
            result = self.run_bound(state, cancellation.clone()) => result,
        }
    }

    async fn run_bound(
        mut self,
        state: Arc<crate::AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            ready = tokio::time::timeout(Duration::from_secs(10), state.wait_original_app_server_ready()) => {
                ready.map_err(|_| invalid("original App Server readiness deadline elapsed"))??;
            }
        }
        let mut connection = tokio::time::timeout(
            Duration::from_secs(10),
            OriginalConnection::connect(self.route.clone()),
        )
        .await
        .map_err(|_| invalid("original Notes thread connection deadline elapsed"))??;
        loop {
            let event = tokio::select! {
                _ = cancellation.cancelled() => return connection.client.shutdown().await.map_err(AgentdError::from),
                event = connection.client.next_observed_event() => event.ok_or_else(|| invalid("original Notes thread disconnected; retained operations cannot resend"))?,
            };
            if event.connection_id() != connection.client.connection_id() {
                return Err(invalid("original Notes callback connection changed"));
            }
            let (request_id, params) = match event.event() {
                AppServerEvent::ServerRequest(request) => {
                    let ServerRequest::DynamicToolCall { request_id, params } = request.as_ref()
                    else {
                        continue;
                    };
                    if !matches!(params.tool.as_str(), READ_TOOL | REPLACE_TOOL | STATUS_TOOL) {
                        continue;
                    }
                    (request_id.clone(), params.clone())
                }
                AppServerEvent::Disconnected { .. } | AppServerEvent::Lagged { .. } => {
                    return Err(invalid(
                        "original Notes tool stream gap; reconcile original identities",
                    ));
                }
                _ => continue,
            };
            let mut operation_id = None;
            let mut human_observation = None;
            let result = async {
                let call = connection.verify(&params).await?;
                let human = connection.verify_human_turn(&state, &self.adapter, call.turn_id()).await?;
                human_observation = Some(json!({"authbus_client_id":human.delivery_id(), "principal_id":human.owner().principal_id,
                    "session_id":human.owner().session_id,"permission_revision":human.owner().permission_revision,
                    "expires_at_ms":human.owner().expires_at_ms}));
                if call.tool() == STATUS_TOOL {
                    let navigation: StatusArguments =
                        serde_json::from_value(call.arguments().clone())?;
                    let item = connection
                        .original_item(&navigation.turn_id, &navigation.call_id)
                        .await?;
                    let original = VerifiedNotesThreadOperation::from_original_item(
                        &self.route,
                        &navigation.turn_id,
                        &navigation.call_id,
                        &item,
                    )?;
                    let first = connection.first_original_replace(&navigation.turn_id).await?;
                    if first.original_item().call_id() != original.original_item().call_id() {
                        return Err(invalid("status must name the original turn's first Notes write"));
                    }
                    operation_id = Some(self.adapter.run_id(&original.original_item().turn_intent_id(&self.route)?)?);
                    return self.observe_retained(&original).await;
                }
                if call.tool() == REPLACE_TOOL {
                    let first = connection.first_original_replace(call.turn_id()).await?;
                    let original_operation_id = self.adapter.run_id(&first.original_item().turn_intent_id(&self.route)?)?;
                    operation_id = Some(original_operation_id.clone());
                    if first.original_item().call_id() != call.call_id() {
                        // Core's original ordered items are the turn fence. A
                        // later call can only inspect the designated original
                        // operation; it cannot prepare or sign another one.
                        let mut value = self.observe_retained(&first).await.unwrap_or_else(|_| json!({"state":"Unknown","operation_id":original_operation_id,"receipt_utf8":null}));
                        value["write_admission"] = json!("refused_later_replace_in_original_turn");
                        value["original_turn_id"] = json!(first.original_item().turn_id());
                        value["original_call_id"] = json!(first.original_item().call_id());
                        return Ok(value);
                    }
                }
                self.execute(&call, &human).await
            }
            .await;
            let (value, success) = match result {
                Ok(mut value) => {
                    value["human_input"] = json!(human_observation);
                    let success = value["write_admission"]
                        != "refused_later_replace_in_original_turn"
                        && (params.tool == READ_TOOL
                            || (value["state"] == "Committed"
                                && value["receipt_utf8"].is_string()));
                    (value, success)
                }
                Err(error) => {
                    // Original operator diagnostics retain the refusal cause;
                    // renderer/model output remains a bounded observation.
                    eprintln!("original Notes tool refused or uncertain: {error}");
                    (
                        json!({"status":"unavailable_or_unknown", "operation_id":operation_id, "thread_id":self.route.thread_id,"turn_id":params.turn_id,"call_id":params.call_id,"instruction":"Reconcile the original call and retained operation. Do not repeat this as a new effect."}),
                        false,
                    )
                }
            };
            let response = DynamicToolCallResponse {
                content_items: vec![DynamicToolCallOutputContentItem::InputText {
                    text: serde_json::to_string(&value)?,
                }],
                success,
            };
            // Resolve exactly the callback received on this physical original
            // connection. Core owns the result item and model continuation.
            tokio::time::timeout(
                Duration::from_secs(5),
                connection
                    .client
                    .request_handle()
                    .resolve_server_request(request_id, serde_json::to_value(response)?),
            )
            .await
            .map_err(|_| invalid("original tool result acknowledgement unknown"))??;
        }
    }
}
