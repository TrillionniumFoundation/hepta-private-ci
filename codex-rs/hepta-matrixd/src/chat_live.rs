//! Bounded, connection-local observations; never a durable history owner.
use super::{
    message,
    wire::{ChatMessage, MAX_CHAT_PAGE},
};
use codex_app_server_protocol::{ServerNotification, ThreadItemEntry};
use std::collections::VecDeque;

#[derive(Default)]
pub(super) struct LiveTimeline {
    messages: VecDeque<(String, ChatMessage)>,
    turns: VecDeque<(String, Option<String>)>,
}
impl LiveTimeline {
    pub fn observe(&mut self, notification: ServerNotification) {
        match notification {
            ServerNotification::AgentMessageDelta(value) => {
                if !valid_id(&value.thread_id)
                    || !valid_id(&value.turn_id)
                    || !valid_id(&value.item_id)
                {
                    return;
                }
                let index = self.messages.iter().position(|(thread, item)| {
                    thread == &value.thread_id && item.id == value.item_id
                });
                if let Some(index) = index {
                    let message = &mut self.messages[index].1;
                    if message.turn_id != value.turn_id {
                        return;
                    }
                    super::append_display(&mut message.body, &value.delta);
                } else {
                    self.upsert(
                        value.thread_id,
                        ChatMessage {
                            id: value.item_id,
                            turn_id: value.turn_id,
                            sender: "assistant".into(),
                            body: super::bounded(value.delta),
                        },
                    );
                }
            }
            ServerNotification::ItemStarted(value) => {
                if let Some(item) = message(ThreadItemEntry {
                    turn_id: value.turn_id,
                    item: value.item,
                }) {
                    self.upsert(value.thread_id, item);
                }
            }
            ServerNotification::ItemCompleted(value) => {
                if let Some(item) = message(ThreadItemEntry {
                    turn_id: value.turn_id,
                    item: value.item,
                }) {
                    self.upsert(value.thread_id, item);
                }
            }
            ServerNotification::TurnStarted(value) => {
                self.turn(value.thread_id, Some(value.turn.id))
            }
            ServerNotification::TurnCompleted(value)
                if !self.turns.iter().any(|(thread, turn)| {
                    thread == &value.thread_id
                        && turn.as_ref().is_some_and(|id| id != &value.turn.id)
                }) =>
            {
                self.turn(value.thread_id, None);
            }
            _ => {}
        }
    }
    fn upsert(&mut self, thread: String, item: ChatMessage) {
        if !valid_id(&thread) || !valid_id(&item.id) || !valid_id(&item.turn_id) {
            return;
        }
        if let Some((_, existing)) = self
            .messages
            .iter_mut()
            .find(|(id, message)| id == &thread && message.id == item.id)
        {
            *existing = item;
            return;
        }
        if self.messages.len() == MAX_CHAT_PAGE as usize {
            self.messages.pop_front();
        }
        self.messages.push_back((thread, item));
    }
    fn turn(&mut self, thread: String, turn: Option<String>) {
        if !valid_id(&thread) || turn.as_ref().is_some_and(|id| !valid_id(id)) {
            return;
        }
        self.turns.retain(|(id, _)| id != &thread);
        if self.turns.len() == MAX_CHAT_PAGE as usize {
            self.turns.pop_front();
        }
        self.turns.push_back((thread, turn));
    }
    pub fn merge(
        &self,
        thread: &str,
        data: &mut Vec<ChatMessage>,
        limit: u32,
        active: &mut Option<String>,
    ) {
        if let Some((_, turn)) = self.turns.iter().find(|(id, _)| id == thread) {
            *active = turn.clone();
        }
        for (_, item) in self.messages.iter().filter(|(id, _)| id == thread) {
            if let Some(existing) = data.iter_mut().find(|row| row.id == item.id) {
                *existing = item.clone();
            } else if active.as_deref() == Some(item.turn_id.as_str()) {
                data.push(item.clone());
            }
        }
        if data.len() > limit as usize {
            data.drain(..data.len() - limit as usize);
        }
    }
}
fn valid_id(value: &str) -> bool {
    !value.is_empty() && value.len() <= 256 && !value.chars().any(char::is_control)
}

#[cfg(test)]
#[path = "chat_live_tests.rs"]
mod tests;
