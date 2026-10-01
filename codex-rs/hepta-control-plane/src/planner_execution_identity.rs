//! Public canonical identities for durable planner execution requests.
//!
//! Recovery owners need to bind a resolved request to the exact durable claim
//! before they contact the effect owner. These helpers expose the same v1
//! identity domains used by the dispatch-claim state machine without granting
//! authority or admitting dispatch.

use codex_hepta_types::Digest32;

use crate::GrantRequestV1;

/// Canonical identity of the effect operation. This identity is stable across
/// observation-only reconciliation attempts for the same exact request.
#[must_use]
pub fn planner_operation_identity_digest_v1(request: &GrantRequestV1) -> Digest32 {
    let mut bytes = b"hepta.control.execution-operation.v1".to_vec();
    push_id(&mut bytes, request.operation_id.as_str());
    push_id(&mut bytes, request.candidate_id.as_str());
    bytes.extend_from_slice(request.plan_digest.as_array());
    bytes.extend_from_slice(request.final_payload_digest.as_array());
    Digest32::of_bytes(&bytes)
}

/// Canonical identity of the complete grant request, including the objective,
/// snapshot, revocation frontier and expiry binding.
#[must_use]
pub fn planner_request_digest_v1(request: &GrantRequestV1) -> Digest32 {
    let mut bytes = b"hepta.control.execution-request.v1".to_vec();
    push_id(&mut bytes, request.operation_id.as_str());
    push_id(&mut bytes, request.candidate_id.as_str());
    bytes.extend_from_slice(request.plan_digest.as_array());
    bytes.extend_from_slice(request.final_payload_digest.as_array());
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(request.snapshot_digest.as_array());
    bytes.extend_from_slice(request.revocation_frontier_digest.as_array());
    bytes.extend_from_slice(&request.expires_at_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
