//! External trust interfaces used by kernel.authority production compositions.
//!
//! These traits deliberately do not manufacture trust. Deployments provide an
//! attested/monotonic clock and an externally durable CAS frontier store. The
//! authority owners use them to fail closed on time uncertainty and local
//! snapshot rollback.

use crate::VerifiedUseTokenWitnessV1;
use crate::authority_lease::AuthorityLeaseBinding;
use crate::authority_lease::AuthorityLeaseError;
use crate::authority_lease::AuthorityLeaseFrontier;
use crate::authority_lease::AuthorityLeaseRegistry;
use crate::authority_lease::AuthorityLeaseVerifier;
use crate::authority_lease::LeaseVerifiedUseToken;
use crate::authority_lease::dispatch_authority_lease_with_witness;
use std::fmt;
use std::path::Path;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorityTrustError {
    Invalid,
    Conflict,
    Unavailable,
}

impl fmt::Display for AuthorityTrustError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for AuthorityTrustError {}

/// Host-owned trusted wall/monotonic-time projection.
///
/// Production implementations are expected to bind this to an attested or
/// otherwise protected time source. The system clock implementation below is a
/// compatibility/testing implementation, not an attestation claim.
pub trait AuthorityClock: Send + Sync {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SystemAuthorityClock;

impl AuthorityClock for SystemAuthorityClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| AuthorityTrustError::Unavailable)?
            .as_millis();
        u64::try_from(millis).map_err(|_| AuthorityTrustError::Unavailable)
    }
}

/// Externally durable compare-and-set frontier.
///
/// The external store must survive rollback/replacement of the local authority
/// directory. compare_and_set must durably commit next only when the current
/// value exactly equals expected. Authority owners call it before committing
/// the corresponding local state. If the local commit then fails, the owner
/// fences itself; reopening observes an external frontier ahead of local state
/// and fails closed until operator recovery.
pub trait AuthorityFrontierStore<F>: Send + Sync {
    fn load(&self, owner_id: &str) -> Result<F, AuthorityTrustError>;

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &F,
        next: &F,
    ) -> Result<(), AuthorityTrustError>;
}

/// Marker contract for a clock that a deployment has independently qualified
/// for production authority decisions. `SystemAuthorityClock` deliberately
/// does not implement this trait.
pub trait ProductionAuthorityClock: AuthorityClock {
    fn production_trust_domain(&self) -> &str;

    fn maximum_uncertainty_ms(&self) -> u64;
}

/// Marker contract for an external, rollback-independent and linearizable CAS
/// frontier. Local-file compatibility stores deliberately do not implement it.
pub trait ProductionAuthorityFrontierStore<F>: AuthorityFrontierStore<F> {
    fn production_trust_domain(&self) -> &str;
}

/// Deployment evidence required by the production constructor. The digests
/// identify externally retained receipts; they are evidence references, not a
/// claim that this crate performed attestation or a disaster-recovery drill.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionAuthorityTrustEvidence {
    pub schema_version: u32,
    pub deployment_id: String,
    pub trust_domain: String,
    pub clock_attestation_sha256: [u8; 32],
    pub frontier_attestation_sha256: [u8; 32],
    pub key_custody_attestation_sha256: [u8; 32],
    pub verifier_topology_attestation_sha256: [u8; 32],
    pub state_directory_attestation_sha256: [u8; 32],
    pub disaster_recovery_receipt_sha256: [u8; 32],
    pub boot_rollback_detection_enabled: bool,
    pub verifier_only_topology: bool,
    pub state_directory_validated: bool,
    pub kms_or_hsm_custody: bool,
    pub maximum_clock_uncertainty_ms: u64,
}

impl ProductionAuthorityTrustEvidence {
    pub const SCHEMA_VERSION: u32 = 1;

    pub fn validate(&self) -> Result<(), AuthorityTrustError> {
        let identifiers_valid = identifier(&self.deployment_id) && identifier(&self.trust_domain);
        let digests = [
            self.clock_attestation_sha256,
            self.frontier_attestation_sha256,
            self.key_custody_attestation_sha256,
            self.verifier_topology_attestation_sha256,
            self.state_directory_attestation_sha256,
            self.disaster_recovery_receipt_sha256,
        ];
        if self.schema_version != Self::SCHEMA_VERSION
            || !identifiers_valid
            || digests.iter().any(|digest| *digest == [0; 32])
            || !self.boot_rollback_detection_enabled
            || !self.verifier_only_topology
            || !self.state_directory_validated
            || !self.kms_or_hsm_custody
            || self.maximum_clock_uncertainty_ms == 0
        {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(())
    }
}

/// Opaque, one-shot production dispatch capability for one exact general lease.
///
/// The value is intentionally non-cloneable and non-serializable. Dispatch
/// revalidates expiry, epoch, replacement, binding and revocation while holding
/// the authority owner lock across one bounded local irreversible boundary.
#[must_use = "dropping an authority dispatch binding performs no privileged effect"]
pub struct AuthorityDispatchBinding {
    verifier: AuthorityLeaseVerifier,
    token: LeaseVerifiedUseToken,
    expected: AuthorityLeaseBinding,
}

impl fmt::Debug for AuthorityDispatchBinding {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("AuthorityDispatchBinding([REDACTED ONE-SHOT CAPABILITY])")
    }
}

