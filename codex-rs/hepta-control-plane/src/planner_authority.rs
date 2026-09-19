use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_types::Digest32;

use crate::GrantRequestSetV1;
use crate::GrantRequestV1;

/// A successfully claimed kernel.authority grant paired with the exact
/// control.runtime request it authorizes. The token remains non-cloneable and
/// non-serializable and must be consumed immediately before the effect boundary.
pub struct ClaimedExecutionGrantV1 {
    request: GrantRequestV1,
    binding: FinalUseBinding,
    token: VerifiedUseToken,
}

impl fmt::Debug for ClaimedExecutionGrantV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ClaimedExecutionGrantV1")
            .field("request", &self.request)
            .field("binding", &self.binding)
            .field("token", &"[REDACTED]")
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionAuthorityErrorV1 {
    RequestSetCarriesAuthority,
    RequestIndexOutOfRange,
    InvalidSubjectOrDestination,
    BindingMismatch,
    Authority(FinalUseError),
}

impl fmt::Display for ExecutionAuthorityErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ExecutionAuthorityErrorV1 {}

impl From<FinalUseError> for ExecutionAuthorityErrorV1 {
    fn from(error: FinalUseError) -> Self {
        Self::Authority(error)
    }
}

impl ClaimedExecutionGrantV1 {
    #[must_use]
    pub fn request(&self) -> &GrantRequestV1 {
        &self.request
    }

    #[must_use]
    pub fn binding(&self) -> &FinalUseBinding {
        &self.binding
    }

    /// Revalidate the signed authority at the last possible boundary and run
    /// exactly one caller-supplied effect closure. This consumes the token.
    pub fn with_verified_use<T>(
        self,
        authority: &FinalUseAuthority,
        consumer: impl FnOnce(&GrantRequestV1) -> T,
    ) -> Result<T, ExecutionAuthorityErrorV1> {
        let Self {
            request,
            binding,
            token,
        } = self;
        authority
            .with_verified_use(token, &binding, || consumer(&request))
            .map_err(Into::into)
    }
}

/// Canonical scope bound by kernel.authority independently of the final payload.
/// The request-set digest is bound separately as FinalUseBinding.request_sha256.
#[must_use]
pub fn execution_grant_scope_digest_v1(request: &GrantRequestV1) -> Digest32 {
    let mut bytes = b"hepta.control.execution-grant-scope.v1\0".to_vec();
    push_id(&mut bytes, request.operation_id.as_str());
    push_id(&mut bytes, request.candidate_id.as_str());
    bytes.extend_from_slice(request.plan_digest.as_array());
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(request.snapshot_digest.as_array());
    bytes.extend_from_slice(request.revocation_frontier_digest.as_array());
    bytes.extend_from_slice(&request.expires_at_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

/// Convert one authority-free GrantRequestV1 into a real, independently signed
/// kernel.authority claim. control.runtime never constructs or signs a grant.
pub fn claim_execution_grant_v1(
    authority: &FinalUseAuthority,
    request_set: &GrantRequestSetV1,
    request_index: usize,
    subject_id: &str,
    destination_id: &str,
    signed_grant: &SignedFinalUseGrant,
) -> Result<ClaimedExecutionGrantV1, ExecutionAuthorityErrorV1> {
    if request_set.authority().grants_any() {
        return Err(ExecutionAuthorityErrorV1::RequestSetCarriesAuthority);
    }
    if subject_id.is_empty()
        || destination_id.is_empty()
        || subject_id.len() > 128
        || destination_id.len() > 128
    {
        return Err(ExecutionAuthorityErrorV1::InvalidSubjectOrDestination);
    }
    let request = request_set
        .requests()
        .get(request_index)
        .cloned()
        .ok_or(ExecutionAuthorityErrorV1::RequestIndexOutOfRange)?;
    let expected = FinalUseBinding {
        subject_id: subject_id.to_string(),
        destination_id: destination_id.to_string(),
        request_sha256: *request_set.request_set_digest().as_array(),
        scope_sha256: *execution_grant_scope_digest_v1(&request).as_array(),
        payload_sha256: *request.final_payload_digest.as_array(),
    };
    if signed_grant.grant.binding != expected {
        return Err(ExecutionAuthorityErrorV1::BindingMismatch);
    }
    let token = authority.claim(signed_grant, &expected)?;
    Ok(ClaimedExecutionGrantV1 {
        request,
        binding: expected,
        token,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &str) {
    let raw = value.as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "planner_authority_tests.rs"]
mod tests;
