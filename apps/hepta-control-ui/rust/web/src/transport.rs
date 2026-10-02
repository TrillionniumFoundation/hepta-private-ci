//! Bounded transport contracts and their same-origin browser adapter.
use hepta_control_core::{
    canonical::{
        CanonicalLimits, EmptyText, assert_canonical_text, assert_sha256, assert_stable_identifier,
        canonical_json,
    },
    error::{ControlError, ErrorCode},
};
use serde_json::{Value, json};

#[cfg(target_arch = "wasm32")]
mod browser;
#[cfg(target_arch = "wasm32")]
pub(crate) mod deadline;
#[cfg(target_arch = "wasm32")]
pub use browser::SameOriginHttpTransport;

const MAX_REQUEST_BYTES: usize = 64 * 1024;
const MAX_RESPONSE_BYTES: usize = 1024 * 1024;

fn unsent(error: ControlError) -> ControlError {
    error.with_dispatch(false)
}

fn transport_error(status: u16) -> ControlError {
    ControlError::new(ErrorCode::Transport)
        .with_dispatch(true)
        .detail("status", json!(status))
}

fn too_large(status: u16) -> ControlError {
    transport_error(status).detail("maxBytes", json!(MAX_RESPONSE_BYTES))
}

fn encode_body(body: &Value) -> Result<String, ControlError> {
    canonical_json(
        body,
        &CanonicalLimits {
            max_encoded_bytes: MAX_REQUEST_BYTES,
            ..CanonicalLimits::default()
        },
    )
    .map_err(unsent)
}

fn mutation_body(method: &str, input: &Value) -> Result<Value, ControlError> {
    assert_canonical_text(method, 64, EmptyText::Forbidden).map_err(unsent)?;
    let mut object = input
        .as_object()
        .cloned()
        .ok_or_else(|| unsent(ControlError::invalid()))?;
    if object
        .get("method")
        .is_some_and(|value| value.as_str() != Some(method))
    {
        return Err(unsent(ControlError::invalid()));
    }
    object.insert("method".into(), json!(method));
    Ok(Value::Object(object))
}

fn identifier(value: &Value, field: &str) -> Result<String, ControlError> {
    let text = value
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| unsent(ControlError::invalid()))?;
    assert_stable_identifier(text).map_err(unsent)?;
    Ok(text.to_owned())
}

fn lookup_identity(input: &Value) -> Result<(String, String, u64, String), ControlError> {
    let operation = identifier(input, "operationId")?;
    let session = identifier(input, "sessionId")?;
    let generation = input
        .get("connectionGeneration")
        .and_then(Value::as_u64)
        .filter(|value| (1..=9_007_199_254_740_991).contains(value))
        .ok_or_else(|| unsent(ControlError::invalid()))?;
    let digest = input
        .get("semanticDigest")
        .and_then(Value::as_str)
        .ok_or_else(|| unsent(ControlError::invalid()))?;
    assert_sha256(digest).map_err(unsent)?;
    Ok((operation, session, generation, digest.to_owned()))
}

pub(crate) fn js_whitespace(character: char) -> bool {
    matches!(character, '\u{0009}'..='\u{000d}' | ' ' | '\u{00a0}' | '\u{1680}'
        | '\u{2000}'..='\u{200a}' | '\u{2028}' | '\u{2029}' | '\u{202f}'
        | '\u{205f}' | '\u{3000}' | '\u{feff}')
}

