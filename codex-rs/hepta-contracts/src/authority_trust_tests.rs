use super::*;
use ed25519_dalek::SigningKey;
use std::sync::Mutex;

#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

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
    Arc::new(QualifiedClock {
        now_unix_ms: 2_000,
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

#[test]
fn production_evidence_rejects_missing_external_receipts() {
    let mut evidence = trust_evidence();
    evidence.disaster_recovery_receipt_sha256 = [0; 32];
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
fn bundle_rejects_live_domain_key_set_and_exportability_drift() {
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
        custody("authority-root", [9; 32]),
        trust_evidence(),
        custody_evidence("authority-root", [9; 32]),
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
fn final_use_production_open_binds_exact_custodied_key_ring() {
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
        issuer_keys.clone(),
        head,
        &bundle,
    )
    .unwrap();
    assert_eq!(authority.issuer_key_ids(), vec!["issuer-a"]);
    drop(authority);

    let wrong_keys = vec![FinalUseIssuerTrustKey {
        key_id: "issuer-b".into(),
        verifying_key: SigningKey::from_bytes(&[42; 32])
            .verifying_key()
            .to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 20,
    }];
    assert_eq!(
        recover_production_final_use_authority(
            directory.path(),
            "security-owner".into(),
            wrong_keys,
            FinalUseRevocations {
                authority_epoch: 7,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            &bundle,
        )
        .unwrap_err(),
        FinalUseError::InvalidTrust
    );
}
