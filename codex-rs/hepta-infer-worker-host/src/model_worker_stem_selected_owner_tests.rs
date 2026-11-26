use super::*;

use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_learning_artifacts::DatasetWithdrawalScopeV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerServiceConfigV1;
use codex_hepta_learning_artifacts::SignedArtifactWriterLeaseV1;
use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(s: &str) -> StableId {
    StableId::new(s.to_owned()).expect("fixture stable ID")
}

struct DenyingClock;

impl AuthorityClock for DenyingClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Err(AuthorityTrustError::Unavailable)
    }
}

struct FixedClock;

impl AuthorityClock for FixedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(20)
    }
}

#[test]
fn owner_must_get_trusted_time_then_signed_current_from_actual_artifact_service() {
    let root = tempfile::tempdir().expect("local artifact owner");
    let key = SigningKey::from_bytes(&[73; 32]);
    let verification = key.verifying_key().to_bytes();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"),
        registry_id: id("withdrawal-registry"),
        scope_id: id("principal-workspace-purpose"),
    });
    let scope_digest = withdrawals.scope_digest().expect("scope");
    let registry_id = id("stem-artifact-registry");
    let signer_id = id("stem-artifact-signer");
    let signer = TrustedArtifactSignerV1 {
        signer_id: signer_id.clone(),
        verifying_key: verification,
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 10,
        valid_from: 1,
        expires_at: 1_000,
        revoked_at: None,
    };
    let trust = ArtifactOwnerTrustV1 {
        registry_id: registry_id.clone(),
        withdrawal_scope_digest: scope_digest,
        minimum_registry_generation: Generation::new(1).expect("generation"),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    };
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("stem-writer-lease"),
        producer_id: id("stem-producer"),
        registry_id,
        withdrawal_scope_digest: scope_digest,
        signer_id,
        signing_key_digest: Digest32::of_bytes(&verification),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: 10,
        expires_at: 1_000,
        signature: [0; 64],
    };
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    let mut service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: root.path().to_path_buf(),
        trust,
        writer_lease: lease,
        required_current_head: None,
        withdrawal_registry: withdrawals,
        storage_binding: Digest32::of_bytes(b"independent-host-binding"),
        now: 20,
    })
    .expect("real signed writer lease and locked Artifact owner");

    // The caller cannot supply '20' as a forged timestamp; the bound trust
    // clock is consulted before any request for CURRENT or native execution.
    assert!(matches!(
        acquire_current_pair(&mut service, &DenyingClock),
        Err(StemSelectedOwnerError::UnavailableClock(_))
    ));

    // A trusted time alone still does not make an unpopulated/digest-only CAS
    // store current. Absent signed CURRENT fails closed, not a shadow success.
    assert!(matches!(
        acquire_current_pair(&mut service, &FixedClock),
        Err(StemSelectedOwnerError::UnavailableCurrent(_))
    ));
}
