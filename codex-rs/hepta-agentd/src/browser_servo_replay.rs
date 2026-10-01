//! v1 response extension for observing an already-recorded immutable effect.
//! This branch never claims new authority or acknowledges a new dispatch.

use serde_json::Map;
use serde_json::Value;

use super::BrowserFinalUseInvocation;
use super::BrowserServoError;
use super::DecodedFrame;
use super::parse_hex_32;
use super::positive_u64;
use super::require_plain_object;
use super::stable_id;

pub(super) fn response_result(
    frame: &DecodedFrame,
    input: &Value,
    invocation: &BrowserFinalUseInvocation,
) -> Result<Value, BrowserServoError> {
    let payload = require_plain_object(&frame.payload, "historical Browser response")?;
    exact_keys(payload, &["ok", "result", "replay"])?;
    if payload.get("ok") != Some(&Value::Bool(true)) {
        return Err(protocol("historical response must be successful"));
    }
    let input = require_plain_object(input, "historical Browser input")?;
    let evidence = require_plain_object(&payload["replay"], "Browser replay evidence")?;
    exact_keys(
        evidence,
        &[
            "schema",
            "profileId",
            "principalId",
            "generation",
            "operationId",
            "requestDigest",
            "semanticDigest",
        ],
    )?;
    if evidence.get("schema").and_then(Value::as_str) != Some("hepta.browser.replay-observation.v1")
    {
        return Err(protocol("Browser replay schema is unsupported"));
    }
    for field in ["profileId", "principalId", "operationId"] {
        let value = evidence
            .get(field)
            .and_then(Value::as_str)
            .ok_or_else(|| protocol("Browser replay identity is missing"))?;
        stable_id(value, "Browser replay identity")?;
        if evidence.get(field) != input.get(field) {
            return Err(protocol(
                "Browser replay identity does not match caller input",
            ));
        }
    }
    let generation = positive_u64(evidence.get("generation"), "Browser replay generation")?;
    if generation != positive_u64(input.get("generation"), "Browser input generation")? {
        return Err(protocol(
            "Browser replay generation does not match caller input",
        ));
    }
    if digest(
        evidence.get("requestDigest"),
        "Browser replay request digest",
    )? != invocation.binding.request_sha256
    {
        return Err(protocol(
            "Browser replay request does not match original FinalUseBinding",
        ));
    }
    digest(
        evidence.get("semanticDigest"),
        "Browser replay semantic digest",
    )?;

    let receipt = require_plain_object(&payload["result"], "Browser replay receipt")?;
    exact_keys(
        receipt,
        &[
            "kind",
            "profileId",
            "operationId",
            "semanticDigest",
            "status",
            "outcomeDigest",
            "terminalObserved",
            "observationReason",
            "networkAuthority",
            "filesystemAuthority",
            "credentialExportAuthority",
        ],
    )?;
    if receipt.get("kind").and_then(Value::as_str) != Some("BrowserEffectObservationV1") {
        return Err(protocol("Browser replay receipt kind is unsupported"));
    }
    for field in ["profileId", "operationId", "semanticDigest"] {
        if receipt.get(field) != evidence.get(field) {
            return Err(protocol(
                "Browser replay receipt identity drifted from evidence",
            ));
        }
    }
    for field in [
        "networkAuthority",
        "filesystemAuthority",
        "credentialExportAuthority",
    ] {
        if receipt.get(field) != Some(&Value::Bool(false)) {
            return Err(protocol("Browser replay cannot grant authority"));
        }
    }
    let reason = receipt
        .get("observationReason")
        .and_then(Value::as_str)
        .ok_or_else(|| protocol("Browser replay observation reason is missing"))?;
    if reason.is_empty() || reason.len() > 512 {
        return Err(protocol(
            "Browser replay observation reason exceeds its bound",
        ));
    }
    match (
        receipt.get("terminalObserved"),
        receipt.get("status").and_then(Value::as_str),
    ) {
        (Some(Value::Bool(true)), Some("succeeded" | "failed")) => {
            digest(
                receipt.get("outcomeDigest"),
                "Browser replay outcome digest",
            )?;
        }
        (Some(Value::Bool(false)), Some("indeterminate"))
            if receipt.get("outcomeDigest") == Some(&Value::Null) => {}
        _ => return Err(protocol("Browser replay result shape is invalid")),
    }
    Ok(payload["result"].clone())
}

fn exact_keys(object: &Map<String, Value>, expected: &[&str]) -> Result<(), BrowserServoError> {
    if object.len() != expected.len() || expected.iter().any(|key| !object.contains_key(*key)) {
        return Err(protocol(
            "Browser replay contains missing or unknown fields",
        ));
    }
    Ok(())
}

fn digest(value: Option<&Value>, name: &str) -> Result<[u8; 32], BrowserServoError> {
    let value = value
        .and_then(Value::as_str)
        .ok_or_else(|| protocol("Browser replay digest is missing"))?;
    let parsed = parse_hex_32(value, name)?;
    if parsed == [0; 32] {
        return Err(protocol("Browser replay digest cannot be zero"));
    }
    Ok(parsed)
}

fn protocol(message: &str) -> BrowserServoError {
    BrowserServoError::Protocol(message.to_string())
}

#[cfg(test)]
#[path = "browser_servo_protocol_tests.rs"]
mod tests;
