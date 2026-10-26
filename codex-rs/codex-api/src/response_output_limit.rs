//! An explicitly requested provider output-token limit, not a support claim.

use crate::ApiError;
use crate::RawResponsesInput;
use crate::ResponsesApiRequest;
use codex_client::EncodedJsonBody;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RequestedOutputLimit(u64);

impl RequestedOutputLimit {
    /// The public Responses schema documents a minimum of 16. A separate
    /// backend may reject this parameter; callers must never drop it and retry.
    pub fn new(tokens: u64) -> Result<Self, ApiError> {
        if tokens < 16 {
            return Err(ApiError::Stream(
                "requested output-token limit must be at least 16".into(),
            ));
        }
        Ok(Self(tokens))
    }

    pub fn tokens(self) -> u64 {
        self.0
    }
}

/// Return the exact body the original owner must admit and observe. Merely
/// serializing this field does not establish that a backend enforces it.
pub fn encode_request_with_requested_output_limit(
    request: &ResponsesApiRequest,
    raw_input: Option<&RawResponsesInput>,
    limit: RequestedOutputLimit,
) -> Result<EncodedJsonBody, ApiError> {
    if let Some(input) = raw_input {
        return input.encode_request_with_limit(request, Some(limit));
    }
    let mut body = serde_json::to_value(request)
        .map_err(|_| ApiError::Stream("failed to prepare bounded Responses request".into()))?;
    body["max_output_tokens"] = serde_json::json!(limit.tokens());
    EncodedJsonBody::encode(&body)
        .map_err(|_| ApiError::Stream("failed to encode bounded Responses request".into()))
}

#[cfg(test)]
#[path = "response_output_limit_tests.rs"]
mod tests;
