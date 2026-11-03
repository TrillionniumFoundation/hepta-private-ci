//! Provisional text uses the original turn's UI event channel.
//! Completion still comes from the original persisted model output.

use codex_protocol::items::AgentMessageItem;
use codex_protocol::items::TurnItem;
use codex_protocol::models::MessagePhase;
use codex_protocol::protocol::AgentMessageContentDeltaEvent;
use codex_protocol::protocol::EventMsg;

use super::HostedTurnEntry;
use super::invalid;

/// One bounded preview from a hosted executor, carrying its canonical item ID.
pub struct HostedTextDelta {
    pub item_id: String,
    pub text: String,
    pub phase: Option<MessagePhase>,
}

impl HostedTurnEntry {
    /// Publish text on this exact task without admitting an effect or completing
    /// an item. The persisted original response supplies the final item content.
    pub async fn emit_text_delta(
        &self,
        delta: HostedTextDelta,
    ) -> codex_protocol::error::Result<()> {
        if delta.item_id.is_empty() || delta.item_id.len() > 256 || delta.text.len() > 32 * 1024 {
            return Err(invalid(
                "hosted text delta exceeds its bounded identity or text size",
            ));
        }
        if delta.text.is_empty() {
            return Ok(());
        }
        let mut started = self.stream_items.lock().await;
        self.with_current(self.thread_id, &self.turn_id, || ())?;
        let session = self
            .session
            .upgrade()
            .ok_or_else(|| invalid("hosted text owner stopped"))?;
        let context = self
            .context
            .upgrade()
            .ok_or_else(|| invalid("hosted text task stopped"))?;
        if !started.contains(&delta.item_id) {
            if started.len() >= 1024 {
                return Err(invalid("hosted turn exceeded its streamed item bound"));
            }
            let item = TurnItem::AgentMessage(AgentMessageItem {
                id: delta.item_id.clone(),
                content: Vec::new(),
                phase: delta.phase,
                memory_citation: None,
                delivery: None,
            });
            session.emit_turn_item_started(&context, &item).await;
            started.insert(delta.item_id.clone());
        }
        if self.cancellation.is_cancelled() {
            return Err(codex_protocol::error::CodexErr::TurnAborted);
        }
        session
            .send_event(
                &context,
                EventMsg::AgentMessageContentDelta(AgentMessageContentDeltaEvent {
                    thread_id: self.thread_id.to_string(),
                    turn_id: self.turn_id.clone(),
                    item_id: delta.item_id,
                    delta: delta.text,
                }),
            )
            .await;
        Ok(())
    }
}
