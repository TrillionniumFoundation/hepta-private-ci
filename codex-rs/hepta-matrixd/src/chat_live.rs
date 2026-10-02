//! Bounded, connection-local observations; never a durable history owner.
use super::{
    message,
    wire::{ChatMessage, MAX_CHAT_PAGE},
};
use codex_app_server_protocol::{ServerNotification, ThreadItemEntry, ThreadItemsListResponse};
use std::collections::{BTreeSet, VecDeque};

#[derive(Default)]
pub(super) struct LiveTimeline {
    messages: VecDeque<(String, ChatMessage)>,
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
    pub fn merge(
        &self,
        thread: &str,
        data: &mut Vec<ChatMessage>,
        limit: u32,
        active: &str,
        window: &ActiveItemWindow,
    ) {
        let ActiveItemWindow::Complete { turn_id, ids } = window else {
            return;
        };
        if turn_id != active {
            return;
        }
        let capacity = (limit as usize).saturating_sub(data.len());
        let candidates: Vec<_> = self
            .messages
            .iter()
            .filter(|(id, item)| {
                id == thread
                    && item.turn_id == active
                    && !ids.contains(&item.id)
                    && !data.iter().any(|row| row.id == item.id)
            })
            .map(|(_, item)| item)
            .collect();
        // Never drain or replace authoritative rows, even at a full page.
        let skip = candidates.len().saturating_sub(capacity);
        data.extend(candidates.into_iter().skip(skip).cloned());
    }
}
/// Membership proof is scoped to one complete, bounded persisted active turn.
pub(super) enum ActiveItemWindow {
    Complete {
        turn_id: String,
        ids: BTreeSet<String>,
    },
    Incomplete,
}
impl ActiveItemWindow {
    pub fn from_response(response: ThreadItemsListResponse, expected_turn: &str) -> Self {
        if response.next_cursor.is_some()
            || response.data.len() > MAX_CHAT_PAGE as usize
            || !valid_id(expected_turn)
            || response
                .data
                .iter()
                .any(|row| row.turn_id != expected_turn || !valid_id(row.item.id()))
        {
            return Self::Incomplete;
        }
        let count = response.data.len();
        let ids: BTreeSet<_> = response
            .data
            .into_iter()
            .map(|row| row.item.id().to_owned())
            .collect();
        if ids.len() != count {
            return Self::Incomplete;
        }
        Self::Complete {
            turn_id: expected_turn.into(),
            ids,
        }
    }
}

fn valid_id(value: &str) -> bool {
    !value.is_empty() && value.len() <= 256 && !value.chars().any(char::is_control)
}

#[cfg(test)]
#[path = "chat_live_tests.rs"]
mod tests;
