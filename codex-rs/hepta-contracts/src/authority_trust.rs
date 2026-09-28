//! External trust interfaces used by kernel.authority production compositions.
//!
//! These traits deliberately do not manufacture trust. Deployments provide an
//! attested/monotonic clock, an externally durable CAS frontier store and a
//! live key-custody identity. The owner retains production custody and bounded
//! uncertainty after open; compatibility remains explicitly distinct.

use crate::VerifiedUseTokenWitnessV1;
use crate::authority_lease::AuthorityLeaseBinding;
use crate::authority_lease::AuthorityLeaseError;
use crate::authority_lease::AuthorityLeaseFrontier;
use crate::authority_lease::AuthorityLeaseRegistry;
use crate::authority_lease::AuthorityLeaseVerifier;
use crate::authority_lease::LeaseVerifiedUseToken;
use crate::authority_lease::dispatch_authority_lease_with_witness;
use crate::final_use::FinalUseAuthority;
use crate::final_use::FinalUseError;
use crate::final_use::FinalUseFrontier;
use crate::final_use::FinalUseIssuerTrustKey;
use crate::final_use::FinalUseRevocations;
use crate::final_use_control::FinalUseControlError;
use crate::final_use_control::FinalUseRevocationFeedVerifier;
use crate::final_use_control::SignedFinalUseRevocationUpdate;
use ed25519_dalek::VerifyingKey;
use sha2::Digest;
use sha2::Sha256;
use std::collections::BTreeSet;
use std::fmt;
use std::marker::PhantomData;
use std::path::Path;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[path = "authority_runtime_clock.rs"]
mod runtime_clock;

/// A deployment may choose a stricter limit but cannot raise this cap.
pub const MAX_PRODUCTION_CLOCK_UNCERTAINTY_MS: u64 = 60_000;
const AUTHORITY_LEASE_KEY_ROLE: &str = "authority-lease-owner";
const FINAL_USE_ISSUER_KEY_ROLE: &str = "final-use-issuer";

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
pub trait AuthorityClock: Send + Sync {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError>;

    /// One coherent centre/radius sample in milliseconds. Legacy clocks have
    /// point-time semantics; that default is not production qualification.
    /// Production constructors always install a wrapper that supplies the
    /// qualified uncertainty and retains live key-custody validation.
    fn now_with_uncertainty(&self) -> Result<(u64, u64), AuthorityTrustError> {
        self.now_unix_ms().map(|now| (now, 0))
    }
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

/// Externally durable CAS, independent of local authority directory rollback.
/// Success commits next before return; local-write uncertainty fences the owner.
pub trait AuthorityFrontierStore<F>: Send + Sync {
    fn load(&self, owner_id: &str) -> Result<F, AuthorityTrustError>;

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &F,
        next: &F,
    ) -> Result<(), AuthorityTrustError>;
}

/// Independently qualified production clock; SystemAuthorityClock is not one.
pub trait ProductionAuthorityClock: AuthorityClock {
    fn production_trust_domain(&self) -> &str;

    fn maximum_uncertainty_ms(&self) -> u64;
}

/// Rollback-independent linearizable CAS; local compatibility files are not one.
pub trait ProductionAuthorityFrontierStore<F>: AuthorityFrontierStore<F> {
    fn production_trust_domain(&self) -> &str;
}

/// Live externally controlled custody identity. The kernel never requests key bytes.
/// Implementations must bound calls; a local authenticated cache must expire
/// fail-closed and must not conceal a known rotation or revocation generation.
pub trait ProductionAuthorityKeyCustody: Send + Sync {
    fn provider_id(&self) -> &str;
    fn key_role(&self) -> &str;
    fn production_trust_domain(&self) -> &str;
    fn active_key_set_sha256(&self) -> Result<[u8; 32], AuthorityTrustError>;
    fn active_generation(&self) -> Result<u64, AuthorityTrustError>;
    fn revoked_before_generation(&self) -> Result<u64, AuthorityTrustError>;
    fn private_key_exportable(&self) -> Result<bool, AuthorityTrustError>;
}

