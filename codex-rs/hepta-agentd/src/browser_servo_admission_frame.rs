use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

use crate::browser_servo_product::BrowserServoError;

const MAX_FRAME_BYTES: usize = 1_048_576;
const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;

pub(crate) fn decode(bytes: &[u8]) -> Result<Value, BrowserServoError> {
    if bytes.len() < 5 || bytes.len() > MAX_FRAME_BYTES + 4 {
        return Err(protocol("Browser Agentd frame has invalid byte length"));
    }
    let announced = u32::from_be_bytes(
        bytes[..4]
            .try_into()
            .map_err(|_| protocol("Browser Agentd frame prefix is invalid"))?,
    ) as usize;
    if announced == 0 || announced > MAX_FRAME_BYTES || announced + 4 != bytes.len() {
        return Err(protocol("Browser Agentd frame length prefix mismatch"));
    }
    let body = std::str::from_utf8(&bytes[4..])
        .map_err(|_| protocol("Browser Agentd frame is not UTF-8"))?;
    let value: Value = serde_json::from_str(body)
        .map_err(|_| protocol("Browser Agentd frame is not JSON"))?;
    if canonical(&value)? != body {
        return Err(protocol("Browser Agentd frame is not canonical JSON"));
    }
    let object = value
        .as_object()
        .ok_or_else(|| protocol("Browser Agentd frame must be an object"))?;
    exact(
        object,
        &[
            "kind",
            "payload",
            "payloadDigest",
            "protocolVersion",
            "requestId",
            "schema",
            "sequence",
        ],
        "Browser Agentd frame",
    )?;
    let payload = object
        .get("payload")
        .ok_or_else(|| protocol("Browser Agentd payload is missing"))?;
    let expected = sha256_hex(canonical(payload)?.as_bytes());
    if object.get("payloadDigest").and_then(Value::as_str) != Some(expected.as_str()) {
        return Err(protocol("Browser Agentd payload digest mismatch"));
    }
    Ok(value)
}

pub(crate) fn encode(mut frame: Value) -> Result<Vec<u8>, BrowserServoError> {
    let object = object_mut(&mut frame, "Browser Agentd frame")?;
    let digest = {
        let payload = object
            .get("payload")
            .ok_or_else(|| protocol("Browser Agentd payload is missing"))?;
        sha256_hex(canonical(payload)?.as_bytes())
    };
    object.insert("payloadDigest".to_owned(), Value::String(digest));
    let body = canonical(&frame)?.into_bytes();
    if body.is_empty() || body.len() > MAX_FRAME_BYTES {
        return Err(protocol("Browser Agentd frame exceeds byte limit"));
    }
    let mut output = Vec::with_capacity(body.len() + 4);
    output.extend_from_slice(&(body.len() as u32).to_be_bytes());
    output.extend_from_slice(&body);
    Ok(output)
}

pub(crate) fn exact(
    object: &Map<String, Value>,
    expected: &[&str],
    name: &str,
) -> Result<(), BrowserServoError> {
    if object.len() != expected.len() || expected.iter().any(|key| !object.contains_key(*key)) {
        return Err(protocol(format!(
            "{name} contains missing or unknown fields"
        )));
    }
    Ok(())
}

pub(crate) fn object_mut<'a>(
    value: &'a mut Value,
    name: &str,
) -> Result<&'a mut Map<String, Value>, BrowserServoError> {
    value
        .as_object_mut()
        .ok_or_else(|| protocol(format!("{name} must be an object")))
}

pub(crate) fn text<'a>(
    object: &'a Map<String, Value>,
    key: &str,
    name: &str,
) -> Result<&'a str, BrowserServoError> {
    object
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| protocol(format!("{name}.{key} must be a string")))
}

pub(crate) fn stable_id(value: &str, name: &str) -> Result<(), BrowserServoError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(protocol(format!(
            "{name} must be a bounded stable identifier"
        )));
    }
    Ok(())
}

pub(crate) fn positive(value: Option<&Value>, name: &str) -> Result<u64, BrowserServoError> {
    value
        .and_then(Value::as_u64)
        .filter(|value| *value > 0 && *value <= MAX_SAFE_INTEGER)
        .ok_or_else(|| protocol(format!("{name} must be a positive safe integer")))
}

pub(crate) fn digest(value: Option<&Value>, name: &str) -> Result<[u8; 32], BrowserServoError> {
    let value = value
        .and_then(Value::as_str)
        .ok_or_else(|| protocol(format!("{name} must be lowercase SHA-256 hex")))?;
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        || value.bytes().all(|byte| byte == b'0')
    {
        return Err(protocol(format!(
            "{name} must be non-zero lowercase SHA-256 hex"
        )));
    }
    let mut output = [0_u8; 32];
    for (index, byte) in output.iter_mut().enumerate() {
        let start = index * 2;
        *byte = u8::from_str_radix(&value[start..start + 2], 16)
            .map_err(|_| protocol(format!("{name} contains invalid hex")))?;
    }
    Ok(output)
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest: [u8; 32] = Sha256::digest(bytes).into();
    let mut output = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(output, "{byte:02x}");
    }
    output
}

fn canonical(value: &Value) -> Result<String, BrowserServoError> {
    let mut output = String::new();
    write_canonical(value, 0, &mut output)?;
    if output.len() > MAX_FRAME_BYTES {
        return Err(protocol(
            "canonical Browser Agentd JSON exceeds byte limit",
        ));
    }
    Ok(output)
}

fn write_canonical(
    value: &Value,
    depth: usize,
    output: &mut String,
) -> Result<(), BrowserServoError> {
    if depth > 32 {
        return Err(protocol("Browser Agentd JSON nesting exceeds limit"));
    }
    match value {
        Value::Null => output.push_str("null"),
        Value::Bool(value) => output.push_str(if *value { "true" } else { "false" }),
        Value::String(value) => output.push_str(
            &serde_json::to_string(value)
                .map_err(|_| protocol("Browser Agentd string encoding failed"))?,
        ),
        Value::Number(number) => {
            let valid = number
                .as_u64()
                .map(|value| value <= MAX_SAFE_INTEGER)
                .or_else(|| {
                    number
                        .as_i64()
                        .map(|value| value.unsigned_abs() <= MAX_SAFE_INTEGER)
                })
                .unwrap_or(false);
            if !valid {
                return Err(protocol(
                    "Browser Agentd numbers must be JavaScript-safe integers",
                ));
            }
            output.push_str(&number.to_string());
        }
        Value::Array(items) => {
            output.push('[');
            for (index, item) in items.iter().enumerate() {
                if index != 0 {
                    output.push(',');
                }
                write_canonical(item, depth + 1, output)?;
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
                output.push_str(
                    &serde_json::to_string(key)
                        .map_err(|_| protocol("Browser Agentd key encoding failed"))?,
                );
                output.push(':');
                write_canonical(&object[key], depth + 1, output)?;
            }
            output.push('}');
        }
    }
    Ok(())
}

pub(crate) fn protocol(message: impl Into<String>) -> BrowserServoError {
    BrowserServoError::Protocol(message.into())
}
