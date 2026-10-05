//! Original desktop owner commands and observed responses.
use super::*;

impl App {
    pub(super) fn submit(&mut self, cx: &mut Cx, command: OwnerCommand) {
        if self.busy {
            return;
        }
        match self
            .owner
            .as_ref()
            .ok_or("desktop owner is unavailable")
            .and_then(|owner| {
                owner
                    .submit(command)
                    .map_err(|_| "desktop owner is busy or unavailable")
            }) {
            Ok(()) => {
                self.busy = true;
                self.ui
                    .label(cx, ids!(console_status))
                    .set_text(cx, "Checking the original action…");
            }
            Err(error) => {
                self.observation = None;
                self.ui.label(cx, ids!(console_status)).set_text(cx, error);
            }
        }
        self.ui.redraw(cx);
    }

    pub(super) fn handle_owner_event(&mut self, cx: &mut Cx, event: &Event) {
        if let Event::Timer(event) = event
            && self.chat_timer.is_timer(event).is_some()
            && !self.console_visible
            && !self.busy
            && self
                .chat_view
                .as_ref()
                .is_some_and(|view| view.selected_thread.is_some() && !view.previous_action_pending)
        {
            self.submit(cx, OwnerCommand::ChatTimeline);
        }
        if matches!(event, Event::Startup) {
            self.chat_timer = cx.start_interval(1.0);
            match OwnerWorker::start(std::env::args().skip(1).collect()) {
                Ok(owner) => {
                    self.owner = Some(owner);
                    self.busy = true;
                }
                Err(error) => self
                    .ui
                    .label(cx, ids!(console_status))
                    .set_text(cx, &error.to_string()),
            }
        }
        if let Some(response) = self.owner.as_ref().and_then(OwnerWorker::poll) {
            self.busy = false;
            self.observation = response.observation;
            self.chat_view = response.chat;
            if response.clear_composer {
                self.ui.text_input(cx, ids!(message_input)).set_text(cx, "");
            }
            self.ui
                .label(cx, ids!(console_status))
                .set_text(cx, &response.message);
            let chat_ready = self
                .chat_view
                .as_ref()
                .is_some_and(|view| view.connection_ready);
            let pending = self
                .chat_view
                .as_ref()
                .is_some_and(|view| view.previous_action_pending);
            let selected = self
                .chat_view
                .as_ref()
                .is_some_and(|view| view.selected_thread.is_some());
            let available = self
                .observation
                .as_ref()
                .is_some_and(|view| view.ready && view.chat_available);
            self.ui.label(cx, ids!(owner_status)).set_text(cx, if pending {
                    "Previous chat action needs inspection. It will not be sent again automatically."
                } else if chat_ready { &response.message } else if self.observation.as_ref().is_some_and(|view| view.chat_available) {
                    "Choose a ready Agent to open its conversations."
                } else { "Chat is not connected. Console still provides runtime controls." });
            self.ui
                .button(cx, ids!(send))
                .set_enabled(cx, available && chat_ready && selected && !pending);
            self.ui
                .button(cx, ids!(new_conversation))
                .set_enabled(cx, available && chat_ready && !pending);
            self.ui
                .button(cx, ids!(refresh_conversation))
                .set_enabled(cx, chat_ready && selected && !pending);
            self.ui
                .button(cx, ids!(inspect_chat))
                .set_enabled(cx, pending);
            self.ui.button(cx, ids!(abandon_creation)).set_enabled(
                cx,
                self.chat_view
                    .as_ref()
                    .is_some_and(|view| view.previous_creation_pending),
            );
            self.ui.button(cx, ids!(cancel_reply)).set_enabled(
                cx,
                chat_ready
                    && !pending
                    && self
                        .chat_view
                        .as_ref()
                        .is_some_and(|view| view.active_turn.is_some()),
            );
            self.ui.button(cx, ids!(inspect)).set_enabled(
                cx,
                self.observation
                    .as_ref()
                    .is_none_or(|view| view.previous_action_pending),
            );
            self.ui.redraw(cx);
        }
    }
    pub(super) fn handle_owner_actions(&mut self, cx: &mut Cx, actions: &Actions) {
        if self.ui.button(cx, ids!(new_conversation)).clicked(actions) {
            self.submit(cx, OwnerCommand::ChatCreate);
        }
        if self
            .ui
            .button(cx, ids!(refresh_conversation))
            .clicked(actions)
        {
            self.submit(cx, OwnerCommand::ChatTimeline);
        }
        if self.ui.button(cx, ids!(inspect_chat)).clicked(actions) {
            self.submit(cx, OwnerCommand::ChatInspect);
        }
        if self.ui.button(cx, ids!(abandon_creation)).clicked(actions) {
            self.submit(cx, OwnerCommand::ChatAbandonCreation);
        }
        if self.ui.button(cx, ids!(cancel_reply)).clicked(actions) {
            self.submit(cx, OwnerCommand::ChatCancel);
        }
        if self.ui.button(cx, ids!(send)).clicked(actions) {
            let text = self.ui.text_input(cx, ids!(message_input)).text();
            if !text.trim().is_empty() {
                self.submit(cx, OwnerCommand::ChatSend(text));
            }
        }
        let agents = self.ui.portal_list(cx, ids!(chat_agents));
        for (index, item) in agents.items_with_actions(actions) {
            if item.as_button().clicked(actions)
                && !self.busy
                && let Some(view) = &self.observation
                && let Some(agent) = view.agents.get(index)
                && view.chat_available
                && agent.healthy
                && agent.running
            {
                self.submit(
                    cx,
                    OwnerCommand::OpenChat {
                        agent_id: agent.id.clone(),
                        revision: view.revision,
                    },
                );
            }
        }
        let rooms = self.ui.portal_list(cx, ids!(rooms));
        for (index, item) in rooms.items_with_actions(actions) {
            if item.button(cx, ids!(open)).clicked(actions)
                && !self.busy
                && let Some(row) = self
                    .chat_view
                    .as_ref()
                    .and_then(|view| view.conversations.get(index))
            {
                self.submit(cx, OwnerCommand::ChatSelect(row.id.clone()));
            }
        }
        if self.ui.button(cx, ids!(refresh)).clicked(actions) {
            self.submit(cx, OwnerCommand::Refresh);
        }
        if self.ui.button(cx, ids!(inspect)).clicked(actions) {
            self.submit(cx, OwnerCommand::Inspect);
        }
        let list = self.ui.portal_list(cx, ids!(agents));
        for (index, item) in list.items_with_actions(actions) {
            let Some(view) = &self.observation else {
                continue;
            };
            if self.busy
                || !view.lifecycle_available
                || view.previous_action_pending
                || view.revision != self.displayed_revision
            {
                continue;
            }
            let Some(agent) = view.agents.get(index) else {
                continue;
            };
            let operation = if item.button(cx, ids!(start)).clicked(actions) && !agent.active {
                Some(FleetLifecycleOperation::Start)
            } else if item.button(cx, ids!(stop)).clicked(actions) && agent.active {
                Some(FleetLifecycleOperation::Stop)
            } else if item.button(cx, ids!(restart)).clicked(actions)
                && agent.running
                && agent.healthy
            {
                Some(FleetLifecycleOperation::Restart)
            } else {
                None
            };
            if let Some(operation) = operation {
                self.submit(
                    cx,
                    OwnerCommand::Lifecycle {
                        agent_id: agent.id.clone(),
                        operation,
                        revision: view.revision,
                    },
                );
            }
        }
    }
}
