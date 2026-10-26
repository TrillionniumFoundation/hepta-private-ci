//! Private raw continuation input under the existing exact-body admission.
//!
//! This buffer carries no permission, credentials, provider capability claim or
//! persistent state. The original context owner supplies initial input and tool
//! results, verifies retained receipts, and admits the final encoded request.

use crate::ApiError;
use crate::OpaqueResponsesContinuation;
use crate::RequestedOutputLimit;
use crate::ResponseCaptureError;
use crate::ResponsesApiRequest;
use codex_client::EncodedJsonBody;
use codex_protocol::models::ResponseItem;
use serde::Serialize;
use serde::Serializer;
use serde::ser::SerializeMap;
use serde_json::Value;
use serde_json::value::RawValue;
use std::sync::Arc;

pub struct RawResponsesInput {
    items: Vec<Arc<RawValue>>,
    maximum_items: usize,
    maximum_bytes: usize,
    bytes: usize,
}

impl RawResponsesInput {
    pub fn new(maximum_items: usize, maximum_bytes: usize) -> Self {
        Self {
            items: Vec::new(),
            maximum_items,
            maximum_bytes,
            bytes: 0,
        }
    }

    /// Append context-owner supplied input, including real tool results under
    /// their original call IDs. This does not manufacture or validate authority.
    pub fn append_typed(&mut self, items: &[ResponseItem]) -> Result<(), ResponseCaptureError> {
        if self
            .items
            .len()
            .checked_add(items.len())
            .is_none_or(|count| count > self.maximum_items)
        {
            return Err(ResponseCaptureError::Limit);
        }
        let items = items
            .iter()
            .map(|item| {
                serde_json::value::to_raw_value(item)
                    .map(Arc::from)
                    .map_err(|_| ResponseCaptureError::Invalid)
            })
            .collect::<Result<Vec<_>, _>>()?;
        self.append(items)
    }

    /// Raw bytes are replayable only after the current semantic projection has
    /// accepted them. Unknown schema remains retainable but not executable.
    pub fn append_continuation(
        &mut self,
        continuation: &OpaqueResponsesContinuation,
    ) -> Result<(), ResponseCaptureError> {
        if !continuation.projection_supported() {
            return Err(ResponseCaptureError::Invalid);
        }
        self.append(continuation.items().to_vec())
    }

    fn append(&mut self, items: Vec<Arc<RawValue>>) -> Result<(), ResponseCaptureError> {
        let count = self
            .items
            .len()
            .checked_add(items.len())
            .ok_or(ResponseCaptureError::Limit)?;
        let bytes = items
            .iter()
            .try_fold(self.bytes, |total, item| {
                total.checked_add(item.get().len())
            })
            .ok_or(ResponseCaptureError::Limit)?;
        if self.maximum_items == 0 || count > self.maximum_items || bytes > self.maximum_bytes {
            return Err(ResponseCaptureError::Limit);
        }
        self.items.extend(items);
        self.bytes = bytes;
        Ok(())
    }

    /// Use these exact bytes for the existing owner's admission and body
    /// observer. The typed request must not also contain a competing input.
    pub fn encode_request(
        &self,
        request: &ResponsesApiRequest,
    ) -> Result<EncodedJsonBody, ApiError> {
        self.encode_request_with_limit(request, None)
    }

    pub(crate) fn encode_request_with_limit(
        &self,
        request: &ResponsesApiRequest,
        limit: Option<RequestedOutputLimit>,
    ) -> Result<EncodedJsonBody, ApiError> {
        if !request.input.is_empty() || self.maximum_items == 0 || self.maximum_bytes == 0 {
            return Err(ApiError::Stream(
                "raw Responses input conflicts with typed input or bounds".into(),
            ));
        }
        let mut fields = serde_json::to_value(request)
            .map_err(|_| ApiError::Stream("failed to prepare private Responses request".into()))?;
        let fields = fields
            .as_object_mut()
            .ok_or_else(|| ApiError::Stream("Responses request must be an object".into()))?;
        fields.remove("input");
        if let Some(limit) = limit {
            fields.insert(
                "max_output_tokens".into(),
                serde_json::json!(limit.tokens()),
            );
        }
        struct Prepared<'a> {
            fields: &'a serde_json::Map<String, Value>,
            items: &'a [Arc<RawValue>],
        }
        impl Serialize for Prepared<'_> {
            fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
                let mut map = serializer.serialize_map(Some(self.fields.len() + 1))?;
                for (key, value) in self.fields {
                    map.serialize_entry(key, value)?;
                }
                let items: Vec<&RawValue> = self.items.iter().map(AsRef::as_ref).collect();
                map.serialize_entry("input", &items)?;
                map.end()
            }
        }
        EncodedJsonBody::encode(&Prepared {
            fields,
            items: &self.items,
        })
        .map_err(|_| ApiError::Stream("failed to encode private Responses request".into()))
    }
}

#[cfg(test)]
#[path = "response_input_tests.rs"]
mod tests;
