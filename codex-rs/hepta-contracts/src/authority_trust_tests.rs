use super::*;
use crate::final_use_control::FinalUseRevocationUpdate;
use crate::final_use_control::SignedFinalUseRevocationUpdate;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

#[derive(Debug)]
struct MutablePointClock {
    now_unix_ms: AtomicU64,
    uncertainty_ms: AtomicU64,
    unavailable: AtomicBool,
}

impl AuthorityClock for MutablePointClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        self.now_with_uncertainty().map(|(now, _)| now)
    }

    fn now_with_uncertainty(&self) -> Result<(u64, u64), AuthorityTrustError> {
        if self.unavailable.load(Ordering::SeqCst) {
            Err(AuthorityTrustError::Unavailable)
        } else {
            Ok((
                self.now_unix_ms.load(Ordering::SeqCst),
                self.uncertainty_ms.load(Ordering::SeqCst),
            ))
        }
    }
}

#[derive(Debug)]
struct QualifiedClock {
    now_unix_ms: u64,
    trust_domain: String,
    uncertainty_ms: u64,
}

impl AuthorityClock for QualifiedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.now_unix_ms)
    }
}

impl ProductionAuthorityClock for QualifiedClock {
    fn production_trust_domain(&self) -> &str {
        &self.trust_domain
    }

    fn maximum_uncertainty_ms(&self) -> u64 {
        self.uncertainty_ms
    }
}

#[derive(Debug)]
struct MemoryProductionFrontier<F> {
    current: Mutex<F>,
    trust_domain: String,
}

impl<F> AuthorityFrontierStore<F> for MemoryProductionFrontier<F>
where
    F: Copy + Eq + Send,
{
    fn load(&self, _owner_id: &str) -> Result<F, AuthorityTrustError> {
        self.current
            .lock()
            .map(|current| *current)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }

    fn compare_and_set(
        &self,
        _owner_id: &str,
        expected: &F,
        next: &F,
    ) -> Result<(), AuthorityTrustError> {
        let mut current = self
            .current
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if &*current != expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *current = *next;
        Ok(())
    }
}

impl<F> ProductionAuthorityFrontierStore<F> for MemoryProductionFrontier<F>
where
    F: Copy + Eq + Send,
{
    fn production_trust_domain(&self) -> &str {
        &self.trust_domain
    }
}

#[derive(Debug)]
struct QualifiedCustody {
    provider_id: String,
    key_role: String,
    trust_domain: String,
    key_set_sha256: [u8; 32],
    generation: u64,
    revoked_before_generation: u64,
    exportable: bool,
}

impl ProductionAuthorityKeyCustody for QualifiedCustody {
    fn provider_id(&self) -> &str {
        &self.provider_id
    }

    fn key_role(&self) -> &str {
        &self.key_role
    }

    fn production_trust_domain(&self) -> &str {
        &self.trust_domain
    }

    fn active_key_set_sha256(&self) -> Result<[u8; 32], AuthorityTrustError> {
        Ok(self.key_set_sha256)
    }

    fn active_generation(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.generation)
    }

    fn revoked_before_generation(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.revoked_before_generation)
    }

    fn private_key_exportable(&self) -> Result<bool, AuthorityTrustError> {
        Ok(self.exportable)
    }
}

fn trust_evidence() -> ProductionAuthorityTrustEvidence {
    ProductionAuthorityTrustEvidence {
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
    }
}

fn custody_evidence(
    key_role: &str,
    key_set_sha256: [u8; 32],
) -> ProductionAuthorityKeyCustodyEvidence {
    ProductionAuthorityKeyCustodyEvidence {
        schema_version: ProductionAuthorityKeyCustodyEvidence::SCHEMA_VERSION,
        provider_id: "kms-one".into(),
        key_role: key_role.into(),
        trust_domain: "authority-root".into(),
        active_key_set_sha256: key_set_sha256,
        active_generation: 2,
        revoked_before_generation: 1,
        custody_receipt_sha256: [3; 32],
        rotation_receipt_sha256: [7; 32],
        compromise_response_receipt_sha256: [8; 32],
        private_key_export_prohibited: true,
        versioned_key_selection: true,
        staged_rotation_verified: true,
        retired_key_rejection_verified: true,
        compromise_response_verified: true,
    }
}

