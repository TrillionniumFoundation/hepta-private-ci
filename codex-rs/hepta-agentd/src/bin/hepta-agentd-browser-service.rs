//! Long-lived Agentd-owned product service for `browser.servo`.
//!
//! The service owns one persistent Browser control for the Agentd generation,
//! accepts only canonical digest-bound length-prefixed JSON over inherited
//! stdin/stdout, keeps the live revocation feed active, and never exposes a
//! discovery, TCP, UDS, WebDriver, or CDP listener. A semantic call is executed
//! at most once; an indeterminate result is returned for explicit reconciliation.

use std::io::{self, Read, Write};
use std::path::Path;

use codex_hepta_contracts::{FinalUseBinding, SignedFinalUseGrant};
use serde::Deserialize;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

// These source modules are intentionally owned by the named persistent binary
// instead of replacing the legacy Agentd Browser library port. Their internal
// qualification helpers are exercised by this binary's test harness.
#[allow(dead_code)]
#[path = "../browser_revocation_feed.rs"]
mod browser_revocation_feed;
#[allow(dead_code)]
#[path = "../browser_servo_persistent.rs"]
mod browser_servo;

use browser_servo::{
    BrowserFinalUseInvocation, BrowserServoCall, BrowserServoMethod,
    open_browser_servo_port_from_file,
};

const SERVICE_SCHEMA: &str = "hepta.browser.agentd-service-frame.v1";
const SERVICE_PROTOCOL_VERSION: u64 = 1;
const MAX_FRAME_BYTES: usize = 1_048_576;
const MAX_ERROR_CHARS: usize = 512;
const MAX_JSON_DEPTH: usize = 32;
const JS_SAFE_INTEGER: u64 = 9_007_199_254_740_991;

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ServiceMethod {
    OpenProfile,
    AdmitEffectGrant,
    ObservePage,
    NavigateOrAct,
    ReconcileOperation,
    ReconcilePersistedOperation,
    CloseProfile,
}

