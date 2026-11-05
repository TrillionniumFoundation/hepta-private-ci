//! One original connection resolves callbacks; Core retains the conversation.
use super::transport::OriginalConnection;
use super::*;
use codex_app_server_client::AppServerEvent;
use codex_app_server_protocol::DynamicToolCallOutputContentItem;
use codex_app_server_protocol::DynamicToolCallResponse;
use codex_app_server_protocol::ServerRequest;
use tokio_util::sync::CancellationToken;

fn fenced_response(callback: Value, original_reference: Value, original_operation: Value) -> Value {
    json!({"status":"fenced","write_admission":"refused_later_effect_in_original_turn",
        "requested_effect_performed":false,"callback":callback,
        "original_reference":original_reference,"original_operation":original_operation})
}

fn response_succeeded(tool: &str, value: &Value) -> bool {
    if matches!(
        value["status"].as_str(),
        Some("fenced" | "unknown" | "unavailable_or_unknown")
    ) {
        return false;
    }
    match tool {
        READ_TOOL | CALCULATOR_READ_TOOL => {
            value["current_state"].is_object() && value["provenance"]["tool"] == tool
        }
        REPLACE_TOOL | STATUS_TOOL | CALCULATOR_EVALUATE_TOOL | CALCULATOR_STATUS_TOOL => {
            let original_tool = if matches!(tool, REPLACE_TOOL | STATUS_TOOL) {
                REPLACE_TOOL
            } else {
                CALCULATOR_EVALUATE_TOOL
            };
            value["source_domain"] == "original_protected_sender_reference"
                && value["provenance"]["tool"] == original_tool
                && value["state"] == "Committed"
                && value["receipt_utf8"].is_string()
        }
        _ => false,
    }
}

#[cfg(test)]
#[path = "desktop_thread_response_tests.rs"]
mod tests;