fn clock() -> Arc<QualifiedClock> {
    clock_at(2_000)
}

fn clock_at(now_unix_ms: u64) -> Arc<QualifiedClock> {
    Arc::new(QualifiedClock {
        now_unix_ms,
        trust_domain: "authority-root".into(),
        uncertainty_ms: 10,
    })
}

fn custody(key_role: &str, key_set_sha256: [u8; 32]) -> Arc<QualifiedCustody> {
    Arc::new(QualifiedCustody {
        provider_id: "kms-one".into(),
        key_role: key_role.into(),
        trust_domain: "authority-root".into(),
        key_set_sha256,
        generation: 2,
        revoked_before_generation: 1,
        exportable: false,
    })
}

fn verified_revocation_head(
    head: &FinalUseRevocations,
    issued_at_unix_ms: u64,
    expires_at_unix_ms: u64,
) -> VerifiedFinalUseRevocationHead {
    let distributor = SigningKey::from_bytes(&[55; 32]);
    let update = FinalUseRevocationUpdate::new(
        "revocation-distributor".into(),
        head.clone(),
        issued_at_unix_ms,
        expires_at_unix_ms,
    );
    let signed = SignedFinalUseRevocationUpdate {
        signature: distributor
            .sign(&update.signing_bytes().unwrap())
            .to_bytes()
            .to_vec(),
        update,
    };
    let verifier = FinalUseRevocationFeedVerifier::new(
        "revocation-distributor".into(),
        distributor.verifying_key().to_bytes(),
    )
    .unwrap();
    VerifiedFinalUseRevocationHead::verify(&verifier, &signed, issued_at_unix_ms + 20).unwrap()
}

#[test]
fn production_evidence_rejects_missing_external_receipts() {
    let mut evidence = trust_evidence();
    evidence.disaster_recovery_receipt_sha256 = [0; 32];
    assert_eq!(evidence.validate(), Err(AuthorityTrustError::Invalid));
}

#[test]
fn production_evidence_rejects_excess_clock_uncertainty() {
    let mut evidence = trust_evidence();
    evidence.maximum_clock_uncertainty_ms = MAX_PRODUCTION_CLOCK_UNCERTAINTY_MS + 1;
    assert_eq!(evidence.validate(), Err(AuthorityTrustError::Invalid));
}

#[test]
fn key_custody_evidence_rejects_missing_rotation_or_compromise_proof() {
    let mut evidence = custody_evidence("authority-root", [9; 32]);
    evidence.rotation_receipt_sha256 = [0; 32];
    assert_eq!(evidence.validate(), Err(AuthorityTrustError::Invalid));
    evidence.rotation_receipt_sha256 = [7; 32];
    evidence.compromise_response_verified = false;
    assert_eq!(evidence.validate(), Err(AuthorityTrustError::Invalid));
}