impl ServiceMethod {
    fn module_method(self) -> BrowserServoMethod {
        match self {
            Self::OpenProfile => BrowserServoMethod::OpenProfile,
            Self::AdmitEffectGrant => BrowserServoMethod::AdmitEffectGrant,
            Self::ObservePage => BrowserServoMethod::ObservePage,
            Self::NavigateOrAct => BrowserServoMethod::NavigateOrAct,
            Self::ReconcileOperation => BrowserServoMethod::ReconcileOperation,
            Self::ReconcilePersistedOperation => BrowserServoMethod::ReconcilePersistedOperation,
            Self::CloseProfile => BrowserServoMethod::CloseProfile,
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct ServiceCallPayload {
    method: ServiceMethod,
    input: Value,
    signed_grant: Option<SignedFinalUseGrant>,
    binding: Option<FinalUseBinding>,
}

#[derive(Debug)]
struct DecodedFrame {
    sequence: u64,
    request_id: String,
    payload: Value,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let config_path = args.next().ok_or(
        "usage: hepta-agentd-browser-service BROWSER_HOST_CONFIG.json",
    )?;
    if args.next().is_some() {
        return Err(
            "usage: hepta-agentd-browser-service BROWSER_HOST_CONFIG.json".into(),
        );
    }

    let owner = open_browser_servo_port_from_file(Path::new(&config_path))?;
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut input = stdin.lock();
    let mut output = stdout.lock();
    let mut expected_incoming_sequence = 1_u64;
    let mut next_outgoing_sequence = 1_u64;

    while let Some(body) = read_frame(&mut input)? {
        let frame = decode_request_frame(&body, expected_incoming_sequence)?;
        expected_incoming_sequence = expected_incoming_sequence
            .checked_add(1)
            .ok_or("Browser service input sequence exhausted")?;
        let request_id = frame.request_id.clone();
        let response_payload = match serde_json::from_value::<ServiceCallPayload>(frame.payload) {
            Ok(call) => execute_call(&owner, call),
            Err(error) => json!({
                "requestSequence": frame.sequence,
                "ok": false,
                "error": bounded_error(format!("invalid Browser service request: {error}")),
            }),
        };
        let response = build_response_frame(
            next_outgoing_sequence,
            &request_id,
            response_payload,
        )?;
        next_outgoing_sequence = next_outgoing_sequence
            .checked_add(1)
            .ok_or("Browser service output sequence exhausted")?;
        write_frame(&mut output, &response)?;
    }

    Ok(())
}

fn execute_call(
    owner: &browser_servo::PersistentBrowserServoControl,
    call: ServiceCallPayload,
) -> Value {
    let method = call.method.module_method();
    let request = if matches!(method, BrowserServoMethod::NavigateOrAct) {
        match (call.signed_grant, call.binding) {
            (Some(signed_grant), Some(binding)) => BrowserServoCall::effect(
                call.input,
                BrowserFinalUseInvocation {
                    signed_grant,
                    binding,
                },
            ),
            _ => Err(browser_servo::BrowserServoError::Invalid(
                "navigate_or_act requires signed final-use grant and exact binding".into(),
            )),
        }
    } else if call.signed_grant.is_some() || call.binding.is_some() {
        Err(browser_servo::BrowserServoError::Invalid(
            "non-effect Browser calls must not carry final-use authority".into(),
        ))
    } else {
        BrowserServoCall::read(method, call.input)
    };

    match request.and_then(|request| owner.call(request)) {
        Ok(result) => json!({
            "requestSequence": 0,
            "ok": true,
            "result": result,
        }),
        Err(error) => json!({
            "requestSequence": 0,
            "ok": false,
            "error": bounded_error(error.to_string()),
        }),
    }
}

fn decode_request_frame(
    body: &[u8],
    expected_sequence: u64,
) -> Result<DecodedFrame, Box<dyn std::error::Error>> {
    let text = std::str::from_utf8(body)?;
    let value: Value = serde_json::from_str(text)?;
    validate_safe_json(&value, 0)?;
    if canonical_json(&value)? != text {
        return Err("Browser service request is not canonical JSON".into());
    }
    let object = require_object(&value, "Browser service frame")?;
    let expected = [
        "kind",
        "payload",
        "payloadDigest",
        "protocolVersion",
        "requestId",
        "schema",
        "sequence",
    ];
    if object.len() != expected.len() || expected.iter().any(|key| !object.contains_key(*key)) {
        return Err("Browser service frame contains missing or unknown fields".into());
    }
    if object.get("schema").and_then(Value::as_str) != Some(SERVICE_SCHEMA)
        || positive_u64(object.get("protocolVersion"), "protocolVersion")?
            != SERVICE_PROTOCOL_VERSION
        || object.get("kind").and_then(Value::as_str) != Some("request")
    {
        return Err("Browser service frame protocol/kind is unsupported".into());
    }
    let sequence = positive_u64(object.get("sequence"), "sequence")?;
    if sequence != expected_sequence {
        return Err("Browser service input sequence is not monotonic".into());
    }
    let request_id = object
        .get("requestId")
        .and_then(Value::as_str)
        .ok_or("Browser service requestId is missing")?;
    validate_request_id(request_id)?;
    let payload = object
        .get("payload")
        .cloned()
        .ok_or("Browser service payload is missing")?;
    require_object(&payload, "Browser service payload")?;
    let payload_digest = object
        .get("payloadDigest")
        .and_then(Value::as_str)
        .ok_or("Browser service payloadDigest is missing")?;
    if payload_digest != sha256_hex(canonical_json(&payload)?.as_bytes()) {
        return Err("Browser service payload digest mismatch".into());
    }
    Ok(DecodedFrame {
        sequence,
        request_id: request_id.to_string(),
        payload,
    })
}

fn build_response_frame(
    sequence: u64,
    request_id: &str,
    mut payload: Value,
) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    validate_request_id(request_id)?;
    let object = payload
        .as_object_mut()
        .ok_or("Browser service response payload must be an object")?;
    // execute_call cannot know the parent frame sequence. Bind it here and
    // reject an internal attempt to smuggle another request sequence.
    let request_sequence = object
        .get("requestSequence")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    if request_sequence != 0 {
        return Err("Browser service internal response sequence was already set".into());
    }
    object.insert("requestSequence".to_string(), Value::from(sequence));
    let payload_json = canonical_json(&payload)?;
    let frame = json!({
        "schema": SERVICE_SCHEMA,
        "protocolVersion": SERVICE_PROTOCOL_VERSION,
        "sequence": sequence,
        "kind": "response",
        "requestId": request_id,
        "payloadDigest": sha256_hex(payload_json.as_bytes()),
        "payload": payload,
    });
    let rendered = canonical_json(&frame)?.into_bytes();
    if rendered.is_empty() || rendered.len() > MAX_FRAME_BYTES {
        return Err("Browser service response exceeds the hard bound".into());
    }
    Ok(rendered)
}

fn validate_request_id(value: &str) -> Result<(), Box<dyn std::error::Error>> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err("requestId must be a bounded stable identifier".into());
    }
    Ok(())
}

