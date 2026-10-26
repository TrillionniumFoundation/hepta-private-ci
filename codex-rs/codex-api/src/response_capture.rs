//! Bounded opaque output-item/terminal JSON captured before typed projection.
//!
//! This is an ephemeral transport buffer, never an authorization or persistence
//! owner. Only the caller's original continuation owner may retain its private
//! bytes. Neither captured type implements Debug or Serialize. SSE framing and
//! known transient deltas are outside this completed-continuation scope.

use crate::OpaqueResponsesIncomplete;
use codex_protocol::models::ResponseItem;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::value::RawValue;
use std::sync::Arc;
use std::sync::Mutex;

#[path = "response_capture_json.rs"]
mod strict_json;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResponseCaptureError {
    Limit,
    Invalid,
    Incomplete,
    Binding,
    Unavailable,
}

pub struct ResponseCapture {
    maximum_items: usize,
    maximum_bytes: usize,
    state: Mutex<State>,
}

#[derive(Default)]
struct State {
    events: Vec<Arc<RawValue>>,
    items: Vec<Arc<RawValue>>,
    terminal: Option<Arc<RawValue>>,
    terminal_is_incomplete: bool,
    retained_bytes: usize,
    unknown_event: bool,
    invalid: bool,
}

#[derive(Deserialize)]
struct Envelope<'a> {
    #[serde(rename = "type")]
    kind: String,
    #[serde(borrow)]
    item: Option<&'a RawValue>,
    #[serde(borrow)]
    response: Option<&'a RawValue>,
}

pub struct OpaqueResponsesContinuation {
    events: Vec<Arc<RawValue>>,
    items: Vec<Arc<RawValue>>,
    projection_supported: bool,
}

impl ResponseCapture {
    /// Bounds are checked before parsing/copying each complete SSE JSON event.
    /// They do not replace transport/SSE decoder download or event-size bounds.
    pub fn new(maximum_items: usize, maximum_bytes: usize) -> Self {
        Self {
            maximum_items,
            maximum_bytes,
            state: Mutex::new(State {
                // Include the private evidence wrapper in the JSON byte bound.
                retained_bytes: 128,
                ..State::default()
            }),
        }
    }

