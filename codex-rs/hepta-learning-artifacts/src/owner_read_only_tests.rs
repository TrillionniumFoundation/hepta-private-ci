use super::super::tests::*;
use super::*;
use crate::DatasetWithdrawalNoticeV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;

#[test]
fn a_valid_writer_dto_in_unprotected_storage_never_becomes_root_read_authority() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let trust = trust(&key, scope.digest());
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust.clone(),
        lease(&key, scope.digest()),
        20,
    )
    .fixture("writer fixture");
    assert!(matches!(
        owner.publish_root_read_frontier(&withdrawals, 20),
        Err(ArtifactOwnerHostError::PathBoundary)
    ));
    assert!(matches!(
        ReadOnlyArtifactCurrentOwnerV1::open(&directory.0, trust.clone(), withdrawals, 20),
        Err(ArtifactOwnerHostError::PathBoundary)
    ));
    assert!(!directory.0.join("READ-CURRENT").exists());
    assert!(matches!(
        LearningArtifactOwnerHost::open(&directory.0, trust, lease(&key, scope.digest()), 20),
        Err(ArtifactOwnerHostError::WriterFenceBusy)
    ));
}

/// Real Root-owned storage and a real wall clock exercise the deployment
/// permission boundary. The payload and keys are isolated native fixtures;
/// this never qualifies a scientific model or an installed Agent.
#[test]
#[ignore = "Run explicitly as Root against isolated /var/lib native fixture custody"]
fn root_readonly_current_preserves_the_real_writer_and_closes_on_withdrawal_and_corruption() {
    let now = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .fixture("real clock")
            .as_millis(),
    )
    .fixture("clock width");
    let root = PathBuf::from(format!(
        "/var/lib/hepta/native-readonly-owner-tests/{}-{now}",
        std::process::id()
    ));
    fs::create_dir_all(&root).fixture("isolated Root fixture");
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).fixture("Root fixture mode");
    let key = signer();
    let scope = withdrawal_scope();
    let mut withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let mut trust = trust(&key, scope.digest());
    for signer in trust
        .writer_signers
        .iter_mut()
        .chain(trust.head_signers.iter_mut())
    {
        signer.valid_from = now - 1000;
        signer.expires_at = now + 60000;
    }
    let mut lease = lease(&key, scope.digest());
    lease.issued_at = now;
    lease.expires_at = now + 60000;
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    let owner = LearningArtifactOwnerHost::open(&root, trust.clone(), lease.clone(), now)
        .fixture("actual Root writer");
    let mut model = manifest();
    model.created_at = now;
    model.expires_at = now + 60000;
    let dataset = model.source_dataset_digests[0];
    let admission =
        admit_manifest_at_withdrawal_head_v3(&withdrawals, withdrawals.head_digest(), model, now)
            .fixture("native fixture admission");
    let mut registry = ArtifactRegistry::new();
    let mut transaction = owner
        .begin_publication(
            id("root-native-readonly-operation"),
            admission,
            &withdrawals,
            &registry,
            Digest32::ZERO,
            now,
        )
        .fixture("actual Prepared");
    owner
        .stage_compatibility_registration(&transaction, &mut registry, now)
        .fixture("actual registry projection");
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", now)
        .fixture("payload fsync");
    let binding = digest("root-native-readonly-storage");
    owner
        .ensure_registry_durable(&mut transaction, &registry, &withdrawals, binding, now)
        .fixture("registry fsync");
    let mut head = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: scope.digest(),
        binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: trust.registry_id.clone(),
            generation: Generation::new(1).fixture("generation"),
            head_digest: registry.head_digest(),
            predecessor_head_digest: Digest32::ZERO,
            authority_epoch: 1,
            signer_id: id("owner-authority"),
            signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
            issued_at: now,
            expires_at: now + 60000,
        },
        signature: [0; 64],
    };
    head.signature = key.sign(&head.signing_bytes()).to_bytes();
    owner
        .ensure_witness_durable(&mut transaction, &head, &withdrawals, now)
        .fixture("actual CURRENT fsync");
    assert!(matches!(
        owner.publish_root_read_frontier(&withdrawals, now),
        Err(ArtifactOwnerHostError::CheckpointMissing)
    ));
    owner
        .acknowledge(&mut transaction, &withdrawals, now)
        .fixture("actual ACK fsync");
    owner
        .publish_root_read_frontier(&withdrawals, now)
        .fixture("Root current read grant");
    let reader =
        ReadOnlyArtifactCurrentOwnerV1::open(&root, trust.clone(), withdrawals.clone(), now)
            .fixture("Root protected reader");
    let view = reader
        .current_registry_view(now)
        .fixture("complete read while writer remains held");
    assert_eq!(view.receipt().head_digest, registry.head_digest());
    assert!(view.is_eligible(&id("candidate")));
    assert!(view.supports_dataset(
        registry.manifest(&id("candidate")).fixture("manifest"),
        dataset
    ));
    assert!(matches!(
        LearningArtifactOwnerHost::open(&root, trust.clone(), lease, now),
        Err(ArtifactOwnerHostError::WriterFenceBusy)
    ));
    let mut fake = trust.clone();
    fake.minimum_authority_epoch = 2;
    assert!(matches!(
        ReadOnlyArtifactCurrentOwnerV1::open(&root, fake, withdrawals.clone(), now),
        Err(ArtifactOwnerHostError::ProvenanceMismatch)
    ));
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("native-withdrawal"),
            dataset_digest: dataset,
            source_tombstone_digest: digest("actual-native-tombstone"),
            authority_id: id("native-withdrawal-owner"),
            credential_chain_digest: digest("native-credential"),
            signing_key_digest: digest("native-withdrawal-key"),
            authority_epoch: 1,
            issued_at: now,
        })
        .fixture("withdrawal frontier");
    owner
        .publish_root_read_frontier(&withdrawals, now)
        .fixture("new Root current frontier");
    assert!(matches!(
        reader.current_registry_view(now),
        Err(ArtifactOwnerHostError::CurrentHeadConflict)
    ));
    let revoked = ReadOnlyArtifactCurrentOwnerV1::open(&root, trust, withdrawals, now)
        .fixture("current revoked view");
    assert!(
        !revoked
            .current_registry_view(now)
            .fixture("complete withdrawal view")
            .is_eligible(&id("candidate"))
    );
    let sidecar = fs::read_dir(root.join("admissions"))
        .fixture("admissions")
        .find_map(|entry| {
            let path = entry.fixture("admission entry").path();
            (path
                .extension()
                .is_some_and(|extension| extension == "manifest"))
            .then_some(path)
        })
        .fixture("complete sidecar");
    fs::remove_file(&sidecar).fixture("isolated native corruption");
    assert!(revoked.current_registry_view(now).is_err());
    assert!(!sidecar.exists());
    drop(owner);
    fs::remove_dir_all(root).fixture("isolated native fixture cleanup");
}
