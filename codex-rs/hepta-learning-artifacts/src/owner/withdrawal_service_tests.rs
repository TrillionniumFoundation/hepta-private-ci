use super::*;

use std::fs;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalScopeV1;
use crate::TrustedArtifactSignerV1;
use crate::test_support::FixtureValue;

static NEXT: AtomicU64 = AtomicU64::new(1);

struct TestDir(PathBuf);

impl TestDir {
    fn new() -> Self {
        let sequence = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "artifact-withdrawal-service-{}-{sequence}",
            std::process::id()
        ));
        fs::create_dir(&root).fixture("fresh service root");
        Self(root)
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).fixture("fixture id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn frontier(count: usize) -> DatasetWithdrawalRegistry {
    let mut frontier = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("authority"),
        registry_id: id("withdrawals"),
        scope_id: id("scope"),
    });
    for sequence in 0..count {
        frontier
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id(&format!("notice-{sequence}")),
                dataset_digest: digest(&format!("dataset-{sequence}")),
                source_tombstone_digest: digest("tombstone"),
                authority_id: id("authority"),
                credential_chain_digest: digest("fixture-credential"),
                signing_key_digest: digest("fixture-key"),
                authority_epoch: 1,
                issued_at: 10,
            })
            .fixture("append authenticated fixture");
    }
    frontier
}

fn config(
    root: PathBuf,
    withdrawals: DatasetWithdrawalRegistry,
) -> LearningArtifactOwnerServiceConfigV1 {
    let key = SigningKey::from_bytes(&[9u8; 32]);
    let scope = withdrawals.scope_digest().fixture("scope");
    let signer = TrustedArtifactSignerV1 {
        signer_id: id("authority"),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 10,
        valid_from: 1,
        expires_at: 1000,
        revoked_at: None,
    };
    let trust = ArtifactOwnerTrustV1 {
        registry_id: id("artifacts"),
        withdrawal_scope_digest: scope,
        minimum_registry_generation: Generation::new(1).fixture("generation"),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    };
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("writer-lease"),
        producer_id: id("trainer"),
        registry_id: id("artifacts"),
        withdrawal_scope_digest: scope,
        signer_id: id("authority"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: 10,
        expires_at: 1000,
        signature: [0; 64],
    };
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    LearningArtifactOwnerServiceConfigV1 {
        root,
        trust,
        writer_lease: lease,
        required_current_head: None,
        withdrawal_registry: withdrawals,
        storage_binding: digest("binding"),
        now: 20,
    }
}

#[test]
fn acknowledged_frontier_survives_reopen_and_rejects_old_startup_input() {
    let directory = TestDir::new();
    let mut service = LearningArtifactOwnerService::open(config(directory.0.clone(), frontier(0)))
        .fixture("open service");
    service
        .install_withdrawal_frontier(frontier(2))
        .fixture("durable install");
    assert!(service.withdrawal_frontier_is_durable());
    drop(service);
    assert!(LearningArtifactOwnerService::open(config(directory.0.clone(), frontier(1))).is_err());
    let mut reopened = LearningArtifactOwnerService::open(config(directory.0.clone(), frontier(2)))
        .fixture("reopen exact durable frontier");
    assert_eq!(
        reopened.withdrawal_registry().head_digest(),
        frontier(2).head_digest()
    );
    assert!(reopened.install_withdrawal_frontier(frontier(0)).is_err());
    reopened
        .install_withdrawal_frontier(frontier(3))
        .fixture("extend after restart");
}

#[test]
fn uncertain_frontier_never_reports_drained_or_reopens_old_frontier() {
    let directory = TestDir::new();
    let mut service = LearningArtifactOwnerService::open(config(directory.0.clone(), frontier(0)))
        .fixture("open service");
    let orphan = directory.0.join("writer/withdrawal-floor-v1/0001.v1");
    fs::write(&orphan, b"").fixture("inject interrupted create");
    assert!(service.install_withdrawal_frontier(frontier(1)).is_err());
    assert!(!service.withdrawal_frontier_is_durable());
    assert_eq!(
        service.withdrawal_registry().head_digest(),
        frontier(1).head_digest()
    );
    assert!(matches!(
        service.current_registry_view(20),
        Err(LearningArtifactOwnerServiceError::WithdrawalDurabilityUnknown)
    ));
    service.begin_drain();
    assert!(!service.is_drained());
    assert!(service.install_withdrawal_frontier(frontier(0)).is_err());
    assert!(service.install_withdrawal_frontier(frontier(1)).is_err());
    assert_eq!(fs::read(orphan).fixture("orphan remains untouched"), b"");
}