    pub(crate) fn observe(&self, encoded: &str) -> Result<(), ResponseCaptureError> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| ResponseCaptureError::Unavailable)?;
        let result = self.observe_into(&mut state, encoded);
        if result.is_err() {
            state.invalid = true;
        }
        result
    }

    fn observe_into(&self, state: &mut State, encoded: &str) -> Result<(), ResponseCaptureError> {
        if state.invalid || state.terminal.is_some() {
            return Err(ResponseCaptureError::Invalid);
        }
        if self.maximum_items == 0 || encoded.len() > self.maximum_bytes {
            return Err(ResponseCaptureError::Limit);
        }
        // Duplicate keys are ambiguous even if the normal Value parser would
        // silently retain only the final occurrence. Never project them.
        let parsed = strict_json::parse(encoded).map_err(|_| ResponseCaptureError::Invalid)?;
        let event: Envelope<'_> =
            serde_json::from_str(encoded).map_err(|_| ResponseCaptureError::Invalid)?;
        if matches!(
            event.kind.as_str(),
            "response.output_item.done" | "response.completed" | "response.incomplete"
        ) {
            let known = |key: &str| match event.kind.as_str() {
                "response.output_item.done" => {
                    matches!(key, "type" | "item" | "output_index" | "sequence_number")
                }
                _ => matches!(key, "type" | "response" | "sequence_number"),
            };
            state.unknown_event |= parsed
                .as_object()
                .is_some_and(|fields| fields.keys().any(|key| !known(key)));
        }
        let retain = match event.kind.as_str() {
            "response.output_item.done" => {
                let item = event.item.ok_or(ResponseCaptureError::Invalid)?;
                if state.items.len() >= self.maximum_items {
                    return Err(ResponseCaptureError::Limit);
                }
                state.retained_bytes = state
                    .retained_bytes
                    .checked_add(item.get().len())
                    .ok_or(ResponseCaptureError::Limit)?;
                if state.retained_bytes > self.maximum_bytes {
                    return Err(ResponseCaptureError::Limit);
                }
                state.items.push(Arc::from(item.to_owned()));
                true
            }
            "response.completed" | "response.incomplete" => {
                let response = event.response.ok_or(ResponseCaptureError::Invalid)?;
                state.retained_bytes = state
                    .retained_bytes
                    .checked_add(response.get().len())
                    .ok_or(ResponseCaptureError::Limit)?;
                if state.retained_bytes > self.maximum_bytes {
                    return Err(ResponseCaptureError::Limit);
                }
                state.terminal = Some(Arc::from(response.to_owned()));
                state.terminal_is_incomplete = event.kind == "response.incomplete";
                true
            }
            "response.created"
            | "response.in_progress"
            | "response.output_item.added"
            | "response.output_text.delta"
            | "response.output_text.done"
            | "response.content_part.added"
            | "response.content_part.done"
            | "response.function_call_arguments.delta"
            | "response.function_call_arguments.done"
            | "response.custom_tool_call_input.delta"
            | "response.custom_tool_call_input.done"
            | "response.reasoning_summary_text.delta"
            | "response.reasoning_summary_text.done"
            | "response.reasoning_summary_part.added"
            | "response.reasoning_summary_part.done"
            | "response.reasoning_text.delta"
            | "response.reasoning_text.done"
            | "response.metadata"
            | "codex.response.metadata"
            | "responsesapi.websocket_timing" => false,
            _ => {
                state.unknown_event = true;
                true
            }
        };
        if retain {
            if state.events.len() >= self.maximum_items.saturating_mul(16).saturating_add(8) {
                return Err(ResponseCaptureError::Limit);
            }
            state.retained_bytes = state
                .retained_bytes
                .checked_add(encoded.len())
                .and_then(|bytes| bytes.checked_add(1))
                .ok_or(ResponseCaptureError::Limit)?;
            if state.retained_bytes > self.maximum_bytes {
                return Err(ResponseCaptureError::Limit);
            }
            let raw = RawValue::from_string(encoded.to_owned())
                .map_err(|_| ResponseCaptureError::Invalid)?;
            state.events.push(Arc::from(raw));
        }
        Ok(())
    }

    /// Restore only bytes whose digest and admitted binding the original owner
    /// has already verified. This parser does not authenticate a receipt.
    pub fn restore_private_evidence(
        encoded: &[u8],
        maximum_items: usize,
        maximum_bytes: usize,
        response_id: &str,
        typed_items: &[ResponseItem],
    ) -> Result<OpaqueResponsesContinuation, ResponseCaptureError> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Evidence<'a> {
            schema: &'a str,
            #[serde(borrow)]
            events: Vec<&'a RawValue>,
        }
        if encoded.len() > maximum_bytes {
            return Err(ResponseCaptureError::Limit);
        }
        let encoded = std::str::from_utf8(encoded).map_err(|_| ResponseCaptureError::Invalid)?;
        strict_json::parse(encoded).map_err(|_| ResponseCaptureError::Invalid)?;
        let evidence: Evidence<'_> =
            serde_json::from_str(encoded).map_err(|_| ResponseCaptureError::Invalid)?;
        if evidence.schema != "responses-opaque-continuation:v1" {
            return Err(ResponseCaptureError::Invalid);
        }
        let capture = Self::new(maximum_items, maximum_bytes);
        for event in evidence.events {
            capture.observe(event.get())?;
        }
        capture.completed(response_id, typed_items)
    }

    /// Incomplete provider termination is retained separately and cannot be
    /// restored or serialized as a completed/replayable continuation.
    pub fn incomplete(&self) -> Result<Option<OpaqueResponsesIncomplete>, ResponseCaptureError> {
        let state = self
            .state
            .lock()
            .map_err(|_| ResponseCaptureError::Unavailable)?;
        if state.invalid {
            return Err(ResponseCaptureError::Invalid);
        }
        if !state.terminal_is_incomplete {
            return Ok(None);
        }
        let terminal = state
            .terminal
            .as_ref()
            .ok_or(ResponseCaptureError::Incomplete)?;
        OpaqueResponsesIncomplete::from_capture(state.events.clone(), terminal).map(Some)
    }

    /// Bind the capture to the terminal and complete typed output observed by
    /// this same stream. Unknown item fields remain present, but cannot make
    /// the projection executable until their semantics are reviewed.
    pub fn completed(
        &self,
        response_id: &str,
        typed_items: &[ResponseItem],
    ) -> Result<OpaqueResponsesContinuation, ResponseCaptureError> {
        let state = self
            .state
            .lock()
            .map_err(|_| ResponseCaptureError::Unavailable)?;
        if state.invalid {
            return Err(ResponseCaptureError::Invalid);
        }
        if state.terminal_is_incomplete {
            return Err(ResponseCaptureError::Incomplete);
        }
        let terminal = state
            .terminal
            .as_ref()
            .ok_or(ResponseCaptureError::Incomplete)?;
        let terminal: Value =
            serde_json::from_str(terminal.get()).map_err(|_| ResponseCaptureError::Invalid)?;
        let typed_items = typed_items
            .iter()
            .map(strict_json::typed_evidence)
            .collect::<Result<Vec<_>, _>>()
            .map_err(|_| ResponseCaptureError::Binding)?;
        if terminal["id"].as_str() != Some(response_id) || typed_items.len() != state.items.len() {
            return Err(ResponseCaptureError::Binding);
        }
        let raw_items: Vec<Value> = state
            .items
            .iter()
            .map(|item| serde_json::from_str(item.get()))
            .collect::<Result<_, _>>()
            .map_err(|_| ResponseCaptureError::Invalid)?;
        if let Some(output) = terminal.get("output")
            && output != &Value::Array(raw_items.clone())
        {
            return Err(ResponseCaptureError::Binding);
        }
        if terminal
            .get("status")
            .is_some_and(|value| value != "completed")
            || terminal.get("error").is_some_and(|value| !value.is_null())
            || terminal
                .get("incomplete_details")
                .is_some_and(|value| !value.is_null())
        {
            return Err(ResponseCaptureError::Binding);
        }
        let projection_supported = !state.unknown_event
            && raw_items
                .iter()
                .zip(&typed_items)
                .all(|(raw, typed)| strict_json::covered(raw, typed));
        Ok(OpaqueResponsesContinuation {
            events: state.events.clone(),
            items: state.items.clone(),
            projection_supported,
        })
    }
}

