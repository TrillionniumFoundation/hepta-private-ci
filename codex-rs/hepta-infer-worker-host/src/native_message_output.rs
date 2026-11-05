//! Bounded text from the canonical App Server message-item lifecycle.
//!
//! Complete items also occur without any text delta. Their text replaces that
//! item's partial stream, while distinct item IDs retain distinct output.

use super::MAX_OUTPUT_BYTES;

struct AgentMessage {
    id: String,
    text: String,
    completed: bool,
}

#[derive(Default)]
pub(super) struct NativeMessageOutput {
    messages: Vec<AgentMessage>,
    output_bytes: usize,
    metadata_bytes: usize,
}

impl NativeMessageOutput {
    pub(super) fn start(&mut self, id: &str) -> Result<(), String> {
        self.ensure_message(id)?;
        Ok(())
    }

    pub(super) fn append(
        &mut self,
        id: &str,
        delta: &str,
        output: &mut String,
    ) -> Result<(), String> {
        if delta.len() > MAX_OUTPUT_BYTES.saturating_sub(self.output_bytes) {
            return Err("output byte limit exceeded".to_string());
        }
        let index = self.ensure_message(id)?;
        if self.messages[index].completed {
            return Err("agent message delta followed completion".to_string());
        }
        self.messages[index].text.push_str(delta);
        self.output_bytes += delta.len();
        if index + 1 == self.messages.len() {
            output.push_str(delta);
        } else {
            self.render(output);
        }
        Ok(())
    }

    pub(super) fn complete(
        &mut self,
        id: &str,
        text: &str,
        output: &mut String,
    ) -> Result<(), String> {
        let existing = self.messages.iter().position(|message| message.id == id);
        if let Some(index) = existing
            && self.messages[index].completed
        {
            return if self.messages[index].text == text {
                Ok(())
            } else {
                Err("agent message completion changed".to_string())
            };
        }
        let previous_bytes = existing.map_or(0, |index| self.messages[index].text.len());
        let other_bytes = self.output_bytes - previous_bytes;
        if text.len() > MAX_OUTPUT_BYTES.saturating_sub(other_bytes) {
            return Err("output byte limit exceeded".to_string());
        }
        let index = self.ensure_message(id)?;
        self.messages[index].text = text.to_string();
        self.messages[index].completed = true;
        self.output_bytes = other_bytes + text.len();
        self.render(output);
        Ok(())
    }

    fn ensure_message(&mut self, id: &str) -> Result<usize, String> {
        if let Some(index) = self.messages.iter().position(|message| message.id == id) {
            return Ok(index);
        }
        // Empty messages must not bypass the output cap by retaining unlimited
        // item identities. Account for both each entry and its owned ID bytes.
        let bytes = size_of::<AgentMessage>().saturating_add(id.len());
        if bytes > MAX_OUTPUT_BYTES.saturating_sub(self.metadata_bytes) {
            return Err("output item metadata limit exceeded".to_string());
        }
        self.metadata_bytes += bytes;
        self.messages.push(AgentMessage {
            id: id.to_string(),
            text: String::new(),
            completed: false,
        });
        Ok(self.messages.len() - 1)
    }

    fn render(&self, output: &mut String) {
        output.clear();
        output.reserve(self.output_bytes);
        for message in &self.messages {
            output.push_str(&message.text);
        }
    }
}

