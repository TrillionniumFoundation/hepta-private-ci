use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::AndroidCellGeneration;
use crate::AndroidNativeTextObservation;
use crate::AndroidSetTextV1;

const PROTOCOL: &str = "pocket4-bound-text-v1";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Apply {
    ok: bool,
    performed: String,
    characters: usize,
    readback_verified: bool,
    password: bool,
    action_submitted: bool,
    receiver_preconditions_checked: bool,
    postcondition_observed: bool,
    independent_readback_required: bool,
    receiver_action_observed_elapsed_ms: u64,
    causal_receipt_persisted: bool,
    business_success_verified: bool,
    automatic_retry: bool,
    organ_protocol: String,
    receiver_generation: AndroidCellGeneration,
    operation_id: String,
    payload_sha256: Sha256Digest,
    accessibility_mode: String,
    restored_flags: i64,
    touch_exploration_after: bool,
    accessibility_mode_restoration_verified: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Readback {
    ok: bool,
    observation: AndroidNativeTextObservation,
    destination_id: String,
    action_submitted: bool,
    independent_readback: bool,
    causal_receipt_persisted: bool,
    business_success_verified: bool,
    automatic_retry: bool,
    state_matches_requested_value: bool,
    terminal_outcome: String,
    organ_protocol: String,
    receiver_generation: AndroidCellGeneration,
    operation_id: String,
    payload_sha256: Sha256Digest,
    accessibility_mode: String,
    restored_flags: i64,
    touch_exploration_after: bool,
    accessibility_mode_restoration_verified: bool,
}

fn parse<T: serde::de::DeserializeOwned>(raw: &[u8]) -> Result<T, String> {
    if raw.is_empty() || raw.len() > 8192 {
        return Err("Android receiver response exceeds its bound".to_string());
    }
    serde_json::from_slice(raw)
        .map_err(|_| "invalid original Android receiver response".to_string())
}

pub(super) fn apply(
    payload: &AndroidSetTextV1,
    digest: &Sha256Digest,
    raw: &[u8],
) -> Result<Apply, String> {
    let reply: Apply = parse(raw)?;
    let _ = (reply.restored_flags, reply.touch_exploration_after);
    if !reply.ok
        || reply.performed != "set-text"
        || reply.characters != payload.value.chars().count()
        || !reply.readback_verified
        || reply.password
        || !reply.action_submitted
        || !reply.receiver_preconditions_checked
        || !reply.postcondition_observed
        || !reply.independent_readback_required
        || reply.causal_receipt_persisted
        || reply.business_success_verified
        || reply.automatic_retry
        || reply.organ_protocol != PROTOCOL
        || reply.receiver_generation != payload.observation.generation
        || reply.operation_id != payload.operation_id
        || reply.payload_sha256 != *digest
        || reply.accessibility_mode != "none"
        || !reply.accessibility_mode_restoration_verified
        || reply.receiver_action_observed_elapsed_ms < payload.observation.observed_elapsed_ms
        || reply.receiver_action_observed_elapsed_ms >= payload.expires_elapsed_ms
    {
        return Err(
            "Android apply acknowledgement does not bind the exact original action".to_string(),
        );
    }
    Ok(reply)
}

pub(super) fn readback(
    payload: &AndroidSetTextV1,
    digest: &Sha256Digest,
    raw: &[u8],
) -> Result<Readback, String> {
    let reply: Readback = parse(raw)?;
    let _ = (reply.restored_flags, reply.touch_exploration_after);
    reply.observation.validate()?;
    if !reply.ok
        || reply.action_submitted
        || !reply.independent_readback
        || reply.causal_receipt_persisted
        || reply.business_success_verified
        || reply.automatic_retry
        || reply.terminal_outcome != "unproven"
        || reply.organ_protocol != PROTOCOL
        || reply.receiver_generation != payload.observation.generation
        || reply.receiver_generation != reply.observation.generation
        || reply.operation_id != payload.operation_id
        || reply.payload_sha256 != *digest
        || reply.destination_id != payload.destination_id
        || reply.accessibility_mode != "none"
        || !reply.accessibility_mode_restoration_verified
        || !reply.observation.same_target(&payload.observation)
        || reply.observation.observed_elapsed_ms < payload.observation.observed_elapsed_ms
        || reply.state_matches_requested_value
            != (reply.observation.target.prior_text_sha256
                == Sha256Digest::for_bytes(payload.value.as_bytes()))
    {
        return Err(
            "Android independent observation does not bind the original target".to_string(),
        );
    }
    Ok(reply)
}

pub(super) fn committed(
    payload: &AndroidSetTextV1,
    digest: &Sha256Digest,
    acknowledgement: &Apply,
    apply_bytes: &[u8],
    readback_bytes: &[u8],
) -> Result<String, String> {
    let readback = readback(payload, digest, readback_bytes)?;
    if !readback.state_matches_requested_value
        || readback.observation.observed_elapsed_ms
            < acknowledgement.receiver_action_observed_elapsed_ms
    {
        return Err("Android apply has no later independent matching text observation".to_string());
    }
    #[derive(Serialize)]
    struct Receipt<'a> {
        schema_version: u16,
        evidence_kind: &'a str,
        operation_id: &'a str,
        payload_sha256: &'a Sha256Digest,
        apply_receiver_json: &'a str,
        independent_readback_json: &'a str,
    }
    serde_json::to_string(&Receipt {
        schema_version: 1,
        evidence_kind: "android_acknowledged_text_and_independent_readback_v1",
        operation_id: &payload.operation_id,
        payload_sha256: digest,
        apply_receiver_json: std::str::from_utf8(apply_bytes)
            .map_err(|_| "non-UTF-8 Android reply")?,
        independent_readback_json: std::str::from_utf8(readback_bytes)
            .map_err(|_| "non-UTF-8 Android readback")?,
    })
    .map_err(|e| e.to_string())
}