impl AuthorityDispatchBinding {
    pub fn dispatch<T>(
        self,
        dispatch_boundary: impl FnOnce(&VerifiedUseTokenWitnessV1) -> T,
    ) -> Result<(T, VerifiedUseTokenWitnessV1), AuthorityLeaseError> {
        dispatch_authority_lease_with_witness(
            &self.verifier,
            self.token,
            &self.expected,
            dispatch_boundary,
        )
    }
}

impl AuthorityLeaseVerifier {
    /// Bind one exact lease to the only closed-world product final-use
    /// capability. Raw verification helpers remain compatibility/test
    /// primitives and must have no production product callers.
    pub fn bind_dispatch(
        &self,
        lease_id: &str,
        expected_revision: u64,
        expected: &AuthorityLeaseBinding,
    ) -> Result<AuthorityDispatchBinding, AuthorityLeaseError> {
        let token = self.verify_use(lease_id, expected_revision, expected)?;
        Ok(AuthorityDispatchBinding {
            verifier: self.clone(),
            token,
            expected: expected.clone(),
        })
    }
}

impl AuthorityLeaseRegistry {
    /// Production-only constructor. It is unavailable to the system-clock and
    /// local-file compatibility adapters because those types do not implement
    /// the production marker traits. Every external evidence reference and
    /// fail-closed deployment invariant must validate before local state opens.
    pub fn open_production_state_dir<C, S>(
        directory: &Path,
        owner_id: String,
        clock: Arc<C>,
        frontier_store: Arc<S>,
        evidence: &ProductionAuthorityTrustEvidence,
    ) -> Result<Self, AuthorityLeaseError>
    where
        C: ProductionAuthorityClock + 'static,
        S: ProductionAuthorityFrontierStore<AuthorityLeaseFrontier> + 'static,
    {
        evidence
            .validate()
            .map_err(|_| AuthorityLeaseError::InvalidTrust)?;
        if clock.production_trust_domain() != evidence.trust_domain
            || frontier_store.production_trust_domain() != evidence.trust_domain
            || clock.maximum_uncertainty_ms() == 0
            || clock.maximum_uncertainty_ms() > evidence.maximum_clock_uncertainty_ms
        {
            return Err(AuthorityLeaseError::InvalidTrust);
        }
        Self::open_state_dir_with_trust(directory, owner_id, clock, frontier_store)
    }
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b':'))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn production_evidence_rejects_missing_external_receipts() {
        let evidence = ProductionAuthorityTrustEvidence {
            schema_version: ProductionAuthorityTrustEvidence::SCHEMA_VERSION,
            deployment_id: "prod-one".into(),
            trust_domain: "authority-root".into(),
            clock_attestation_sha256: [1; 32],
            frontier_attestation_sha256: [2; 32],
            key_custody_attestation_sha256: [3; 32],
            verifier_topology_attestation_sha256: [4; 32],
            state_directory_attestation_sha256: [5; 32],
            disaster_recovery_receipt_sha256: [0; 32],
            boot_rollback_detection_enabled: true,
            verifier_only_topology: true,
            state_directory_validated: true,
            kms_or_hsm_custody: true,
            maximum_clock_uncertainty_ms: 50,
        };
        assert_eq!(evidence.validate(), Err(AuthorityTrustError::Invalid));
    }

    #[test]
    fn production_evidence_accepts_complete_external_receipt_set() {
        let evidence = ProductionAuthorityTrustEvidence {
            schema_version: ProductionAuthorityTrustEvidence::SCHEMA_VERSION,
            deployment_id: "prod-one".into(),
            trust_domain: "authority-root".into(),
            clock_attestation_sha256: [1; 32],
            frontier_attestation_sha256: [2; 32],
            key_custody_attestation_sha256: [3; 32],
            verifier_topology_attestation_sha256: [4; 32],
            state_directory_attestation_sha256: [5; 32],
            disaster_recovery_receipt_sha256: [6; 32],
            boot_rollback_detection_enabled: true,
            verifier_only_topology: true,
            state_directory_validated: true,
            kms_or_hsm_custody: true,
            maximum_clock_uncertainty_ms: 50,
        };
        evidence.validate().unwrap();
    }
}
