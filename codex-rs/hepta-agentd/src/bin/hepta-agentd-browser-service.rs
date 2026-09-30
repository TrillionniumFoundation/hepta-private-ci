//! Long-lived Agentd-owned product service for `browser.servo`.
//!
//! The service owns one persistent Browser control for the Agentd generation,
//! accepts only canonical digest-bound length-prefixed JSON over inherited
//! stdin/stdout, keeps the live revocation feed active, and never exposes a
//! discovery, TCP, UDS, WebDriver, or CDP listener.
//!
//! `navigate_or_act` is replay-safe: before entering final-use authority the
//! service asks the Browser owner for the exact immutable operation receipt
//! through a reserved read-only replay probe. An existing operation returns its
//! original receipt without reconciliation, authority or dispatch. Only a
//! proven absence proceeds to the new effect path.

use std::io::{self, Read, Write};
use std::path::Path;

use codex_hepta_contracts::{FinalUseBinding, SignedFinalUseGrant};
use serde::Deserialize;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

#[allow(dead_code)]
#[path = "../browser_revocation_feed.rs"]
mod browser_revocation_feed;
#[allow(dead_code)]
#[path = "../browser_servo_persistent.rs"]
mod browser_servo;

use browser_servo::{
    BrowserFinalUseInvocation, BrowserServoCall, BrowserServoError, BrowserServoMethod,
    open_browser_servo_port_from_file,
};

const SERVICE_SCHEMA: &str = "hepta.browser.agentd-service-frame.v1";
const SERVICE_PROTOCOL_VERSION: u64 = 1;
const MAX_FRAME_BYTES: usize = 1_048_576;
const MAX_ERROR_CHARS: usize = 512;
const MAX_JSON_DEPTH: usize = 32;
const JS_SAFE_INTEGER: u64 = 9_007_199_254_740_991;
const REPLAY_PROBE_RESULT_KIND: &str = "hepta.browser.replay-probe-result.v1";
const OPERATION_ABSENCE_CODE: &str = "hepta.browser.operation-not-crossed.v1";

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
    payload_digest: String,
    payload: Value,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let config_path = args
        .next()
        .ok_or("usage: hepta-agentd-browser-service BROWSER_HOST_CONFIG.json")?;
    if args.next().is_some() {
        return Err("usage: hepta-agentd-browser-service BROWSER_HOST_CONFIG.json".into());
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
                "ok": false,
                "error": bounded_error(format!("invalid Browser service request: {error}")),
            }),
        };
        let response = build_response_frame(
            next_outgoing_sequence,
            frame.sequence,
            &frame.payload_digest,
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
    let result = execute_call_result(owner, call);
    match result {
        Ok(result) => json!({ "ok": true, "result": result }),
        Err(error) => json!({
            "ok": false,
            "error": bounded_error(error.to_string()),
        }),
    }
}

fn execute_call_result(
    owner: &browser_servo::PersistentBrowserServoControl,
    call: ServiceCallPayload,
) -> Result<Value, BrowserServoError> {
    let method = call.method.module_method();
    if matches!(method, BrowserServoMethod::NavigateOrAct) {
        let (signed_grant, binding) = match (call.signed_grant, call.binding) {
            (Some(signed_grant), Some(binding)) => (signed_grant, binding),
            _ => {
                return Err(BrowserServoError::Invalid(
                    "navigate_or_act requires signed final-use grant and exact binding".into(),
                ));
            }
        };

        let mut replay_input = call.input.clone();
        let replay_object = replay_input.as_object_mut().ok_or_else(|| {
            BrowserServoError::Invalid("Browser call input must be an object".into())
        })?;
        if replay_object
            .insert("replayOnly".into(), Value::Bool(true))
            .is_some()
        {
            return Err(BrowserServoError::Invalid(
                "Browser caller must not supply reserved replayOnly".into(),
            ));
        }
        let probe = BrowserServoCall::read(BrowserServoMethod::ReconcileOperation, replay_input)?;
        if let Some(receipt) = classify_replay_probe(owner.call(probe))? {
            return Ok(receipt);
        }

        return owner.call(BrowserServoCall::effect(
            call.input,
            BrowserFinalUseInvocation {
                signed_grant,
                binding,
            },
        )?);
    }

    if call.signed_grant.is_some() || call.binding.is_some() {
        return Err(BrowserServoError::Invalid(
            "non-effect Browser calls must not carry final-use authority".into(),
        ));
    }
    owner.call(BrowserServoCall::read(method, call.input)?)
}

fn invalid_replay_probe(message: &str) -> BrowserServoError {
    BrowserServoError::Invalid(message.to_string())
}

