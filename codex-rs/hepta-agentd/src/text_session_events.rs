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
    /// Empty for original-thread activity without a retained local input.
    /// Such events never acknowledge admission of a new UI message.
    pub message_id: String,
    pub delivery_id: String,
    pub turn_id: String,
    pub notification: ServerNotification,
}

pub enum AgentdTextObservation {
    Notification(AgentdTextEvent),
    Approval(TextApprovalObservation),
}

impl AgentdTextEvents {
    pub async fn next(&mut self) -> Result<Option<AgentdTextEvent>, TextSessionError> {
        loop {
            match self.next_observation().await? {
                Some(AgentdTextObservation::Notification(event)) => return Ok(Some(event)),
                Some(AgentdTextObservation::Approval(_)) => {}
                None => return Ok(None),
            }
        }
    }

    pub async fn next_observation(
        &mut self,
    ) -> Result<Option<AgentdTextObservation>, TextSessionError> {
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
                AppServerEvent::ServerRequest(request) => {
                    let requests = AgentdTextRequests {
                        handle: self.client.request_handle(),
                        shared: self.shared.clone(),
                    };
                    let observation = requests.observe_approval(request).await?;
                    return Ok(Some(AgentdTextObservation::Approval(observation)));
                }
            };
            if let ServerNotification::ServerRequestResolved(resolved) = notification {
                if resolved.thread_id != self.shared.config.thread_id {
                    continue;
                }
                let id = serde_json::to_string(&resolved.request_id).map_err(unavailable)?;
                self.shared.current()?.approvals.remove(&id);
                return Ok(Some(AgentdTextObservation::Approval(
                    TextApprovalObservation::Resolved {
                        connection_id: self.shared.connection_id,
                        id,
                    },
                )));
            }
            let (thread_id, turn_id) = match notification {
                ServerNotification::ItemStarted(value) => (&value.thread_id, &value.turn_id),
                ServerNotification::ItemCompleted(value) => (&value.thread_id, &value.turn_id),
                ServerNotification::AgentMessageDelta(value) => (&value.thread_id, &value.turn_id),
                ServerNotification::CommandExecutionOutputDelta(value) => {
                    (&value.thread_id, &value.turn_id)
                }
                ServerNotification::PlanDelta(value) => (&value.thread_id, &value.turn_id),
                ServerNotification::TurnDiffUpdated(value) => (&value.thread_id, &value.turn_id),
                ServerNotification::TurnPlanUpdated(value) => (&value.thread_id, &value.turn_id),
                ServerNotification::TurnCompleted(value) => (&value.thread_id, &value.turn.id),
                _ => continue,
            };
            if thread_id != &self.shared.config.thread_id {
                continue;
            }
            let bytes = serde_json::to_vec(notification).map_err(unavailable)?.len();
            let (event, cancel) = {
                let mut state = self.shared.current()?;
                if state.snapshot_turns.contains_key(turn_id) {
                    continue;
                }
                let used = state.stream_bytes.entry(turn_id.clone()).or_default();
                *used = used.saturating_add(bytes);
                if bytes > 32 * 1024 || *used > 128 * 1024 {
                    // The original notification remains owned by App Server.
                    // A large artifact changes only display strategy, not the
                    // connection identity, authority, or durable delivery.
                    state.snapshot_turns.insert(turn_id.clone(), false);
                    state.stream_bytes.remove(turn_id);
                    continue;
                }
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
                if matches!(notification, ServerNotification::TurnCompleted(_)) {
                    state.stream_bytes.remove(turn_id);
                }
                let pending = state
                    .pending
                    .values_mut()
                    .find(|pending| pending.turn_id.as_ref() == Some(turn_id));
                if pending.as_ref().is_some_and(|pending| pending.terminal) {
                    continue;
                }
                if pending.as_ref().is_some_and(|pending| pending.recovered) {
                    state.snapshot_turns.insert(turn_id.clone(), false);
                    continue;
                }
                if let ServerNotification::TurnCompleted(completed) = notification
                    && completed.turn.status == TurnStatus::InProgress
                {
                    return Err(TextSessionError::Identity);
                }
                let (message_id, delivery_id, cancel) = if let Some(pending) = pending {
                    if matches!(notification, ServerNotification::TurnCompleted(_)) {
                        pending.terminal = true;
                    }
                    (
                        pending.envelope.message_id.clone(),
                        pending.delivery_id.clone(),
                        pending.cancellation_requested
                            && matches!(notification, ServerNotification::ItemStarted(value) if matches!(&value.item, ThreadItem::UserMessage { .. })),
                    )
                } else {
                    (String::new(), String::new(), false)
                };
                (
                    AgentdTextEvent {
                        connection_id: self.shared.connection_id,
                        thread_id: thread_id.clone(),
                        message_id,
                        delivery_id,
                        turn_id: turn_id.clone(),
                        notification: notification.clone(),
                    },
                    cancel,
                )
            };
            if cancel {
                let requests = AgentdTextRequests {
                    handle: self.client.request_handle(),
                    shared: self.shared.clone(),
                };
                requests.interrupt_turn(turn_id.clone()).await?;
            }
            return Ok(Some(AgentdTextObservation::Notification(event)));
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