fn read_frame(input: &mut impl Read) -> Result<Option<Vec<u8>>, Box<dyn std::error::Error>> {
    let mut prefix = [0_u8; 4];
    let mut read = 0;
    while read < prefix.len() {
        match input.read(&mut prefix[read..])? {
            0 if read == 0 => return Ok(None),
            0 => return Err("Browser service input ended with a partial frame prefix".into()),
            count => read += count,
        }
    }
    let length = u32::from_be_bytes(prefix) as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err("Browser service frame length is outside the hard bound".into());
    }
    let mut body = vec![0_u8; length];
    input.read_exact(&mut body)?;
    Ok(Some(body))
}

fn write_frame(
    output: &mut impl Write,
    body: &[u8],
) -> Result<(), Box<dyn std::error::Error>> {
    if body.is_empty() || body.len() > MAX_FRAME_BYTES {
        return Err("Browser service output frame exceeds the hard bound".into());
    }
    output.write_all(&(body.len() as u32).to_be_bytes())?;
    output.write_all(body)?;
    output.flush()?;
    Ok(())
}

fn require_object<'a>(
    value: &'a Value,
    name: &str,
) -> Result<&'a Map<String, Value>, Box<dyn std::error::Error>> {
    value
        .as_object()
        .ok_or_else(|| format!("{name} must be an object").into())
}

fn positive_u64(
    value: Option<&Value>,
    name: &str,
) -> Result<u64, Box<dyn std::error::Error>> {
    value
        .and_then(Value::as_u64)
        .filter(|value| *value > 0 && *value <= JS_SAFE_INTEGER)
        .ok_or_else(|| format!("{name} must be a positive JavaScript-safe integer").into())
}

fn validate_safe_json(value: &Value, depth: usize) -> Result<(), Box<dyn std::error::Error>> {
    if depth > MAX_JSON_DEPTH {
        return Err("Browser service JSON nesting exceeds the hard bound".into());
    }
    match value {
        Value::Null | Value::Bool(_) | Value::String(_) => Ok(()),
        Value::Number(number) => {
            let safe = number
                .as_u64()
                .is_some_and(|value| value <= JS_SAFE_INTEGER)
                || number
                    .as_i64()
                    .is_some_and(|value| value.unsigned_abs() <= JS_SAFE_INTEGER);
            if safe {
                Ok(())
            } else {
                Err("Browser service JSON numbers must be JavaScript-safe integers".into())
            }
        }
        Value::Array(values) => values
            .iter()
            .try_for_each(|value| validate_safe_json(value, depth + 1)),
        Value::Object(object) => object
            .values()
            .try_for_each(|value| validate_safe_json(value, depth + 1)),
    }
}

fn canonical_json(value: &Value) -> Result<String, Box<dyn std::error::Error>> {
    let mut output = String::new();
    write_canonical(value, 0, &mut output)?;
    if output.len() > MAX_FRAME_BYTES {
        return Err("canonical Browser service JSON exceeds the hard bound".into());
    }
    Ok(output)
}

fn write_canonical(
    value: &Value,
    depth: usize,
    output: &mut String,
) -> Result<(), Box<dyn std::error::Error>> {
    if depth > MAX_JSON_DEPTH {
        return Err("Browser service JSON nesting exceeds the hard bound".into());
    }
    match value {
        Value::Null => output.push_str("null"),
        Value::Bool(value) => output.push_str(if *value { "true" } else { "false" }),
        Value::String(value) => output.push_str(&serde_json::to_string(value)?),
        Value::Number(number) => {
            validate_safe_json(value, depth)?;
            output.push_str(&number.to_string());
        }
        Value::Array(values) => {
            output.push('[');
            for (index, value) in values.iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                write_canonical(value, depth + 1, output)?;
            }
            output.push(']');
        }
        Value::Object(object) => {
            output.push('{');
            let mut keys = object.keys().collect::<Vec<_>>();
            keys.sort();
            for (index, key) in keys.into_iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                output.push_str(&serde_json::to_string(key)?);
                output.push(':');
                write_canonical(&object[key], depth + 1, output)?;
            }
            output.push('}');
        }
    }
    Ok(())
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(output, "{byte:02x}");
    }
    output
}

