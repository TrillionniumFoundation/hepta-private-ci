//! Metadata-only retirement after the original writer's durable terminal.

use super::*;
use serde::Deserialize;

#[derive(Serialize)]
struct Acknowledge<'a> {
    schema_version: u16,
    action: &'static str,
    target: &'a CalculatorTargetIdentity,
    operation_id: &'a str,
    payload_sha256: &'a str,
    receipt_sha256: &'a str,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Response {
    schema_version: u16,
    action: String,
    target: CalculatorTargetIdentity,
    operation_id: String,
    payload_sha256: String,
    receipt_sha256: String,
    status: Status,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum Status {
    Retired,
    AlreadyRetired,
    NotRetired,
}

pub(super) fn retire(
    target: &ProductionCalculatorTarget,
    permit: &crate::CalculatorRetirementPermit,
) -> Result<crate::ProductionRetirementAck, String> {
    let request = permit.request();
    target.decode(request)?;
    let receipt = CalculatorTerminalReceipt::from_json(&request.payload_json, permit.receipt())?;
    if receipt.outcome() != LocalReconcileOutcome::Committed {
        return Err("only an applied Calculator receipt occupies capacity".into());
    }
    // The hash covers the app's original bytes retained by the source owner.
    let digest = Sha256Digest::for_bytes(permit.receipt().as_bytes());
    let mut retired = target
        .retired_receipt
        .try_lock()
        .map_err(|_| "Calculator retirement is busy")?;
    if retired.as_ref() == Some(&digest) {
        return crate::ProductionRetirementAck::from_validated_target(request, permit.receipt());
    }
    let request_bytes = serde_json::to_vec(&Acknowledge {
        schema_version: 1,
        action: "acknowledge",
        target: &target.identity,
        operation_id: &request.occurrence_key,
        payload_sha256: request.payload_sha256.as_str(),
        receipt_sha256: digest.as_str(),
    })
    .map_err(|error| error.to_string())?;
    let bytes = target.recovery.exchange(&request_bytes)?;
    if bytes.is_empty() || bytes.len() > CALCULATOR_RESPONSE_MAX_BYTES {
        return Err("Calculator retirement response exceeds its bound".into());
    }
    let response: Response =
        serde_json::from_slice(&bytes).map_err(|_| "invalid Calculator retirement response")?;
    if response.schema_version != 1
        || response.action != "acknowledged"
        || response.target != target.identity
        || response.operation_id != request.occurrence_key
        || response.payload_sha256 != request.payload_sha256.as_str()
        || response.receipt_sha256 != digest.as_str()
        || !matches!(response.status, Status::Retired | Status::AlreadyRetired)
    {
        return Err("Calculator retirement differs from the original terminal".into());
    }
    *retired = Some(digest);
    crate::ProductionRetirementAck::from_validated_target(request, permit.receipt())
}
