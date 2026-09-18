//! Concrete adapter from deny-all planner grant requests to kernel.authority.
//!
//! Control never signs a grant. A separately issued SignedFinalUseGrant must
//! bind the exact request before FinalUseAuthority can mint a private token.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;

use crate::GrantRequestV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GrantAuthorityContextV1 {
    pub subject_id: String,
    pub destination_id: String,
    pub scope_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GrantAuthorityAdapterError {
    InvalidContext,
    Authority(FinalUseError),
}

impl fmt::Display for GrantAuthorityAdapterError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for GrantAuthorityAdapterError {}

impl From<FinalUseError> for GrantAuthorityAdapterError {
    fn from(error: FinalUseError) -> Self {
        Self::Authority(error)
    }
}

pub fn final_use_binding_for_grant_request_v1(
    request: &GrantRequestV1,
    context: &GrantAuthorityContextV1,
) -> Result<FinalUseBinding, GrantAuthorityAdapterError> {
    if context.subject_id.is_empty()
        || context.destination_id.is_empty()
        || context.scope_digest.is_zero()
        || request.plan_digest.is_zero()
        || request.final_payload_digest.is_zero()
        || request.objective_digest.is_zero()
        || request.snapshot_digest.is_zero()
        || request.revocation_frontier_digest.is_zero()
    {
        return Err(GrantAuthorityAdapterError::InvalidContext);
    }
    let request_digest = grant_request_digest_v1(request);
    Ok(FinalUseBinding {
        subject_id: context.subject_id.clone(),
        destination_id: context.destination_id.clone(),
        request_sha256: *request_digest.as_array(),
        scope_sha256: *context.scope_digest.as_array(),
        payload_sha256: *request.final_payload_digest.as_array(),
    })
}

/// Claims independently signed authority and executes the caller's final
/// boundary under FinalUseAuthority's second revocation/time fence.
pub fn with_authorized_grant_request_v1<T>(
    authority: &FinalUseAuthority,
    request: &GrantRequestV1,
    context: &GrantAuthorityContextV1,
    signed: &SignedFinalUseGrant,
    dispatch: impl FnOnce() -> T,
) -> Result<T, GrantAuthorityAdapterError> {
    let binding = final_use_binding_for_grant_request_v1(request, context)?;
    let token = authority.claim(signed, &binding)?;
    authority
        .with_verified_use(token, &binding, dispatch)
        .map_err(Into::into)
}

#[must_use]
pub fn grant_request_digest_v1(request: &GrantRequestV1) -> Digest32 {
    let mut bytes = b"hepta.control.grant-request-authority-binding.v1\0".to_vec();
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
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(all(test, unix))]
mod tests {
    use std::collections::BTreeSet;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_types::StableId;
    use ed25519_dalek::Signer as _;
    use ed25519_dalek::SigningKey;

    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn request() -> GrantRequestV1 {
        GrantRequestV1 {
            operation_id: id("operation-send"),
            candidate_id: id("candidate-send"),
            plan_digest: digest("plan"),
            final_payload_digest: digest("payload"),
            objective_digest: digest("objective"),
            snapshot_digest: digest("snapshot"),
            revocation_frontier_digest: digest("revocations"),
            expires_at_micros: 50_000,
        }
    }

    #[test]
    fn independently_signed_final_use_grant_is_required_and_single_use() {
        let directory = tempfile::tempdir().expect("tempdir");
        let signing = SigningKey::from_bytes(&[5_u8; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            directory.path(),
            "runtime-authority".to_string(),
            signing.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 3,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("authority");
        let request = request();
        let context = GrantAuthorityContextV1 {
            subject_id: "control-runtime".to_string(),
            destination_id: "provider-effect".to_string(),
            scope_digest: digest("effect-scope"),
        };
        let binding =
            final_use_binding_for_grant_request_v1(&request, &context).expect("binding");
        let now = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock")
                .as_millis(),
        )
        .expect("millis");
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "runtime-authority".to_string(),
            authority_epoch: 3,
            grant_id: "grant-1".to_string(),
            nonce: [11_u8; 32],
            binding,
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 60_000,
        };
        let signed = SignedFinalUseGrant {
            signature: signing
                .sign(&grant.signing_bytes().expect("signing bytes"))
                .to_bytes()
                .to_vec(),
            grant,
        };

        let result = with_authorized_grant_request_v1(
            &authority,
            &request,
            &context,
            &signed,
            || "dispatched",
        )
        .expect("authorized");
        assert_eq!(result, "dispatched");

        assert_eq!(
            with_authorized_grant_request_v1(&authority, &request, &context, &signed, || ()),
            Err(GrantAuthorityAdapterError::Authority(
                FinalUseError::AlreadyClaimed
            ))
        );
    }

    #[test]
    fn payload_or_scope_drift_breaks_the_final_use_binding() {
        let request = request();
        let context = GrantAuthorityContextV1 {
            subject_id: "control-runtime".to_string(),
            destination_id: "provider-effect".to_string(),
            scope_digest: digest("scope"),
        };
        let original =
            final_use_binding_for_grant_request_v1(&request, &context).expect("binding");
        let mut changed = request;
        changed.final_payload_digest = digest("changed-payload");
        let changed_binding =
            final_use_binding_for_grant_request_v1(&changed, &context).expect("changed binding");
        assert_ne!(original, changed_binding);
    }
}