fn bounded_error(value: impl AsRef<str>) -> String {
    value.as_ref().chars().take(MAX_ERROR_CHARS).collect()
}

#[cfg(test)]
mod service_protocol_tests {
    use super::*;
    use std::io::Cursor;

    fn valid_payload() -> Value {
        json!({
            "method": "observe_page",
            "input": {"profileId": "profile.1"},
            "signedGrant": null,
            "binding": null,
        })
    }

    fn request_frame(sequence: u64, payload: Value) -> Vec<u8> {
        let payload_json = canonical_json(&payload).unwrap();
        canonical_json(&json!({
            "schema": SERVICE_SCHEMA,
            "protocolVersion": SERVICE_PROTOCOL_VERSION,
            "sequence": sequence,
            "kind": "request",
            "requestId": "request.1",
            "payloadDigest": sha256_hex(payload_json.as_bytes()),
            "payload": payload,
        }))
        .unwrap()
        .into_bytes()
    }

    #[test]
    fn accepts_exact_canonical_digest_bound_request() {
        let body = request_frame(1, valid_payload());
        let decoded = decode_request_frame(&body, 1).unwrap();
        assert_eq!(decoded.sequence, 1);
        assert_eq!(decoded.request_id, "request.1");
        let call: ServiceCallPayload = serde_json::from_value(decoded.payload).unwrap();
        assert!(matches!(call.method, ServiceMethod::ObservePage));
    }

    #[test]
    fn rejects_noncanonical_request_json() {
        let body = request_frame(1, valid_payload());
        let value: Value = serde_json::from_slice(&body).unwrap();
        let noncanonical = serde_json::to_vec_pretty(&value).unwrap();
        assert!(decode_request_frame(&noncanonical, 1)
            .unwrap_err()
            .to_string()
            .contains("not canonical"));
    }

    #[test]
    fn rejects_payload_digest_drift() {
        let body = request_frame(1, valid_payload());
        let mut value: Value = serde_json::from_slice(&body).unwrap();
        value["payloadDigest"] = Value::String("0".repeat(64));
        let drifted = canonical_json(&value).unwrap().into_bytes();
        assert!(decode_request_frame(&drifted, 1)
            .unwrap_err()
            .to_string()
            .contains("payload digest mismatch"));
    }

    #[test]
    fn rejects_sequence_drift_and_unknown_fields() {
        let body = request_frame(2, valid_payload());
        assert!(decode_request_frame(&body, 1)
            .unwrap_err()
            .to_string()
            .contains("not monotonic"));

        let body = request_frame(1, valid_payload());
        let mut value: Value = serde_json::from_slice(&body).unwrap();
        value["extra"] = Value::Bool(true);
        let unknown = canonical_json(&value).unwrap().into_bytes();
        assert!(decode_request_frame(&unknown, 1)
            .unwrap_err()
            .to_string()
            .contains("missing or unknown fields"));
    }

    #[test]
    fn rejects_partial_length_prefixed_frame() {
        let body = request_frame(1, valid_payload());
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&(body.len() as u32).to_be_bytes());
        bytes.extend_from_slice(&body[..body.len() - 1]);
        let mut cursor = Cursor::new(bytes);
        assert!(read_frame(&mut cursor).is_err());
    }

    #[test]
    fn response_is_canonical_and_binds_request_sequence() {
        let body = build_response_frame(
            7,
            "request.7",
            json!({"requestSequence": 0, "ok": true, "result": {"kind": "ok"}}),
        )
        .unwrap();
        let text = std::str::from_utf8(&body).unwrap();
        let value: Value = serde_json::from_str(text).unwrap();
        assert_eq!(canonical_json(&value).unwrap(), text);
        assert_eq!(value["payload"]["requestSequence"], 7);
        let digest = sha256_hex(canonical_json(&value["payload"]).unwrap().as_bytes());
        assert_eq!(value["payloadDigest"], digest);
    }
}