#[test]
fn bundle_rejects_live_domain_key_set_exportability_and_clock_drift() {
    let frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(AuthorityLeaseFrontier::for_empty_epoch(7).unwrap()),
        trust_domain: "wrong-domain".into(),
    });
    assert!(
        ProductionAuthorityTrustBundle::new(
            clock(),
            frontier,
            custody("authority-root", [9; 32]),
            trust_evidence(),
            custody_evidence("authority-root", [9; 32]),
        )
        .is_err()
    );

    let frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(AuthorityLeaseFrontier::for_empty_epoch(7).unwrap()),
        trust_domain: "authority-root".into(),
    });
    assert!(
        ProductionAuthorityTrustBundle::new(
            clock(),
            frontier,
            custody("authority-root", [10; 32]),
            trust_evidence(),
            custody_evidence("authority-root", [9; 32]),
        )
        .is_err()
    );

    let frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(AuthorityLeaseFrontier::for_empty_epoch(7).unwrap()),
        trust_domain: "authority-root".into(),
    });
    let exportable = Arc::new(QualifiedCustody {
        provider_id: "kms-one".into(),
        key_role: "authority-root".into(),
        trust_domain: "authority-root".into(),
        key_set_sha256: [9; 32],
        generation: 2,
        revoked_before_generation: 1,
        exportable: true,
    });
    assert!(
        ProductionAuthorityTrustBundle::new(
            clock(),
            frontier,
            exportable,
            trust_evidence(),
            custody_evidence("authority-root", [9; 32]),
        )
        .is_err()
    );

    let frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(AuthorityLeaseFrontier::for_empty_epoch(7).unwrap()),
        trust_domain: "authority-root".into(),
    });
    let zero_clock = Arc::new(QualifiedClock {
        now_unix_ms: 0,
        trust_domain: "authority-root".into(),
        uncertainty_ms: 10,
    });
    assert!(
        ProductionAuthorityTrustBundle::new(
            zero_clock,
            frontier,
            custody("authority-root", [9; 32]),
            trust_evidence(),
            custody_evidence("authority-root", [9; 32]),
        )
        .is_err()
    );

    let frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(AuthorityLeaseFrontier::for_empty_epoch(7).unwrap()),
        trust_domain: "authority-root".into(),
    });
    let uncertain_clock = Arc::new(QualifiedClock {
        now_unix_ms: 2_000,
        trust_domain: "authority-root".into(),
        uncertainty_ms: MAX_PRODUCTION_CLOCK_UNCERTAINTY_MS + 1,
    });
    let mut evidence = trust_evidence();
    evidence.maximum_clock_uncertainty_ms = MAX_PRODUCTION_CLOCK_UNCERTAINTY_MS;
    assert!(
        ProductionAuthorityTrustBundle::new(
            uncertain_clock,
            frontier,
            custody("authority-root", [9; 32]),
            evidence,
            custody_evidence("authority-root", [9; 32]),
        )
        .is_err()
    );
}

#[cfg(unix)]
#[test]
fn generic_production_registry_rejects_cross_domain_key_role() {
    let initial = AuthorityLeaseFrontier::for_empty_epoch(7).unwrap();
    let frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(initial),
        trust_domain: "authority-root".into(),
    });
    let bundle = ProductionAuthorityTrustBundle::new(
        clock(),
        frontier,
        custody("final-use-issuer", [9; 32]),
        trust_evidence(),
        custody_evidence("final-use-issuer", [9; 32]),
    )
    .unwrap();
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    assert_eq!(
        AuthorityLeaseRegistry::open_production_state_dir(
            directory.path(),
            "security-authority".into(),
            &bundle,
        )
        .unwrap_err(),
        AuthorityLeaseError::InvalidTrust
    );
}

#[cfg(unix)]
#[test]
fn complete_bundle_opens_generic_production_registry() {
    let initial = AuthorityLeaseFrontier::for_empty_epoch(7).unwrap();
    let frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(initial),
        trust_domain: "authority-root".into(),
    });
    let bundle = ProductionAuthorityTrustBundle::new(
        clock(),
        frontier,
        custody("authority-lease-owner", [9; 32]),
        trust_evidence(),
        custody_evidence("authority-lease-owner", [9; 32]),
    )
    .unwrap();
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let registry = AuthorityLeaseRegistry::open_production_state_dir(
        directory.path(),
        "security-authority".into(),
        &bundle,
    )
    .unwrap();
    assert_eq!(registry.owner_id(), "security-authority");
}

#[cfg(unix)]
#[test]
fn final_use_production_open_binds_exact_custodied_key_ring_and_verified_head() {
    let signer = SigningKey::from_bytes(&[41; 32]);
    let issuer_keys = vec![FinalUseIssuerTrustKey {
        key_id: "issuer-a".into(),
        verifying_key: signer.verifying_key().to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 20,
    }];
    let key_set_sha256 = final_use_issuer_trust_sha256(&issuer_keys).unwrap();
    let head = FinalUseRevocations {
        authority_epoch: 7,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let verified_head = verified_revocation_head(&head, 1_000, 3_000);
    let frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(FinalUseFrontier::for_initial_head(&head).unwrap()),
        trust_domain: "authority-root".into(),
    });
    let bundle = ProductionAuthorityTrustBundle::new(
        clock(),
        frontier,
        custody("final-use-issuer", key_set_sha256),
        trust_evidence(),
        custody_evidence("final-use-issuer", key_set_sha256),
    )
    .unwrap();
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let authority = open_production_final_use_authority(
        directory.path(),
        "security-owner".into(),
        issuer_keys,
        &verified_head,
        &bundle,
    )
    .unwrap();
    assert_eq!(authority.issuer_key_ids(), vec!["issuer-a"]);
    drop(authority);

    let wrong_keys = vec![FinalUseIssuerTrustKey {
        key_id: "issuer-b".into(),
        verifying_key: SigningKey::from_bytes(&[42; 32]).verifying_key().to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 20,
    }];
    assert_eq!(
        recover_production_final_use_authority(
            directory.path(),
            "security-owner".into(),
            wrong_keys,
            &verified_head,
            &bundle,
        )
        .unwrap_err(),
        FinalUseError::InvalidTrust
    );
}

