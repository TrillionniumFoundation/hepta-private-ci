//! External trust interfaces used by kernel.authority production compositions.
//!
//! These traits deliberately do not manufacture trust. Deployments provide an
//! attested/monotonic clock, an externally durable CAS frontier store and a
//! live key-custody identity. Authority owners use the resulting bundle to fail
//! closed on time uncertainty, local snapshot rollback and key-set drift.

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

/// Repository-wide upper bound for production authority clock uncertainty.
/// Deployment evidence may select a stricter bound but cannot raise this cap.
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

/// Live KMS/HSM custody identity used by production constructors.
///
/// The authority kernel never asks this interface for private key bytes. It
/// samples the externally controlled public key-set digest and generation, and
/// rejects an exportable or unexpectedly rolled-back custody state.
pub trait ProductionAuthorityKeyCustody: Send + Sync {
    fn provider_id(&self) -> &str;

    fn key_role(&self) -> &str;

    fn production_trust_domain(&self) -> &str;

    fn active_key_set_sha256(&self) -> Result<[u8; 32], AuthorityTrustError>;

    fn active_generation(&self) -> Result<u64, AuthorityTrustError>;

    fn revoked_before_generation(&self) -> Result<u64, AuthorityTrustError>;

    fn private_key_exportable(&self) -> Result<bool, AuthorityTrustError>;
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
            || self.maximum_clock_uncertainty_ms > MAX_PRODUCTION_CLOCK_UNCERTAINTY_MS
        {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(())
    }
}

/// Evidence for the live key-custody component of a production trust bundle.
/// Every receipt is retained outside the process and content-addressed here.
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

/// Complete production trust bundle. Construction and every privileged open
/// revalidate the live clock, frontier and key-custody identities against the
/// retained evidence. No component is optional and no local compatibility
/// adapter implements all three production marker contracts.
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
            || self.key_custody_evidence.trust_domain.as_str()
                != self.evidence.trust_domain.as_str()
            || self.key_custody.provider_id()
                != self.key_custody_evidence.provider_id.as_str()
            || self.key_custody.key_role() != self.key_custody_evidence.key_role.as_str()
            || self.clock.maximum_uncertainty_ms() == 0
            || self.clock.maximum_uncertainty_ms() > MAX_PRODUCTION_CLOCK_UNCERTAINTY_MS
            || self.clock.maximum_uncertainty_ms() > self.evidence.maximum_clock_uncertainty_ms
            || self.evidence.key_custody_attestation_sha256
                != self.key_custody_evidence.custody_receipt_sha256
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
    /// Production-only constructor. The complete bundle is mandatory, and is
    /// revalidated immediately before local state opens. Compatibility clocks,
    /// local frontier stores and evidence-only key claims cannot satisfy it.
    pub fn open_production_state_dir<C, S, K>(
        directory: &Path,
        owner_id: String,
        bundle: &ProductionAuthorityTrustBundle<C, S, K, AuthorityLeaseFrontier>,
    ) -> Result<Self, AuthorityLeaseError>
    where
        C: ProductionAuthorityClock + 'static,
        S: ProductionAuthorityFrontierStore<AuthorityLeaseFrontier> + 'static,
        K: ProductionAuthorityKeyCustody,
    {
        bundle
            .validate()
            .map_err(|_| AuthorityLeaseError::InvalidTrust)?;
        if bundle.key_custody_evidence.key_role.as_str() != AUTHORITY_LEASE_KEY_ROLE {
            return Err(AuthorityLeaseError::InvalidTrust);
        }
        let clock: Arc<dyn AuthorityClock> = bundle.clock.clone();
        let frontier_store: Arc<dyn AuthorityFrontierStore<AuthorityLeaseFrontier>> =
            bundle.frontier_store.clone();
        Self::open_state_dir_with_trust(directory, owner_id, clock, frontier_store)
    }
}

/// Open a FinalUse key-ring owner only when the exact issuer public-key set is
/// the live, externally custodied set named by the production trust bundle.
pub fn open_production_final_use_authority<C, S, K>(
    directory: &Path,
    signer_id: String,
    issuer_keys: Vec<FinalUseIssuerTrustKey>,
    head: FinalUseRevocations,
    bundle: &ProductionAuthorityTrustBundle<C, S, K, FinalUseFrontier>,
) -> Result<FinalUseAuthority, FinalUseError>
where
    C: ProductionAuthorityClock + 'static,
    S: ProductionAuthorityFrontierStore<FinalUseFrontier> + 'static,
    K: ProductionAuthorityKeyCustody,
{
    validate_final_use_production_bundle(&issuer_keys, bundle)?;
    let clock: Arc<dyn AuthorityClock> = bundle.clock.clone();
    let frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>> =
        bundle.frontier_store.clone();
    FinalUseAuthority::open_state_dir_with_issuer_keys(
        directory,
        signer_id,
        issuer_keys,
        head,
        clock,
        frontier_store,
    )
}

/// Recover a FinalUse key-ring owner only after the same production bundle and
/// issuer set validate. Existing state still has to match the external frontier;
/// the supplied head initializes only a virgin store.
pub fn recover_production_final_use_authority<C, S, K>(
    directory: &Path,
    signer_id: String,
    issuer_keys: Vec<FinalUseIssuerTrustKey>,
    head: FinalUseRevocations,
    bundle: &ProductionAuthorityTrustBundle<C, S, K, FinalUseFrontier>,
) -> Result<FinalUseAuthority, FinalUseError>
where
    C: ProductionAuthorityClock + 'static,
    S: ProductionAuthorityFrontierStore<FinalUseFrontier> + 'static,
    K: ProductionAuthorityKeyCustody,
{
    validate_final_use_production_bundle(&issuer_keys, bundle)?;
    let clock: Arc<dyn AuthorityClock> = bundle.clock.clone();
    let frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>> =
        bundle.frontier_store.clone();
    FinalUseAuthority::recover_state_dir_with_issuer_keys(
        directory,
        signer_id,
        issuer_keys,
        head,
        clock,
        frontier_store,
    )
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
    bundle
        .validate()
        .map_err(|_| FinalUseError::InvalidTrust)?;
    if bundle.key_custody_evidence.key_role.as_str() != FINAL_USE_ISSUER_KEY_ROLE
        || final_use_issuer_trust_sha256(issuer_keys)?
            != bundle.key_custody_evidence.active_key_set_sha256
    {
        return Err(FinalUseError::InvalidTrust);
    }
    Ok(())
}

fn final_use_issuer_trust_sha256(
    issuer_keys: &[FinalUseIssuerTrustKey],
) -> Result<[u8; 32], FinalUseError> {
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
        let key = VerifyingKey::from_bytes(&candidate.verifying_key)
            .map_err(|_| FinalUseError::InvalidTrust)?;
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
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b':'))
}

#[cfg(test)]
#[path = "authority_trust_tests.rs"]
mod tests;
