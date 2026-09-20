//! Explicit control.runtime -> kernel.authority final-use bridge.
//!
//! The planner remains authority-free. This host consumes only a sealed
//! GrantRequestV1 and a separately signed FinalUseGrant. Subject, destination,
//! scope and payload are never supplied as independent caller arguments.

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_control_plane::GrantRequestV1;

#[derive(Clone, Debug)]
pub struct AgentdControlRuntimeAuthorityHost {
    authority: FinalUseAuthority,
}

impl AgentdControlRuntimeAuthorityHost {
    #[must_use]
    pub fn new(authority: FinalUseAuthority) -> Self {
        Self { authority }
    }

    pub fn binding(request: &GrantRequestV1) -> Result<FinalUseBinding, FinalUseError> {
        if !request.digest_is_valid() {
            return Err(FinalUseError::BindingMismatch);
        }
        Ok(FinalUseBinding {
            subject_id: request.subject_id.as_str().to_string(),
            destination_id: request.destination_id.as_str().to_string(),
            request_sha256: *request.request_digest().as_array(),
            scope_sha256: *request.scope_digest.as_array(),
            payload_sha256: *request.final_payload_digest.as_array(),
        })
    }

    pub fn claim(
        &self,
        request: &GrantRequestV1,
        signed: &SignedFinalUseGrant,
    ) -> Result<VerifiedUseToken, FinalUseError> {
        let binding = Self::binding(request)?;
        self.authority.claim(signed, &binding)
    }

    pub fn with_verified_use<T>(
        &self,
        token: VerifiedUseToken,
        request: &GrantRequestV1,
        consumer: impl FnOnce() -> T,
    ) -> Result<T, FinalUseError> {
        let binding = Self::binding(request)?;
        self.authority.with_verified_use(token, &binding, consumer)
    }
}

#[cfg(test)]
#[path = "control_runtime_authority_tests.rs"]
mod tests;