impl AgentdDesktopThreadToolRuntime {
    pub(crate) async fn run(
        mut self,
        state: Arc<crate::AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let session = self
            .session
            .take()
            .ok_or_else(|| invalid("original Desktop held Session absent"))?;
        session.check_alive()?;
        tokio::select! {
            biased;
            _ = cancellation.cancelled() => Ok(()),
            _ = session.readable() => Err(invalid("original Desktop Session lifetime ended")),
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
            OriginalConnection::connect(self.route.clone(), &self.seed),
        )
        .await
        .map_err(|_| invalid("original Desktop connection deadline elapsed"))??;
        loop {
            let event = tokio::select! {
                _ = cancellation.cancelled() => return connection.client.shutdown().await.map_err(AgentdError::from),
                event = connection.client.next_observed_event() => event.ok_or_else(|| invalid("original Desktop connection ended; no resends"))?,
            };
            if event.connection_id() != connection.client.connection_id() {
                return Err(invalid("original Desktop callback connection changed"));
            }
            let (request_id, params) = match event.event() {
                AppServerEvent::ServerRequest(request) => {
                    let ServerRequest::DynamicToolCall { request_id, params } = request.as_ref()
                    else {
                        continue;
                    };
                    if !matches!(
                        params.tool.as_str(),
                        READ_TOOL
                            | REPLACE_TOOL
                            | STATUS_TOOL
                            | CALCULATOR_READ_TOOL
                            | CALCULATOR_EVALUATE_TOOL
                            | CALCULATOR_STATUS_TOOL
                    ) {
                        continue;
                    }
                    (request_id.clone(), params.clone())
                }
                AppServerEvent::Disconnected { .. } | AppServerEvent::Lagged { .. } => {
                    return Err(invalid(
                        "original Desktop stream gap; reconcile existing operations",
                    ));
                }
                _ => continue,
            };
            let mut human_observation = None;
            let result = async {
                let call = connection.verify(&params).await?;
                let human = connection.verify_human_turn(&state, &self.adapter, call.turn_id()).await?;
                human_observation = Some(json!({"authbus_client_id":human.delivery_id(),
                    "principal_id":human.owner().principal_id,"session_id":human.owner().session_id,
                    "permission_revision":human.owner().permission_revision,"expires_at_ms":human.owner().expires_at_ms}));
                if matches!(call.tool(), STATUS_TOOL | CALCULATOR_STATUS_TOOL) {
                    let navigation: StatusArguments = serde_json::from_value(call.arguments().clone())?;
                    let tool = if call.tool() == STATUS_TOOL { REPLACE_TOOL } else { CALCULATOR_EVALUATE_TOOL };
                    let end = tokio::time::Instant::now() + Duration::from_secs(5);
                    let observed = match navigation {
                        StatusArguments::Exact(value) => self.adapter.recorded_desktop_operation(
                            &self.route, tool, &value.turn_id, &value.call_id, end,
                        ).await?,
                        StatusArguments::Selected(_) => self.adapter.latest_recorded_desktop_operation(&self.route, tool, end).await?,
                    };
                    return self.observe_lookup(observed).await;
                }
                if matches!(call.tool(), REPLACE_TOOL | CALCULATOR_EVALUATE_TOOL) {
                    let retained = self.adapter.recorded_desktop_turn_operation(
                        &self.route, call.turn_id(),
                        tokio::time::Instant::now() + Duration::from_secs(5),
                    ).await?;
                    match retained {
                        RecordedDesktopLookup::Found(original) => {
                            let same = original.reference.call_id == call.call_id()
                                && original.reference.tool == call.tool()
                                && original.reference.callback_sha256 == call.callback_digest().to_string();
                            let reference = serde_json::to_value(&original.reference)?;
                            let observed = self.observe_recorded(original).await?;
                            return Ok(if same { observed } else {
                                fenced_response(self.provenance(&call), reference, observed)
                            });
                        }
                        RecordedDesktopLookup::Unknown("original_request_not_observed") => {}
                        RecordedDesktopLookup::Unknown(reason) => return Err(invalid(reason)),
                    }
                    let first = connection.first_original_effect(call.turn_id()).await?;
                    let first = first.original_item();
                    if first.call_id() != call.call_id() || first.tool() != call.tool() {
                        // Keep the actual first application's receipt nested.
                        // It can never be relabelled as this refused tool's success.
                        let observed = self.observe_original(first).await.unwrap_or_else(|_| json!({"status":"unknown"}));
                        return Ok(fenced_response(self.provenance(&call), self.provenance(first), observed));
                    }
                    if first.callback_digest() != call.callback_digest() {
                        return Err(invalid("original first effect changed after callback verification"));
                    }
                }
                self.execute(&call, &human).await
            }.await;
            let (mut value, success) = match result {
                Ok(value) => {
                    let success = response_succeeded(&params.tool, &value);
                    (value, success)
                }
                Err(error) => {
                    eprintln!("original Desktop tool refused or uncertain: {error}");
                    (
                        json!({"status":"unavailable_or_unknown",
                        "instruction":"Reconcile the original retained operation; do not repeat it under a new call or target."}),
                        false,
                    )
                }
            };
            value["human_input"] = json!(human_observation);
            value["callback"] = json!({"thread_id":self.route.thread_id,"app_server_session_id":self.route.app_server_session_id,
                "turn_id":params.turn_id,"call_id":params.call_id,"tool":params.tool});
            let text = serde_json::to_string(&value)?;
            if text.len() > 16_384 {
                return Err(invalid(
                    "original Desktop result exceeds bounded Core output",
                ));
            }
            let response = DynamicToolCallResponse {
                content_items: vec![DynamicToolCallOutputContentItem::InputText { text }],
                success,
            };
            // Exactly the callback received on this original physical connection.
            // A missing acknowledgement exits the required task without replay.
            tokio::time::timeout(
                Duration::from_secs(5),
                connection
                    .client
                    .request_handle()
                    .resolve_server_request(request_id, serde_json::to_value(response)?),
            )
            .await
            .map_err(|_| invalid("original Desktop result acknowledgement unknown"))??;
        }
    }
}
