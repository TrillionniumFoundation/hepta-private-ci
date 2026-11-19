//! Original transport and pending-call resolution. The Core/App Server owner
//! retains the conversation and dynamic-tool callback; this task adds no log.
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::DynamicToolCallParams;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::SortDirection;
use codex_app_server_protocol::ThreadItemsListParams;
use codex_app_server_protocol::ThreadItemsListResponse;
use serde::de::DeserializeOwned;

use super::*;
#[derive(Clone, Copy)]
enum OriginalItemSelection<'a> {
    Call(&'a str),
    FirstEffect,
    UserInput,
}

pub(super) struct OriginalConnection {
    pub(super) client: RemoteAppServerClient,
    route: AgentdTextSessionConfig,
    next_request: i64,
}

impl OriginalConnection {
    pub(super) async fn connect(
        route: AgentdTextSessionConfig,
        seed: &crate::DesktopThreadSeedReceipt,
    ) -> Result<Self, AgentdError> {
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
                client_name: "hepta-original-desktop-thread-tools".into(),
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
        // The same actual connection must resume and verify the original
        // model/provider/catalog/meta tuple before observing any tool event.
        crate::verify_original_desktop_thread_seed(&client, seed).await?;
        let connection = Self {
            client,
            route,
            next_request: 1,
        };
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

    pub(super) async fn verify(
        &mut self,
        params: &DynamicToolCallParams,
    ) -> Result<VerifiedDesktopThreadCall, AgentdError> {
        VerifiedDesktopThreadCall::validate_callback(&self.route, params)?;
        let item = self.original_item(&params.turn_id, &params.call_id).await?;
        VerifiedDesktopThreadCall::from_original_item(&self.route, params, &item)
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

    pub(super) async fn first_original_effect(
        &mut self,
        turn_id: &str,
    ) -> Result<VerifiedDesktopThreadOperation, AgentdError> {
        let item = self
            .find_original_item(turn_id, OriginalItemSelection::FirstEffect)
            .await?;
        let codex_app_server_protocol::ThreadItem::DynamicToolCall { id, .. } = &item else {
            return Err(invalid("original Notes turn item changed kind"));
        };
        VerifiedDesktopThreadOperation::from_original_item(&self.route, turn_id, id, &item)
    }

    pub(super) async fn verify_human_turn(
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
                        OriginalItemSelection::FirstEffect => {
                            namespace.is_none()
                                && matches!(tool.as_str(), REPLACE_TOOL | CALCULATOR_EVALUATE_TOOL)
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
