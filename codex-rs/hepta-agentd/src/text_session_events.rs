use codex_app_server_client::AppServerEvent;

use super::*;

/// Original protocol observations, including tool/file/artifact ThreadItems.
/// UI consumers upsert item IDs and replace complete items; deltas are only for
/// this live connection. These observations do not grant execution authority.
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AgentdTextEvent {
    pub connection_id: u64,
    pub thread_id: String,
    pub message_id: String,
    pub delivery_id: String,
    pub turn_id: String,
    pub notification: ServerNotification,
}

impl AgentdTextEvents {
    pub async fn next(&mut self) -> Result<Option<AgentdTextEvent>, TextSessionError> {
        if self.ended {
            return Ok(None);
        }
        loop {
            let Some(observed) = self.client.next_observed_event().await else {
                self.shared.state()?.fenced = true;
                self.ended = true;
                return Err(unavailable(
                    "stream disconnected; reconcile original identities",
                ));
            };
            if observed.connection_id() != self.shared.connection_id {
                self.shared.state()?.fenced = true;
                return Err(TextSessionError::Identity);
            }
            let notification = match observed.event() {
                AppServerEvent::ServerNotification(notification) => notification.as_ref(),
                AppServerEvent::Disconnected { .. } | AppServerEvent::Lagged { .. } => {
                    self.shared.state()?.fenced = true;
                    self.ended = true;
                    return Err(unavailable("stream gap; reconcile original identities"));
                }
                AppServerEvent::ServerRequest(_) => {
                    self.shared.state()?.fenced = true;
                    self.ended = true;
                    return Err(unavailable("original approval channel required"));
                }
            };
            let Some((thread_id, turn_id)) = backend::notification_route(notification) else {
                continue;
            };
            if thread_id != &self.shared.config.thread_id {
                continue;
            }
            if serde_json::to_vec(notification).map_err(unavailable)?.len() > MAX_OBSERVATION_BYTES
            {
                self.shared.state()?.fenced = true;
                return Err(TextSessionError::Capacity);
            }
            let (event, cancel) = {
                let mut state = self.shared.current()?;
                if let ServerNotification::ItemStarted(started) = notification
                    && let ThreadItem::UserMessage {
                        client_id: Some(id),
                        content,
                        ..
                    } = &started.item
                    && let Some(pending) = state
                        .pending
                        .values_mut()
                        .find(|pending| &pending.client_id == id)
                {
                    if content != &pending.input
                        || pending.turn_id.as_ref().is_some_and(|id| id != turn_id)
                    {
                        state.fenced = true;
                        return Err(TextSessionError::Identity);
                    }
                    pending.turn_id = Some(turn_id.clone());
                }
                let Some(pending) = state
                    .pending
                    .values_mut()
                    .find(|pending| pending.turn_id.as_ref() == Some(turn_id))
                else {
                    continue;
                };
                if pending.terminal {
                    continue;
                }
                // App Server deltas have no replay cursor. After reconnect an
                // active snapshot can overlap queued deltas; use replacement
                // snapshots and final items for that turn until it terminates.
                if pending.recovered && backend::is_nonreplayable_delta(notification) {
                    continue;
                }
                if let ServerNotification::TurnCompleted(completed) = notification {
                    if completed.turn.status == TurnStatus::InProgress {
                        return Err(TextSessionError::Identity);
                    }
                    pending.terminal = true;
                }
                let cancel = pending.cancellation_requested
                    && !pending.interrupt_attempted
                    && matches!(notification, ServerNotification::ItemStarted(value) if matches!(&value.item, ThreadItem::UserMessage { .. }));
                (
                    AgentdTextEvent {
                        connection_id: self.shared.connection_id,
                        thread_id: thread_id.clone(),
                        message_id: pending.envelope.message_id.clone(),
                        delivery_id: pending.delivery_id.clone(),
                        turn_id: turn_id.clone(),
                        notification: notification.clone(),
                    },
                    cancel,
                )
            };
            if cancel {
                let requests = AgentdTextRequests {
                    shared: self.shared.clone(),
                };
                requests.interrupt_turn(turn_id.clone()).await?;
            }
            return Ok(Some(event));
        }
    }

    pub async fn shutdown(self) -> Result<(), TextSessionError> {
        self.shared.state()?.fenced = true;
        tokio::time::timeout(REQUEST_TIMEOUT, self.client.shutdown())
            .await
            .map_err(unavailable)?
            .map_err(unavailable)
    }
}