impl OpaqueResponsesContinuation {
    pub fn projection_supported(&self) -> bool {
        self.projection_supported
    }
    pub fn item_count(&self) -> usize {
        self.items.len()
    }
    pub(crate) fn items(&self) -> &[Arc<RawValue>] {
        &self.items
    }

    /// Private original-owner storage only. Contains opaque/encrypted and
    /// possibly sensitive provider data; never display it in logs or reports.
    pub fn private_evidence_json(&self) -> Result<Vec<u8>, ResponseCaptureError> {
        #[derive(Serialize)]
        struct Evidence<'a> {
            schema: &'static str,
            events: Vec<&'a RawValue>,
        }
        serde_json::to_vec(&Evidence {
            schema: "responses-opaque-continuation:v1",
            events: self.events.iter().map(AsRef::as_ref).collect(),
        })
        .map_err(|_| ResponseCaptureError::Invalid)
    }

    /// Exact completed item JSON, including fields omitted by request-oriented
    /// typed serializers. This is not permission to resend an unknown schema.
    pub fn private_output_items_json(&self) -> Result<Vec<u8>, ResponseCaptureError> {
        serde_json::to_vec(
            &self
                .items
                .iter()
                .map(AsRef::as_ref)
                .collect::<Vec<&RawValue>>(),
        )
        .map_err(|_| ResponseCaptureError::Invalid)
    }
}

#[cfg(test)]
#[path = "response_capture_tests.rs"]
mod tests;