fn validate_headers(
    content_type: &str,
    content_length: Option<&str>,
    status: u16,
) -> Result<(), ControlError> {
    // Match the JS application's application/(vendor+)?json media-type profile.
    let media = match content_type.split_once(';') {
        Some((media, _)) => media.trim_end_matches(js_whitespace),
        None => content_type,
    }
    .to_ascii_lowercase();
    let Some(subtype) = media.strip_prefix("application/") else {
        return Err(transport_error(status));
    };
    let valid = subtype == "json"
        || subtype.strip_suffix("+json").is_some_and(|prefix| {
            !prefix.is_empty()
                && prefix
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b".+-".contains(&b))
        });
    if !valid {
        return Err(transport_error(status));
    }
    if let Some(length) = content_length {
        let length = length.trim_matches(js_whitespace);
        if length.is_empty()
            || !length.bytes().all(|b| b.is_ascii_digit())
            || (length.len() > 1 && length.starts_with('0'))
        {
            return Err(transport_error(status));
        }
        let length = length.parse::<u64>().map_err(|_| transport_error(status))?;
        if length > 9_007_199_254_740_991 {
            return Err(transport_error(status));
        }
        if length > MAX_RESPONSE_BYTES as u64 {
            return Err(too_large(status));
        }
    }
    Ok(())
}

fn classify_http(status: u16, payload: &Value) -> ControlError {
    let backend_code = payload
        .get("errorCode")
        .and_then(Value::as_str)
        .filter(|value| assert_stable_identifier(value).is_ok());
    let (code, retryable) = match status {
        401 => (ErrorCode::SessionExpired, true),
        403 => (ErrorCode::PermissionDenied, false),
        409 => (ErrorCode::OperationConflict, true),
        412 => (ErrorCode::StaleRevision, true),
        400 | 404 | 422 => (ErrorCode::BackendRejected, false),
        _ => (ErrorCode::Transport, status >= 429),
    };
    ControlError::new(code)
        .retryable(retryable)
        .with_dispatch(true)
        .detail("status", json!(status))
        .detail("backendCode", json!(backend_code))
}

fn parse_response(bytes: &[u8], status: u16) -> Result<Value, ControlError> {
    if bytes.len() > MAX_RESPONSE_BYTES {
        return Err(too_large(status));
    }
    let text = std::str::from_utf8(bytes).map_err(|_| transport_error(status))?;
    // TextDecoder's default ignoreBOM=false strips a leading UTF-8 BOM.
    let text = text.strip_prefix('\u{feff}').unwrap_or(text);
    let payload = if text.is_empty() {
        Value::Null
    } else {
        serde_json::from_str(text).map_err(|_| transport_error(status))?
    };
    if !(200..300).contains(&status) {
        return Err(classify_http(status, &payload));
    }
    if !payload.is_object() {
        return Err(transport_error(status));
    }
    Ok(payload)
}

fn mutation_outcome(error: ControlError, operation_id: &str) -> ControlError {
    if error.request_dispatched == Some(false)
        || matches!(
            error.code,
            ErrorCode::InvalidInput
                | ErrorCode::BackendRejected
                | ErrorCode::OperationConflict
                | ErrorCode::StaleRevision
                | ErrorCode::SessionExpired
                | ErrorCode::PermissionDenied
                | ErrorCode::AmbiguousSubmission
        )
    {
        error
    } else {
        ControlError::new(ErrorCode::AmbiguousSubmission)
            .retryable(true)
            .with_dispatch(true)
            .detail("operationId", json!(operation_id))
    }
}

/// Strict incremental UTF-8 validation without allocating past the response limit.
#[derive(Default)]
struct ResponseBytes {
    bytes: Vec<u8>,
    validated: usize,
}
impl ResponseBytes {
    fn append(&mut self, chunk: &[u8], status: u16) -> Result<(), ControlError> {
        if chunk.len() > MAX_RESPONSE_BYTES - self.bytes.len() {
            return Err(too_large(status));
        }
        self.bytes.extend_from_slice(chunk);
        match std::str::from_utf8(&self.bytes[self.validated..]) {
            Ok(_) => self.validated = self.bytes.len(),
            Err(error) if error.error_len().is_none() => self.validated += error.valid_up_to(),
            Err(_) => return Err(transport_error(status)),
        }
        Ok(())
    }
    fn finish(self, status: u16) -> Result<Vec<u8>, ControlError> {
        if self.validated != self.bytes.len() {
            return Err(transport_error(status));
        }
        Ok(self.bytes)
    }
}

#[cfg(test)]
#[path = "transport/contract_tests.rs"]
mod tests;
