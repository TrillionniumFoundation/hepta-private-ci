//! Validate streamed text coordinates against the final immutable output item.

use std::collections::BTreeMap;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use serde_json::Value;

use super::ModelTextDelta;

#[derive(Default)]
pub(super) struct TextTracker {
    messages: BTreeMap<usize, Message>,
}

struct Message {
    id: String,
    phase: Option<String>,
    parts: BTreeMap<usize, String>,
    done: bool,
}

fn index(value: &Value, name: &str) -> Result<usize> {
    value[name]
        .as_u64()
        .and_then(|index| usize::try_from(index).ok())
        .filter(|index| *index < 1024)
        .with_context(|| format!("text event {name} missing or out of bounds"))
}

fn identity(value: &Value) -> Result<&str> {
    value
        .as_str()
        .filter(|id| !id.is_empty() && id.len() <= 512)
        .context("text event item identity missing or too long")
}

fn phase(value: &Value) -> Result<Option<String>> {
    match value {
        Value::Null => Ok(None),
        Value::String(value) if matches!(value.as_str(), "commentary" | "final_answer") => {
            Ok(Some(value.clone()))
        }
        _ => bail!("unsupported model message phase"),
    }
}

impl TextTracker {
    pub(super) fn added(&mut self, value: &Value) -> Result<()> {
        let item = &value["item"];
        if item["type"] != "message" || item["role"] != "assistant" {
            return Ok(());
        }
        let output_index = index(value, "output_index")?;
        let id = identity(&item["id"])?;
        let phase = phase(&item["phase"])?;
        if self.messages.contains_key(&output_index) {
            bail!("provider reused an output item index");
        }
        self.messages.insert(
            output_index,
            Message {
                id: id.to_owned(),
                phase,
                parts: BTreeMap::new(),
                done: false,
            },
        );
        Ok(())
    }

    pub(super) fn delta(&mut self, response_id: &str, value: &Value) -> Result<ModelTextDelta> {
        let output_index = index(value, "output_index")?;
        let content_index = index(value, "content_index")?;
        let id = identity(&value["item_id"])?;
        let text = value["delta"].as_str().context("text delta missing")?;
        let advertised_phase = phase(&value["phase"])?;
        let message = self
            .messages
            .entry(output_index)
            .or_insert_with(|| Message {
                id: id.to_owned(),
                phase: advertised_phase.clone(),
                parts: BTreeMap::new(),
                done: false,
            });
        if message.id != id
            || message.done
            || advertised_phase
                .as_ref()
                .zip(message.phase.as_ref())
                .is_some_and(|(advertised, known)| advertised != known)
        {
            bail!("text delta changed the original item identity or phase");
        }
        // An omitted phase is unknown; an explicit phase may refine it once.
        // Later omissions do not erase a phase the provider already declared.
        if message.phase.is_none() {
            message.phase = advertised_phase;
        }
        message
            .parts
            .entry(content_index)
            .or_default()
            .push_str(text);
        Ok(ModelTextDelta {
            response_id: response_id.to_owned(),
            item_id: id.to_owned(),
            output_index,
            content_index,
            text: text.to_owned(),
            phase: message.phase.clone(),
        })
    }

    pub(super) fn done(&mut self, output_index: usize, item: &Value) -> Result<()> {
        let Some(message) = self.messages.get_mut(&output_index) else {
            return Ok(());
        };
        let completed_phase = phase(&item["phase"])?;
        if message.done
            || item["type"] != "message"
            || item["role"] != "assistant"
            || item["id"].as_str() != Some(message.id.as_str())
            || message
                .phase
                .as_ref()
                .is_some_and(|known| completed_phase.as_ref() != Some(known))
        {
            bail!("completed item differs from the streamed message identity or phase");
        }
        let content = item["content"]
            .as_array()
            .context("streamed message content missing")?;
        for (index, text) in &message.parts {
            let part = content
                .get(*index)
                .context("streamed text content index missing at completion")?;
            if part["type"] != "output_text" || part["text"].as_str() != Some(text.as_str()) {
                bail!("completed text differs from the actual streamed text");
            }
        }
        // Keep the provider's completed item unchanged, including its phase.
        // A declared phase must survive completion; an unknown one may refine.
        message.phase = completed_phase;
        message.done = true;
        Ok(())
    }

    pub(super) fn completed(&self) -> Result<()> {
        if self.messages.values().any(|message| !message.done) {
            bail!("model completed before its streamed messages were finalized");
        }
        Ok(())
    }
}