/// References to externally retained evidence; not self-issued attestations.
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
            || self.maximum_clock_uncertainty_ms > MAX_PRODUCTION_CLOCK_UNCERTAINTY_MS
        {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionAuthorityKeyCustodyEvidence {
    pub schema_version: u32,
    pub provider_id: String,
    pub key_role: String,
    pub trust_domain: String,
    pub active_key_set_sha256: [u8; 32],
    pub active_generation: u64,
    pub revoked_before_generation: u64,
    pub custody_receipt_sha256: [u8; 32],
    pub rotation_receipt_sha256: [u8; 32],
    pub compromise_response_receipt_sha256: [u8; 32],
    pub private_key_export_prohibited: bool,
    pub versioned_key_selection: bool,
    pub staged_rotation_verified: bool,
    pub retired_key_rejection_verified: bool,
    pub compromise_response_verified: bool,
}

impl ProductionAuthorityKeyCustodyEvidence {
    pub const SCHEMA_VERSION: u32 = 1;

    pub fn validate(&self) -> Result<(), AuthorityTrustError> {
        let digests = [
            self.active_key_set_sha256,
            self.custody_receipt_sha256,
            self.rotation_receipt_sha256,
            self.compromise_response_receipt_sha256,
        ];
        if self.schema_version != Self::SCHEMA_VERSION
            || !identifier(&self.provider_id)
            || !identifier(&self.key_role)
            || !identifier(&self.trust_domain)
            || digests.iter().any(|digest| *digest == [0; 32])
            || self.active_generation == 0
            || self.revoked_before_generation > self.active_generation
            || !self.private_key_export_prohibited
            || !self.versioned_key_selection
            || !self.staged_rotation_verified
            || !self.retired_key_rejection_verified
            || !self.compromise_response_verified
        {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(())
    }
}

/// Opaque signature-verified recovery head. Raw DTOs are not recovery authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedFinalUseRevocationHead {
    distributor_id: String,
    trust_key_id: String,
    head: FinalUseRevocations,
    update_sha256: [u8; 32],
    issued_at_unix_ms: u64,
    expires_at_unix_ms: u64,
}

impl VerifiedFinalUseRevocationHead {
    pub fn verify(
        verifier: &FinalUseRevocationFeedVerifier,
        signed: &SignedFinalUseRevocationUpdate,
        now_unix_ms: u64,
    ) -> Result<Self, FinalUseControlError> {
        let trust_key_id = verifier.verify(signed, now_unix_ms)?.to_owned();
        let signing_bytes = signed.update.signing_bytes()?;
        let mut digest = Sha256::new();
        digest.update(b"hepta.kernel.authority.revocation-update-digest.v1\0");
        digest.update(signing_bytes);
        Ok(Self {
            distributor_id: signed.update.distributor_id.clone(),
            trust_key_id,
            head: signed.update.head.clone(),
            update_sha256: digest.finalize().into(),
            issued_at_unix_ms: signed.update.issued_at_unix_ms,
            expires_at_unix_ms: signed.update.expires_at_unix_ms,
        })
    }

    pub fn distributor_id(&self) -> &str {
        &self.distributor_id
    }

    pub fn trust_key_id(&self) -> &str {
        &self.trust_key_id
    }

    pub fn head(&self) -> &FinalUseRevocations {
        &self.head
    }

    pub fn update_sha256(&self) -> [u8; 32] {
        self.update_sha256
    }

    pub fn issued_at_unix_ms(&self) -> u64 {
        self.issued_at_unix_ms
    }

    pub fn expires_at_unix_ms(&self) -> u64 {
        self.expires_at_unix_ms
    }

    fn head_at(
        &self,
        now_unix_ms: u64,
        maximum_uncertainty_ms: u64,
    ) -> Result<FinalUseRevocations, FinalUseError> {
        let definitely_live_after = self.issued_at_unix_ms.saturating_add(maximum_uncertainty_ms);
        let possibly_expired_at = now_unix_ms.saturating_add(maximum_uncertainty_ms);
        if now_unix_ms < definitely_live_after || possibly_expired_at >= self.expires_at_unix_ms {
            return Err(FinalUseError::InvalidTrust);
        }
        Ok(self.head.clone())
    }
}

/// Mandatory production trust components; no component is optional.
pub struct ProductionAuthorityTrustBundle<C, S, K, F> {
    clock: Arc<C>,
    frontier_store: Arc<S>,
    key_custody: Arc<K>,
    evidence: ProductionAuthorityTrustEvidence,
    key_custody_evidence: ProductionAuthorityKeyCustodyEvidence,
    _frontier: PhantomData<fn() -> F>,
}

impl<C, S, K, F> fmt::Debug for ProductionAuthorityTrustBundle<C, S, K, F> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("ProductionAuthorityTrustBundle([REDACTED LIVE TRUST])")
    }
}

