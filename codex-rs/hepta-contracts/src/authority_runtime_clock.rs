//! Production time retains the exact live custody contract after owner open.
//! This adapter stores no private keys and never creates a second authority.

use super::AuthorityClock;
use super::AuthorityTrustError;
use super::MAX_PRODUCTION_CLOCK_UNCERTAINTY_MS;
use super::ProductionAuthorityClock;
use super::ProductionAuthorityFrontierStore;
use super::ProductionAuthorityKeyCustody;
use super::ProductionAuthorityKeyCustodyEvidence;
use super::ProductionAuthorityTrustBundle;
use super::ProductionAuthorityTrustEvidence;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

pub(super) fn bind<C, S, K, F>(
    bundle: &ProductionAuthorityTrustBundle<C, S, K, F>,
) -> Arc<dyn AuthorityClock>
where
    C: ProductionAuthorityClock + 'static,
    S: ProductionAuthorityFrontierStore<F>,
    K: ProductionAuthorityKeyCustody + 'static,
{
    Arc::new(RuntimeClock {
        clock: Arc::clone(&bundle.clock),
        custody: Arc::clone(&bundle.key_custody),
        evidence: bundle.evidence.clone(),
        custody_evidence: bundle.key_custody_evidence.clone(),
        fenced: AtomicBool::new(false),
    })
}

struct RuntimeClock<C, K> {
    clock: Arc<C>,
    custody: Arc<K>,
    evidence: ProductionAuthorityTrustEvidence,
    custody_evidence: ProductionAuthorityKeyCustodyEvidence,
    fenced: AtomicBool,
}

impl<C, K> RuntimeClock<C, K>
where
    C: ProductionAuthorityClock,
    K: ProductionAuthorityKeyCustody,
{
    fn sample(&self) -> Result<(u64, u64), AuthorityTrustError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(AuthorityTrustError::Invalid);
        }
        let expected = &self.custody_evidence;
        let generation_before = self.custody.active_generation()?;
        let keys = self.custody.active_key_set_sha256()?;
        let floor = self.custody.revoked_before_generation()?;
        let exportable = self.custody.private_key_exportable()?;
        let generation_after = self.custody.active_generation()?;
        let uncertainty = self.clock.maximum_uncertainty_ms();
        if self.clock.production_trust_domain() != self.evidence.trust_domain
            || self.custody.production_trust_domain() != expected.trust_domain
            || self.custody.provider_id() != expected.provider_id
            || self.custody.key_role() != expected.key_role
            || generation_before != expected.active_generation
            || generation_after != generation_before
            || keys != expected.active_key_set_sha256
            || floor != expected.revoked_before_generation
            || exportable
            || uncertainty == 0
            || uncertainty > MAX_PRODUCTION_CLOCK_UNCERTAINTY_MS
            || uncertainty > self.evidence.maximum_clock_uncertainty_ms
        {
            // Observed drift may not disappear merely because a provider later
            // reports its old state. A new owner generation must be qualified.
            self.fenced.store(true, Ordering::Release);
            return Err(AuthorityTrustError::Invalid);
        }
        let now = self.clock.now_unix_ms()?;
        if now == 0 || now.checked_add(uncertainty).is_none() {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok((now, uncertainty))
    }
}

impl<C, K> AuthorityClock for RuntimeClock<C, K>
where
    C: ProductionAuthorityClock,
    K: ProductionAuthorityKeyCustody,
{
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        self.sample().map(|(now, _)| now)
    }

    fn now_with_uncertainty(&self) -> Result<(u64, u64), AuthorityTrustError> {
        self.sample()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicU64;

    struct Clock;

    impl AuthorityClock for Clock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            Ok(2_000)
        }
    }

    impl ProductionAuthorityClock for Clock {
        fn production_trust_domain(&self) -> &str {
            "fixture-domain"
        }

        fn maximum_uncertainty_ms(&self) -> u64 {
            10
        }
    }

    struct Custody {
        generation: AtomicU64,
        unavailable: AtomicBool,
    }

    impl ProductionAuthorityKeyCustody for Custody {
        fn provider_id(&self) -> &str { "fixture-custody" }
        fn key_role(&self) -> &str { "final-use-issuer" }
        fn production_trust_domain(&self) -> &str { "fixture-domain" }
        fn active_key_set_sha256(&self) -> Result<[u8; 32], AuthorityTrustError> {
            Ok([1; 32])
        }
        fn active_generation(&self) -> Result<u64, AuthorityTrustError> {
            if self.unavailable.load(Ordering::SeqCst) {
                Err(AuthorityTrustError::Unavailable)
            } else {
                Ok(self.generation.load(Ordering::SeqCst))
            }
        }
        fn revoked_before_generation(&self) -> Result<u64, AuthorityTrustError> { Ok(1) }
        fn private_key_exportable(&self) -> Result<bool, AuthorityTrustError> { Ok(false) }
    }

    fn fixture() -> (RuntimeClock<Clock, Custody>, Arc<Custody>) {
        let custody = Arc::new(Custody {
            generation: AtomicU64::new(2),
            unavailable: AtomicBool::new(false),
        });
        // These fixture digests are not externally issued deployment evidence.
        let evidence = ProductionAuthorityTrustEvidence {
            schema_version: 1, deployment_id: "fixture".into(), trust_domain: "fixture-domain".into(),
            clock_attestation_sha256: [1; 32], frontier_attestation_sha256: [1; 32],
            key_custody_attestation_sha256: [1; 32], verifier_topology_attestation_sha256: [1; 32],
            state_directory_attestation_sha256: [1; 32], disaster_recovery_receipt_sha256: [1; 32],
            boot_rollback_detection_enabled: true, verifier_only_topology: true,
            state_directory_validated: true, kms_or_hsm_custody: true, maximum_clock_uncertainty_ms: 50,
        };
        let custody_evidence = ProductionAuthorityKeyCustodyEvidence {
            schema_version: 1, provider_id: "fixture-custody".into(), key_role: "final-use-issuer".into(),
            trust_domain: "fixture-domain".into(), active_key_set_sha256: [1; 32], active_generation: 2,
            revoked_before_generation: 1, custody_receipt_sha256: [1; 32], rotation_receipt_sha256: [1; 32],
            compromise_response_receipt_sha256: [1; 32], private_key_export_prohibited: true,
            versioned_key_selection: true, staged_rotation_verified: true, retired_key_rejection_verified: true,
            compromise_response_verified: true,
        };
        (RuntimeClock { clock: Arc::new(Clock), custody: Arc::clone(&custody), evidence,
                       custody_evidence, fenced: AtomicBool::new(false) }, custody)
    }

    #[test]
    fn runtime_retains_uncertainty_and_fences_observed_custody_generation_drift() {
        let (clock, custody) = fixture();
        assert_eq!(clock.now_with_uncertainty(), Ok((2_000, 10)));
        custody.generation.store(3, Ordering::SeqCst);
        assert_eq!(clock.now_with_uncertainty(), Err(AuthorityTrustError::Invalid));
        custody.generation.store(2, Ordering::SeqCst);
        assert_eq!(clock.now_with_uncertainty(), Err(AuthorityTrustError::Invalid));
    }

    #[test]
    fn unavailable_custody_cannot_supply_authority_time() {
        let (clock, custody) = fixture();
        custody.unavailable.store(true, Ordering::SeqCst);
        assert_eq!(clock.now_with_uncertainty(), Err(AuthorityTrustError::Unavailable));
        custody.unavailable.store(false, Ordering::SeqCst);
        assert_eq!(clock.now_with_uncertainty(), Ok((2_000, 10)));
    }
}
