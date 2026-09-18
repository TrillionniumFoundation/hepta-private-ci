use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::GrantRequestV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityBridgeError {
    EmptyScope,
    InvalidRequest,
    Authority(FinalUseError),
}

impl fmt::Display for AuthorityBridgeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AuthorityBridgeError {}

impl From<FinalUseError> for AuthorityBridgeError {
    fn from(error: FinalUseError) -> Self {
        Self::Authority(error)
    }
}

/// Canonical request digest sent to the independent kernel.authority boundary.
///
/// This commits every planner-controlled field, including the monotonic
/// planner expiry. It is not a capability and contains no issuer material.
pub fn grant_request_digest_v1(request: &GrantRequestV1) -> Result<Digest32, AuthorityBridgeError> {
    if request.plan_digest.is_zero()
        || request.final_payload_digest.is_zero()
        || request.objective_digest.is_zero()
        || request.snapshot_digest.is_zero()
        || request.revocation_frontier_digest.is_zero()
        || request.expires_at_micros == 0
    {
        return Err(AuthorityBridgeError::InvalidRequest);
    }
    let mut bytes = b"hepta.control.grant-request.v1\0".to_vec();
    push_id(&mut bytes, &request.operation_id);
    push_id(&mut bytes, &request.candidate_id);
    push_digest(&mut bytes, request.plan_digest);
    push_digest(&mut bytes, request.final_payload_digest);
    push_digest(&mut bytes, request.objective_digest);
    push_digest(&mut bytes, request.snapshot_digest);
    push_digest(&mut bytes, request.revocation_frontier_digest);
    bytes.extend_from_slice(&request.expires_at_micros.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

/// Translate one deny-all planner request into the exact binding expected by
/// kernel.authority. The subject/destination/scope come from the trusted host,
/// not from the planner recommendation.
pub fn final_use_binding_for_grant_request_v1(
    request: &GrantRequestV1,
    subject_id: &StableId,
    destination_id: &StableId,
    scope_digest: Digest32,
) -> Result<FinalUseBinding, AuthorityBridgeError> {
    if scope_digest.is_zero() {
        return Err(AuthorityBridgeError::EmptyScope);
    }
    let request_digest = grant_request_digest_v1(request)?;
    Ok(FinalUseBinding {
        subject_id: subject_id.as_str().to_string(),
        destination_id: destination_id.as_str().to_string(),
        request_sha256: request_digest.into_array(),
        scope_sha256: scope_digest.into_array(),
        payload_sha256: request.final_payload_digest.into_array(),
    })
}

/// Claim an independently issued signed grant immediately before the effect
/// adapter. control.runtime never constructs or signs FinalUseGrant values.
pub fn claim_final_use_for_grant_request_v1(
    authority: &FinalUseAuthority,
    signed_grant: &SignedFinalUseGrant,
    request: &GrantRequestV1,
    subject_id: &StableId,
    destination_id: &StableId,
    scope_digest: Digest32,
) -> Result<VerifiedUseToken, AuthorityBridgeError> {
    let binding = final_use_binding_for_grant_request_v1(
        request,
        subject_id,
        destination_id,
        scope_digest,
    )?;
    authority.claim(signed_grant, &binding).map_err(Into::into)
}


/// Preferred final-boundary helper. The caller's effect closure runs only
/// inside FinalUseAuthority's second time/revocation fence after durable nonce
/// claim. Control still does not mint or sign authority.
pub fn with_authorized_grant_request_v1<T>(
    authority: &FinalUseAuthority,
    signed_grant: &SignedFinalUseGrant,
    request: &GrantRequestV1,
    subject_id: &StableId,
    destination_id: &StableId,
    scope_digest: Digest32,
    dispatch: impl FnOnce() -> T,
) -> Result<T, AuthorityBridgeError> {
    let binding = final_use_binding_for_grant_request_v1(
        request,
        subject_id,
        destination_id,
        scope_digest,
    )?;
    let token = authority.claim(signed_grant, &binding)?;
    authority
        .with_verified_use(token, &binding, dispatch)
        .map_err(Into::into)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

#[cfg(test)]
#[path = "authority_bridge_tests.rs"]
mod tests;
