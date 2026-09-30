//! Explicit authority posture of the product owner service.
//!
//! The owner service may authenticate, durably persist, recover and project an
//! artifact registry. None of those capabilities selects an artifact, activates
//! it for a consumer, promotes it, releases it, or grants an external effect.
//! Keeping this as a named source fact prevents transport or operational layers
//! from inferring authority from a successful publication receipt.

use codex_hepta_types::AuthorityPosture;

/// Publication and recovery receipts issued by the owner service are evidence,
/// not selection, activation, promotion, release or external-effect authority.
pub const LEARNING_ARTIFACT_OWNER_SERVICE_AUTHORITY: AuthorityPosture =
    AuthorityPosture::DENY_ALL;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn owner_service_authority_is_permanently_deny_all() {
        assert!(!LEARNING_ARTIFACT_OWNER_SERVICE_AUTHORITY.grants_any());
    }
}