impl<C, S, K, F> ProductionAuthorityTrustBundle<C, S, K, F>
where
    C: ProductionAuthorityClock,
    S: ProductionAuthorityFrontierStore<F>,
    K: ProductionAuthorityKeyCustody,
{
    pub fn new(
        clock: Arc<C>,
        frontier_store: Arc<S>,
        key_custody: Arc<K>,
        evidence: ProductionAuthorityTrustEvidence,
        key_custody_evidence: ProductionAuthorityKeyCustodyEvidence,
    ) -> Result<Self, AuthorityTrustError> {
        let bundle = Self {
            clock,
            frontier_store,
            key_custody,
            evidence,
            key_custody_evidence,
            _frontier: PhantomData,
        };
        bundle.validate()?;
        Ok(bundle)
    }

    pub fn validate(&self) -> Result<(), AuthorityTrustError> {
        self.evidence.validate()?;
        self.key_custody_evidence.validate()?;
        let now_unix_ms = self.clock.now_unix_ms()?;
        if now_unix_ms == 0
            || self.clock.production_trust_domain() != self.evidence.trust_domain
            || self.frontier_store.production_trust_domain() != self.evidence.trust_domain
            || self.key_custody.production_trust_domain() != self.evidence.trust_domain
            || self.key_custody_evidence.trust_domain.as_str() != self.evidence.trust_domain.as_str()
            || self.key_custody.provider_id() != self.key_custody_evidence.provider_id.as_str()
            || self.key_custody.key_role() != self.key_custody_evidence.key_role.as_str()
            || self.clock.maximum_uncertainty_ms() == 0
            || self.clock.maximum_uncertainty_ms() > MAX_PRODUCTION_CLOCK_UNCERTAINTY_MS
            || self.clock.maximum_uncertainty_ms() > self.evidence.maximum_clock_uncertainty_ms
            || self.evidence.key_custody_attestation_sha256 != self.key_custody_evidence.custody_receipt_sha256
        {
            return Err(AuthorityTrustError::Invalid);
        }
        let live_key_set = self.key_custody.active_key_set_sha256()?;
        let live_generation = self.key_custody.active_generation()?;
        let live_revocation_floor = self.key_custody.revoked_before_generation()?;
        if live_key_set != self.key_custody_evidence.active_key_set_sha256
            || live_generation != self.key_custody_evidence.active_generation
            || live_revocation_floor != self.key_custody_evidence.revoked_before_generation
            || self.key_custody.private_key_exportable()?
        {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(())
    }
}

/// One-shot exact general-lease dispatch capability; no serialization or clone.
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
        dispatch_authority_lease_with_witness(&self.verifier, self.token, &self.expected, dispatch_boundary)
    }
}

impl AuthorityLeaseVerifier {
    /// Exact one-shot product binding. Raw helpers stay closed to product callers.
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
    /// Mandatory production bundle. Live custody remains bound after open.
    pub fn open_production_state_dir<C, S, K>(
        directory: &Path,
        owner_id: String,
        bundle: &ProductionAuthorityTrustBundle<C, S, K, AuthorityLeaseFrontier>,
    ) -> Result<Self, AuthorityLeaseError>
    where
        C: ProductionAuthorityClock + 'static,
        S: ProductionAuthorityFrontierStore<AuthorityLeaseFrontier> + 'static,
        K: ProductionAuthorityKeyCustody + 'static,
    {
        bundle.validate().map_err(|_| AuthorityLeaseError::InvalidTrust)?;
        if bundle.key_custody_evidence.key_role.as_str() != AUTHORITY_LEASE_KEY_ROLE {
            return Err(AuthorityLeaseError::InvalidTrust);
        }
        let clock = runtime_clock::bind(bundle);
        let frontier_store: Arc<dyn AuthorityFrontierStore<AuthorityLeaseFrontier>> = bundle.frontier_store.clone();
        Self::open_state_dir_with_trust(directory, owner_id, clock, frontier_store)
    }
}

