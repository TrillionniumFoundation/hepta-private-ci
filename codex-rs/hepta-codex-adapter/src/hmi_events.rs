use super::*;

impl HmiEventsV1 {
    pub async fn next(&mut self) -> Result<Option<HmiEventV1>, HmiError> {
        if self.ended { return Ok(None); }
        loop {
            let observed = self.client.next_observed_event().await;
            let event = match observed.as_ref() { Some(observed) => observed.event(),
                None => &AppServerEvent::Disconnected { message: "event stream ended".to_string() } };
            let late_interrupt = 'project: {
            let mut state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
            match event {
                AppServerEvent::Disconnected { message } => {
                    self.ended = true;
                    if terminal_is_known(&state) { state.fenced = true; return Ok(None); }
                    let output_scope = output_scope(&self.shared, &state);
                    let result = terminal(&mut state, output_scope, HmiTerminalStatusV1::Unknown, Some(message.clone()));
                    state.fenced = true;
                    return Ok(Some(result));
                }
                AppServerEvent::Lagged { .. } => {
                    self.ended = true;
                    let output_scope = output_scope(&self.shared, &state);
                    let result = terminal(&mut state, output_scope, HmiTerminalStatusV1::Unknown,
                        Some("event gap requires same-thread reconciliation".to_string()));
                    state.fenced = true;
                    return Ok(Some(result));
                }
                AppServerEvent::ServerRequest(_) => {
                    self.ended = true;
                    state.fenced = true;
                    let output_scope = output_scope(&self.shared, &state);
                    return Ok(Some(terminal(&mut state, output_scope, HmiTerminalStatusV1::Unknown,
                        Some("server request requires owning approval channel".to_string()))));
                }
                AppServerEvent::ServerNotification(notification) if !state.fenced => match notification.as_ref() {
                    ServerNotification::ItemStarted(started) if started.thread_id == self.shared.binding.thread_id => {
                        if let ThreadItem::UserMessage { client_id: Some(client_id), .. } = &started.item
                            && !terminal_is_known(&state)
                            && state.pending.as_ref().is_some_and(|(pending, _)| pending == client_id) {
                            if state.active_turn.as_ref() == Some(&started.turn_id) { continue; }
                            state.active_turn = Some(started.turn_id.clone());
                            if state.cancel_requested {
                                let turn_id = started.turn_id.clone();
                                break 'project Some(turn_id);
                            }
                            if !state.output_enabled { continue; }
                            return Ok(Some(HmiEventV1 { scope: output_scope(&self.shared, &state), kind: HmiEventKindV1::TurnStarted }));
                        }
                    }
                    ServerNotification::AgentMessageDelta(delta) if delta.thread_id == self.shared.binding.thread_id
                        && state.output_enabled && state.terminal.is_none()
                        && state.active_turn.as_deref() == Some(delta.turn_id.as_str()) => {
                        let bounded = update_text(&mut state, &delta.item_id, &delta.delta, true);
                        if let Err(error) = bounded {
                            let scope = output_scope(&self.shared, &state);
                            return Ok(Some(terminal(&mut state, scope, HmiTerminalStatusV1::Unknown, Some(error.to_string()))));
                        }
                        return Ok(Some(HmiEventV1 { scope: output_scope(&self.shared, &state), kind: HmiEventKindV1::TextDelta {
                            item_id: delta.item_id.clone(), delta: delta.delta.clone() } }));
                    }
                    ServerNotification::ItemCompleted(completed) if completed.thread_id == self.shared.binding.thread_id
                        && state.output_enabled && state.terminal.is_none()
                        && state.active_turn.as_deref() == Some(completed.turn_id.as_str()) => {
                        if let ThreadItem::AgentMessage { id, text, .. } = &completed.item {
                            let bounded = update_text(&mut state, id, text, false);
                        if let Err(error) = bounded {
                            let scope = output_scope(&self.shared, &state);
                            return Ok(Some(terminal(&mut state, scope, HmiTerminalStatusV1::Unknown, Some(error.to_string()))));
                        }
                            return Ok(Some(HmiEventV1 { scope: output_scope(&self.shared, &state), kind: HmiEventKindV1::TextFinal {
                                item_id: id.clone(), text: text.clone() } }));
                        }
                    }
                    ServerNotification::TurnCompleted(completed) if completed.thread_id == self.shared.binding.thread_id
                        && !terminal_is_known(&state) && state.active_turn.as_deref() == Some(completed.turn.id.as_str()) => {
                        let status = match completed.turn.status { TurnStatus::Completed => HmiTerminalStatusV1::Completed,
                            TurnStatus::Failed => HmiTerminalStatusV1::Failed, TurnStatus::Interrupted => HmiTerminalStatusV1::Interrupted,
                            TurnStatus::InProgress => return Err(HmiError::Invalid("nonterminal completion")) };
                        let error = completed.turn.error.as_ref().map(|error| error.message.clone());
                        let output_scope = output_scope(&self.shared, &state);
                        return Ok(Some(terminal(&mut state, output_scope, status, error)));
                    }
                    _ => {}
                },
                AppServerEvent::ServerNotification(_) => {}
            }
            None
            };
            if let Some(turn_id) = late_interrupt {
                let requests = HmiRequestsV1 { handle: self.client.request_handle(), shared: self.shared.clone() };
                requests.interrupt_turn(turn_id).await?;
            }
        }
    }

    pub async fn shutdown(self) -> Result<(), HmiError> {
        self.shared.state.lock().map_err(|_| HmiError::Fenced)?.fenced = true;
        tokio::time::timeout(self.shared.timeout, self.client.shutdown()).await.map_err(|_| HmiError::Deadline)?
            .map_err(|error| HmiError::Transport(error.to_string()))
    }
}

fn update_text(state: &mut State, item_id: &str, text: &str, append: bool) -> Result<(), HmiError> {
    let previous = state.items.iter().find(|(id, _)| id == item_id).map(|(_, text)| text.len()).unwrap_or(0);
    let total = state.items.iter().map(|(_, text)| text.len()).sum::<usize>();
    if item_id.len() > 256 || text.len() > MAX_TEXT_BYTES || total - previous + text.len() + if append { previous } else { 0 } > MAX_TEXT_BYTES
        || (previous == 0 && state.items.len() >= MAX_ITEMS) {
        state.fenced = true;
        return Err(HmiError::Invalid("output bound"));
    }
    if let Some((_, value)) = state.items.iter_mut().find(|(id, _)| id == item_id) {
        if append { value.push_str(text); } else { *value = text.to_string(); }
    } else { state.items.push((item_id.to_string(), text.to_string())); }
    Ok(())
}