#[cfg(unix)]
#[test]
fn production_open_rechecks_verified_head_freshness_on_the_protected_clock() {
    let signer = SigningKey::from_bytes(&[41; 32]);
    let issuer_keys = vec![FinalUseIssuerTrustKey {
        key_id: "issuer-a".into(),
        verifying_key: signer.verifying_key().to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 20,
    }];
    let key_set_sha256 = final_use_issuer_trust_sha256(&issuer_keys).unwrap();
    let head = FinalUseRevocations {
        authority_epoch: 7,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let verified_head = verified_revocation_head(&head, 2_000, 3_000);
    let frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(FinalUseFrontier::for_initial_head(&head).unwrap()),
        trust_domain: "authority-root".into(),
    });
    let bundle = ProductionAuthorityTrustBundle::new(
        clock_at(4_000),
        frontier,
        custody("final-use-issuer", key_set_sha256),
        trust_evidence(),
        custody_evidence("final-use-issuer", key_set_sha256),
    )
    .unwrap();
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    assert_eq!(
        open_production_final_use_authority(
            directory.path(),
            "security-owner".into(),
            issuer_keys,
            &verified_head,
            &bundle,
        )
        .unwrap_err(),
        FinalUseError::InvalidTrust
    );
}

#[test]
fn final_use_feed_clock_does_not_resurrect_expiry_or_clock_failure() {
    let head = FinalUseRevocations {
        authority_epoch: 7,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let verified_head = verified_revocation_head(&head, 1_000, 1_100);
    let base = Arc::new(MutablePointClock {
        now_unix_ms: AtomicU64::new(1_050),
        uncertainty_ms: AtomicU64::new(0),
        unavailable: AtomicBool::new(false),
    });
    let clock: Arc<dyn AuthorityClock> = base.clone();
    let feed = FinalUseFeedClock::new(clock);

    feed.publish(&verified_head).unwrap();
    assert_eq!(feed.now_unix_ms(), Ok(1_050));
    base.now_unix_ms.store(1_100, Ordering::SeqCst);
    assert_eq!(feed.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
    base.now_unix_ms.store(1_050, Ordering::SeqCst);
    assert_eq!(feed.now_unix_ms(), Err(AuthorityTrustError::Unavailable));

    feed.publish(&verified_head).unwrap();
    base.unavailable.store(true, Ordering::SeqCst);
    assert_eq!(feed.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
    base.unavailable.store(false, Ordering::SeqCst);
    assert_eq!(feed.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
}

#[test]
fn final_use_feed_clock_preserves_uncertainty_and_rejects_future_windows() {
    let head = FinalUseRevocations {
        authority_epoch: 7,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let verified_head = verified_revocation_head(&head, 1_000, 1_100);
    let base = Arc::new(MutablePointClock {
        now_unix_ms: AtomicU64::new(1_050),
        uncertainty_ms: AtomicU64::new(49),
        unavailable: AtomicBool::new(false),
    });
    let clock: Arc<dyn AuthorityClock> = base.clone();
    let feed = FinalUseFeedClock::new(clock);
    feed.publish(&verified_head).unwrap();
    assert_eq!(feed.now_with_uncertainty(), Ok((1_050, 49)));
    base.uncertainty_ms.store(50, Ordering::SeqCst);
    assert_eq!(feed.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
    base.uncertainty_ms.store(49, Ordering::SeqCst);
    assert_eq!(feed.now_unix_ms(), Err(AuthorityTrustError::Unavailable));

    let future_head = verified_revocation_head(&head, 1_060, 1_200);
    assert_eq!(
        feed.publish(&future_head),
        Err(AuthorityTrustError::Unavailable)
    );
}

#[test]
fn final_use_feed_clock_invalidation_reaches_existing_readers() {
    let head = FinalUseRevocations {
        authority_epoch: 7,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let verified_head = verified_revocation_head(&head, 1_000, 1_100);
    let base = Arc::new(MutablePointClock {
        now_unix_ms: AtomicU64::new(1_050),
        uncertainty_ms: AtomicU64::new(0),
        unavailable: AtomicBool::new(false),
    });
    let clock: Arc<dyn AuthorityClock> = base;
    let feed = Arc::new(FinalUseFeedClock::new(clock));
    feed.publish(&verified_head).unwrap();
    let reader: Arc<dyn AuthorityClock> = feed.clone();
    assert_eq!(reader.now_unix_ms(), Ok(1_050));
    feed.invalidate().unwrap();
    assert_eq!(reader.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
}

#[test]
fn production_final_use_context_retains_one_clock_and_exact_issuer_identity() {
    let signer = SigningKey::from_bytes(&[71; 32]);
    let issuer_keys = vec![FinalUseIssuerTrustKey {
        key_id: "issuer-context".into(),
        verifying_key: signer.verifying_key().to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 20,
    }];
    let key_set_sha256 = final_use_issuer_trust_sha256(&issuer_keys).unwrap();
    let head = FinalUseRevocations {
        authority_epoch: 7,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let verified_head = verified_revocation_head(&head, 1_000, 3_000);
    let frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(FinalUseFrontier::for_initial_head(&head).unwrap()),
        trust_domain: "authority-root".into(),
    });
    let bundle = ProductionAuthorityTrustBundle::new(
        clock(),
        frontier,
        custody("final-use-issuer", key_set_sha256),
        trust_evidence(),
        custody_evidence("final-use-issuer", key_set_sha256),
    )
    .unwrap();

    let context = ProductionFinalUseTrustContext::bind(&issuer_keys, &bundle).unwrap();
    let first_clock = context.clock();
    let second_clock = context.clock();
    assert!(Arc::ptr_eq(&first_clock, &second_clock));
    assert_eq!(
        context.verified_revocations(&verified_head),
        Ok(head.clone())
    );

    let feed_clock = context.feed_clock();
    assert_eq!(
        feed_clock.now_unix_ms(),
        Err(AuthorityTrustError::Unavailable)
    );
    feed_clock.publish(&verified_head).unwrap();
    assert_eq!(feed_clock.now_unix_ms(), Ok(2_000));
    feed_clock.invalidate().unwrap();
    assert_eq!(
        feed_clock.now_unix_ms(),
        Err(AuthorityTrustError::Unavailable)
    );

    let other_frontier = Arc::new(MemoryProductionFrontier {
        current: Mutex::new(FinalUseFrontier::for_initial_head(&head).unwrap()),
        trust_domain: "authority-root".into(),
    });
    let other_bundle = ProductionAuthorityTrustBundle::new(
        clock(),
        other_frontier,
        custody("final-use-issuer", key_set_sha256),
        trust_evidence(),
        custody_evidence("final-use-issuer", key_set_sha256),
    )
    .unwrap();
    let other_context = ProductionFinalUseTrustContext::bind(&issuer_keys, &other_bundle).unwrap();
    let directory = tempfile::tempdir().unwrap();
    assert!(matches!(
        context.recover_state_dir_with_feed_clock(
            directory.path(),
            "security-owner".into(),
            issuer_keys,
            &verified_head,
            other_context.feed_clock(),
        ),
        Err(FinalUseError::InvalidTrust)
    ));

    let wrong_keys = vec![FinalUseIssuerTrustKey {
        key_id: "issuer-other".into(),
        verifying_key: SigningKey::from_bytes(&[72; 32]).verifying_key().to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 20,
    }];
    assert_eq!(
        context.require_issuer_keys(&wrong_keys),
        Err(FinalUseError::InvalidTrust)
    );
}