/// Exact externally custodied issuer set and authenticated, live initial head.
pub fn open_production_final_use_authority<C, S, K>(
    directory: &Path,
    signer_id: String,
    issuer_keys: Vec<FinalUseIssuerTrustKey>,
    verified_head: &VerifiedFinalUseRevocationHead,
    bundle: &ProductionAuthorityTrustBundle<C, S, K, FinalUseFrontier>,
) -> Result<FinalUseAuthority, FinalUseError>
where
    C: ProductionAuthorityClock + 'static,
    S: ProductionAuthorityFrontierStore<FinalUseFrontier> + 'static,
    K: ProductionAuthorityKeyCustody + 'static,
{
    validate_final_use_production_bundle(&issuer_keys, bundle)?;
    let clock = runtime_clock::bind(bundle);
    let (now, uncertainty) = clock.now_with_uncertainty().map_err(|_| FinalUseError::InvalidTrust)?;
    let head = verified_head.head_at(now, uncertainty)?;
    let frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>> = bundle.frontier_store.clone();
    FinalUseAuthority::open_state_dir_with_issuer_keys(directory, signer_id, issuer_keys, head, clock, frontier_store)
}

/// Recover only an exact external frontier under the same production trust.
pub fn recover_production_final_use_authority<C, S, K>(
    directory: &Path,
    signer_id: String,
    issuer_keys: Vec<FinalUseIssuerTrustKey>,
    verified_head: &VerifiedFinalUseRevocationHead,
    bundle: &ProductionAuthorityTrustBundle<C, S, K, FinalUseFrontier>,
) -> Result<FinalUseAuthority, FinalUseError>
where
    C: ProductionAuthorityClock + 'static,
    S: ProductionAuthorityFrontierStore<FinalUseFrontier> + 'static,
    K: ProductionAuthorityKeyCustody + 'static,
{
    validate_final_use_production_bundle(&issuer_keys, bundle)?;
    let clock = runtime_clock::bind(bundle);
    let (now, uncertainty) = clock.now_with_uncertainty().map_err(|_| FinalUseError::InvalidTrust)?;
    let head = verified_head.head_at(now, uncertainty)?;
    let frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>> = bundle.frontier_store.clone();
    FinalUseAuthority::recover_state_dir_with_issuer_keys(directory, signer_id, issuer_keys, head, clock, frontier_store)
}

fn validate_final_use_production_bundle<C, S, K>(
    issuer_keys: &[FinalUseIssuerTrustKey],
    bundle: &ProductionAuthorityTrustBundle<C, S, K, FinalUseFrontier>,
) -> Result<(), FinalUseError>
where
    C: ProductionAuthorityClock,
    S: ProductionAuthorityFrontierStore<FinalUseFrontier>,
    K: ProductionAuthorityKeyCustody,
{
    bundle.validate().map_err(|_| FinalUseError::InvalidTrust)?;
    if bundle.key_custody_evidence.key_role.as_str() != FINAL_USE_ISSUER_KEY_ROLE
        || final_use_issuer_trust_sha256(issuer_keys)? != bundle.key_custody_evidence.active_key_set_sha256
    {
        return Err(FinalUseError::InvalidTrust);
    }
    Ok(())
}

fn final_use_issuer_trust_sha256(issuer_keys: &[FinalUseIssuerTrustKey]) -> Result<[u8; 32], FinalUseError> {
    if issuer_keys.is_empty() || issuer_keys.len() > 8 {
        return Err(FinalUseError::InvalidTrust);
    }
    let mut keys = issuer_keys.to_vec();
    keys.sort_by(|left, right| left.key_id.cmp(&right.key_id));
    let mut ids = BTreeSet::new();
    let mut public_keys = BTreeSet::new();
    let mut digest = Sha256::new();
    digest.update(b"hepta.kernel.authority.final-use-issuer-trust.v1\0");
    for candidate in keys {
        let key = VerifyingKey::from_bytes(&candidate.verifying_key).map_err(|_| FinalUseError::InvalidTrust)?;
        if !identifier(&candidate.key_id)
            || key.is_weak()
            || candidate.not_before_authority_epoch == 0
            || candidate.not_after_authority_epoch < candidate.not_before_authority_epoch
            || !ids.insert(candidate.key_id.clone())
            || !public_keys.insert(candidate.verifying_key)
        {
            return Err(FinalUseError::InvalidTrust);
        }
        digest.update((candidate.key_id.len() as u64).to_le_bytes());
        digest.update(candidate.key_id.as_bytes());
        digest.update(candidate.verifying_key);
        digest.update(candidate.not_before_authority_epoch.to_le_bytes());
        digest.update(candidate.not_after_authority_epoch.to_le_bytes());
    }
    Ok(digest.finalize().into())
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.bytes().all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b':'))
}

#[cfg(test)]
#[path = "authority_trust_tests.rs"]
mod tests;
