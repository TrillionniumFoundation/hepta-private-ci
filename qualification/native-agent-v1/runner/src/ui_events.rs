//! Provisional qualification UI delivery, distinct from the Core UI owner.
//!
//! The parent drains the existing JSON-lines channel and checks bounded text
//! deltas against completion of the same immutable context item. This sink has
//! no production grant, queue, ThreadStore, or new effect journal.

use std::io::Write;
use std::sync::Arc;
use std::sync::Mutex;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_native_agent::NativeEvent;
use codex_hepta_native_agent::NativeEventSink;
use codex_hepta_native_agent::TurnBinding;
use codex_hepta_native_agent::TurnState;
use codex_hepta_types::Digest32;
use hepta_native_qualification::owner::SessionOwner;
use serde_json::Value;
use serde_json::json;

pub const OWNER_SCOPE: &str = "hepta.qualification.turn-owner.v2";
pub const UI_SCHEMA: &str = "hepta.qualification.streamed-ui.v1";

pub fn contract() -> Value {
    json!({"schema":UI_SCHEMA, "delivery":"text_delta_then_same_item_completion",
        "max_delta_bytes":32768, "max_item_bytes":65536, "max_items":1024,
        "max_total_bytes":4194304, "max_events":8192, "production_core_ui":false})
}

pub struct QualificationUiSink {
    owner: Arc<SessionOwner>,
    session: String,
    writer: Mutex<Box<dyn Write + Send>>,
}

impl QualificationUiSink {
    pub fn stdout(owner: Arc<SessionOwner>, session: String) -> Self {
        Self {
            owner,
            session,
            writer: Mutex::new(Box::new(std::io::stdout())),
        }
    }

    fn item_id(&self, context_index: usize) -> Result<String> {
        let binding = serde_json::to_vec(&hepta_native_qualification::snapshot::binding_json(
            &self.owner.binding,
        ))?;
        Ok(format!(
            "qualification:item:{}:{context_index}",
            Digest32::of_bytes(&binding)
        ))
    }

    fn send(&self, record: Value) -> Result<()> {
        self.owner.check(&self.owner.binding)?;
        let mut bytes = serde_json::to_vec(&record)?;
        bytes.push(b'\n');
        let mut writer = self
            .writer
            .lock()
            .map_err(|_| anyhow::anyhow!("qualification UI lock poisoned"))?;
        writer.write_all(&bytes)?;
        writer.flush()?;
        Ok(())
    }

    /// Publish only items already present in the immutable owner's context.
    /// Unsettled streamed text never becomes a fabricated completed item.
    pub fn publish_completed(&self, state: &TurnState) -> Result<()> {
        self.owner.check(&state.binding)?;
        for (index, item) in state.context.iter().enumerate() {
            if item["type"] != "message" || item["role"] != "assistant" {
                continue;
            }
            let mut text = String::new();
            for part in item["content"]
                .as_array()
                .context("assistant UI content missing")?
            {
                if part["type"] == "output_text" {
                    text.push_str(part["text"].as_str().context("assistant UI text missing")?);
                }
            }
            ensure!(text.len() <= 65536, "qualification UI item exceeds bound");
            self.send(json!({"event":"ui/item_completed", "schema":UI_SCHEMA,
                "session":self.session, "item_id":self.item_id(index)?, "text":text,
                "context_index":index, "phase":item.get("phase")}))?;
        }
        Ok(())
    }
}

impl NativeEventSink for QualificationUiSink {
    async fn emit(&self, binding: &TurnBinding, event: NativeEvent) -> Result<()> {
        self.owner.check(binding)?;
        let NativeEvent::TextDelta(delta) = event;
        ensure!(
            delta.text.len() <= 32768,
            "qualification UI delta exceeds bound"
        );
        self.send(json!({"event":"ui/text_delta", "schema":UI_SCHEMA,
            "session":self.session, "item_id":self.item_id(delta.context_index)?,
            "content_index":delta.content_index, "delta":delta.text, "phase":delta.phase,
            "context_index":delta.context_index, "operation_id":delta.operation_id,
            "response_id":delta.response_id, "provider_item_id":delta.provider_item_id}))
    }
}

#[cfg(test)]
#[path = "ui_events_tests.rs"]
mod tests;