fn classify_replay_probe(
    result: Result<Value, BrowserServoError>,
) -> Result<Option<Value>, BrowserServoError> {
    let value = result?;
    let object = value
        .as_object()
        .ok_or_else(|| invalid_replay_probe("Browser replay probe result must be an object"))?;
    if object.get("kind").and_then(Value::as_str) != Some(REPLAY_PROBE_RESULT_KIND) {
        return Err(invalid_replay_probe(
            "Browser replay probe result kind is unsupported",
        ));
    }

    match object.get("status").and_then(Value::as_str) {
        Some("present") => {
            if object.len() != 3
                || !object.contains_key("receipt")
                || object.contains_key("absenceCode")
            {
                return Err(invalid_replay_probe(
                    "Browser replay present result contains missing or unknown fields",
                ));
            }
            Ok(Some(object["receipt"].clone()))
        }
        Some("absent") => {
            if object.len() != 3
                || object.get("absenceCode").and_then(Value::as_str) != Some(OPERATION_ABSENCE_CODE)
                || object.contains_key("receipt")
            {
                return Err(invalid_replay_probe(
                    "Browser replay absence is not the registered proof",
                ));
            }
            Ok(None)
        }
        _ => Err(invalid_replay_probe(
            "Browser replay probe status is unsupported",
        )),
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
        payload_digest: payload_digest.to_string(),
        payload,
    })
}

fn build_response_frame(
    response_sequence: u64,
    request_sequence: u64,
    request_payload_digest: &str,
    request_id: &str,
    mut payload: Value,
) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    validate_request_id(request_id)?;
    validate_digest(request_payload_digest, "request payload digest")?;
    let object = payload
        .as_object_mut()
        .ok_or("Browser service response payload must be an object")?;
    if object.contains_key("requestSequence") || object.contains_key("requestPayloadDigest") {
        return Err("Browser service response attempted to pre-bind request identity".into());
    }
    object.insert("requestSequence".into(), Value::from(request_sequence));
    object.insert(
        "requestPayloadDigest".into(),
        Value::String(request_payload_digest.to_string()),
    );
    let payload_json = canonical_json(&payload)?;
    let frame = json!({
        "schema": SERVICE_SCHEMA,
        "protocolVersion": SERVICE_PROTOCOL_VERSION,
        "sequence": response_sequence,
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

fn validate_digest(value: &str, name: &str) -> Result<(), Box<dyn std::error::Error>> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(format!("{name} must be lowercase SHA-256 hex").into());
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

fn write_frame(output: &mut impl Write, body: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
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

fn positive_u64(value: Option<&Value>, name: &str) -> Result<u64, Box<dyn std::error::Error>> {
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
        return Err("Browser service canonical JSON exceeds the hard bound".into());
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
            let safe = number
                .as_u64()
                .is_some_and(|value| value <= JS_SAFE_INTEGER)
                || number
                    .as_i64()
                    .is_some_and(|value| value.unsigned_abs() <= JS_SAFE_INTEGER);
            if !safe {
                return Err("Browser service JSON numbers must be JavaScript-safe integers".into());
            }
            output.push_str(&number.to_string());
        }
        Value::Array(values) => {
            output.push('[');
            for (index, value) in values.iter().enumerate() {
                if index != 0 {
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
                if index != 0 {
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

fn bounded_error(value: impl Into<String>) -> String {
    value.into().chars().take(MAX_ERROR_CHARS).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn replay_probe_accepts_only_the_versioned_absence_proof() {
        let receipt = json!({"operationId": "operation.1", "status": "succeeded"});
        let present = json!({
            "kind": REPLAY_PROBE_RESULT_KIND,
            "status": "present",
            "receipt": receipt,
        });
        assert_eq!(
            classify_replay_probe(Ok(present)).expect("present replay"),
            Some(receipt)
        );

        let absent = json!({
            "kind": REPLAY_PROBE_RESULT_KIND,
            "status": "absent",
            "absenceCode": OPERATION_ABSENCE_CODE,
        });
        assert!(
            classify_replay_probe(Ok(absent))
                .expect("registered absence")
                .is_none()
        );

        for malformed in [
            json!({"kind": REPLAY_PROBE_RESULT_KIND, "status": "absent"}),
            json!({
                "kind": REPLAY_PROBE_RESULT_KIND,
                "status": "absent",
                "absenceCode": "hepta.browser.unknown.v1",
            }),
            json!({
                "kind": REPLAY_PROBE_RESULT_KIND,
                "status": "absent",
                "absenceCode": OPERATION_ABSENCE_CODE,
                "receipt": {},
            }),
            json!({
                "kind": "hepta.browser.replay-probe-result.v2",
                "status": "absent",
                "absenceCode": OPERATION_ABSENCE_CODE,
            }),
        ] {
            assert!(matches!(
                classify_replay_probe(Ok(malformed)),
                Err(BrowserServoError::Invalid(_))
            ));
        }

        assert!(matches!(
            classify_replay_probe(Err(BrowserServoError::Rejected(
                "operation reconciliation changed immutable semantics".into()
            ))),
            Err(BrowserServoError::Rejected(_))
        ));
    }

    #[test]
    fn response_frames_bind_the_exact_parent_request() {
        let request_digest = "1".repeat(64);
        let response = build_response_frame(
            1,
            7,
            &request_digest,
            "request.1",
            json!({"ok": true, "result": {"status": "indeterminate"}}),
        )
        .expect("response");
        let value: Value = serde_json::from_slice(&response).expect("json");
        assert_eq!(value["payload"]["requestSequence"], 7);
        assert_eq!(value["payload"]["requestPayloadDigest"], request_digest);
    }

    #[test]
    fn canonical_json_orders_object_keys() {
        assert_eq!(
            canonical_json(&json!({"z": 1, "a": 2})).unwrap(),
            "{\"a\":2,\"z\":1}"
        );
    }
}
