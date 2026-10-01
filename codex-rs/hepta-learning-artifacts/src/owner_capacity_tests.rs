use super::tests::*;
use super::*;

use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

use crate::test_support::FixtureValue;

fn effect_inventory(root: &Path) -> [usize; 6] {
    [
        "transactions",
        "payloads",
        "registries",
        "witnesses",
        "heads",
        "admissions",
    ]
    .map(|name| fs::read_dir(root.join(name)).fixture("effects").count())
}

fn fill_pending(root: &Path, domain: &str, count: usize) {
    for index in 0..count {
        fs::write(
            root.join(domain)
                .join(format!("interrupted-{index}.pending")),
            b"",
        )
        .fixture("real interrupted temporary entry");
    }
}

#[test]
fn registry_orphan_quota_rejects_binding_changes_and_preserves_exact_snapshot_retry() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope.digest()),
        lease(&key, scope.digest()),
        /*now*/ 20,
    )
    .fixture("owner");
    let (registry, mut transaction) =
        deterministic_publication(&owner, &withdrawals, /*now*/ 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", /*now*/ 20)
        .fixture("payload durable");
    let encoded = encode_snapshot(&registry, digest("binding")).fixture("canonical snapshot");
    let snapshot_path = directory.0.join("registries").join(format!(
        "{}-{}.snapshot",
        registry.snapshot().head_digest,
        Digest32::of_bytes(&encoded)
    ));
    // Reproduce the real atomic snapshot effect preceding a failed checkpoint.
    records::write_record_with_limit(&snapshot_path, &encoded, encoded.len())
        .fixture("complete snapshot orphan without RegistryDurable checkpoint");
    let quota = MAX_HEAD_RECORDS * 4;
    fill_pending(&directory.0, "registries", quota - 2);
    for binding in [digest("another-binding"), digest("yet-another-binding")] {
        let before = effect_inventory(&directory.0);
        let state = transaction.snapshot();
        assert!(
            owner
                .ensure_registry_durable(
                    &mut transaction,
                    &registry,
                    &withdrawals,
                    binding,
                    /*now*/ 20,
                )
                .is_err()
        );
        assert_eq!(effect_inventory(&directory.0), before);
        assert_eq!(transaction.snapshot(), state);
        // The first attempt has only one spare entry, insufficient for the
        // final/pending peak; the second attempt has no spare entry at all.
        fs::write(
            directory.0.join("registries/capacity-boundary.pending"),
            b"",
        )
        .fixture("fill last registry slot");
    }
    owner
        .ensure_registry_durable(
            &mut transaction,
            &registry,
            &withdrawals,
            digest("binding"),
            /*now*/ 20,
        )
        .fixture("exact complete snapshot retry at quota");
    let signed = signed_head(&key, scope.digest(), registry.snapshot().head_digest);
    owner
        .ensure_witness_durable(&mut transaction, &signed, &withdrawals, /*now*/ 20)
        .fixture("witness");
    owner
        .acknowledge(&mut transaction, &withdrawals, /*now*/ 20)
        .fixture("acknowledgement");
    assert_eq!(effect_inventory(&directory.0), [5, 1, quota, 1, 1, 2]);
}

#[test]
fn witness_orphan_quota_rejects_valid_signed_changes_and_preserves_exact_retry() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope.digest()),
        lease(&key, scope.digest()),
        /*now*/ 20,
    )
    .fixture("owner");
    let (registry, mut transaction) =
        deterministic_publication(&owner, &withdrawals, /*now*/ 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", /*now*/ 20)
        .fixture("payload");
    owner
        .ensure_registry_durable(
            &mut transaction,
            &registry,
            &withdrawals,
            digest("binding"),
            /*now*/ 20,
        )
        .fixture("registry");
    let signed = signed_head(&key, scope.digest(), registry.snapshot().head_digest);
    let requirement = RegistryHeadRequirementV1 {
        registry_id: signed.witness.registry_id.clone(),
        minimum_generation: signed.witness.generation,
        expected_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        now: 20,
    };
    let verified = validate_registry_head_witness(&signed.witness, &requirement).fixture("witness");
    let encoded = encode_head_witness(&signed.witness, signed.binding).fixture("canonical witness");
    let witness_path = directory.0.join("witnesses").join(format!(
        "{}-{}.witness",
        signed.witness.generation.get(),
        verified.witness_digest
    ));
    // The immutable witness exists while the following head effect is absent.
    records::write_record_with_limit(&witness_path, &encoded, encoded.len())
        .fixture("complete witness orphan preceding head I/O failure");
    let quota = MAX_HEAD_RECORDS * 4;
    fill_pending(&directory.0, "witnesses", quota - 2);
    for issued_at in [21, 22] {
        let mut changed = signed.clone();
        changed.witness.issued_at = issued_at;
        changed.signature = key.sign(&changed.signing_bytes()).to_bytes();
        let before = effect_inventory(&directory.0);
        let state = transaction.snapshot();
        assert!(
            owner
                .ensure_witness_durable(&mut transaction, &changed, &withdrawals, issued_at,)
                .is_err()
        );
        assert_eq!(effect_inventory(&directory.0), before);
        assert_eq!(transaction.snapshot(), state);
        assert_eq!(
            owner
                .discover_current_head(issued_at)
                .fixture("no orphan became CURRENT"),
            None
        );
        fs::write(directory.0.join("witnesses/capacity-boundary.pending"), b"")
            .fixture("fill last witness slot");
    }
    owner
        .ensure_witness_durable(&mut transaction, &signed, &withdrawals, /*now*/ 22)
        .fixture("exact complete witness retry at quota");
    owner
        .acknowledge(&mut transaction, &withdrawals, /*now*/ 22)
        .fixture("acknowledgement");
    assert_eq!(effect_inventory(&directory.0), [5, 1, 1, quota, 1, 2]);
}

#[test]
fn publication_preflights_payload_checkpoint_and_head_capacity_before_effects() {
    for domain in ["payloads", "transactions", "heads"] {
        let directory = TestDir::new();
        let key = signer();
        let scope = withdrawal_scope();
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
        let owner = LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, scope.digest()),
            lease(&key, scope.digest()),
            /*now*/ 20,
        )
        .fixture("owner");
        let (registry, mut transaction) =
            deterministic_publication(&owner, &withdrawals, /*now*/ 20);
        if domain == "heads" {
            owner
                .ensure_payload_durable(&mut transaction, &registry, b"payload", /*now*/ 20)
                .fixture("payload");
            owner
                .ensure_registry_durable(
                    &mut transaction,
                    &registry,
                    &withdrawals,
                    digest("binding"),
                    /*now*/ 20,
                )
                .fixture("registry");
            fill_pending(&directory.0, domain, MAX_HEAD_RECORDS * 2);
        } else if domain == "payloads" {
            fill_pending(&directory.0, domain, MAX_HEAD_RECORDS * 2);
        } else {
            // Prepared already occupies one slot; leave one slot to ensure a
            // new checkpoint reserves its simultaneous pending/final pair.
            fill_pending(&directory.0, domain, MAX_HEAD_RECORDS * 6 - 2);
        }
        let before = effect_inventory(&directory.0);
        let state = transaction.snapshot();
        let signed = signed_head(&key, scope.digest(), registry.snapshot().head_digest);
        let result = if domain == "heads" {
            owner
                .ensure_witness_durable(&mut transaction, &signed, &withdrawals, /*now*/ 20)
                .map(|_| ())
        } else {
            owner
                .ensure_payload_durable(&mut transaction, &registry, b"payload", /*now*/ 20)
                .map(|_| ())
        };
        assert!(result.is_err());
        assert_eq!(effect_inventory(&directory.0), before);
        assert_eq!(transaction.snapshot(), state);
        if domain == "heads" {
            // Test-only retention frees a pair to seed a complete head, then
            // restores capacity. Production publication deletes no orphan.
            for index in [0, 1] {
                fs::remove_file(
                    directory
                        .0
                        .join("heads")
                        .join(format!("interrupted-{index}.pending")),
                )
                .fixture("test-only retention");
            }
            owner
                .persist_signed_head_record(&signed)
                .fixture("complete uncertain CURRENT");
            fs::write(directory.0.join("heads/capacity-boundary.pending"), b"")
                .fixture("restore head quota");
            owner
                .ensure_witness_durable(&mut transaction, &signed, &withdrawals, /*now*/ 20)
                .fixture("reuse exact head at quota without temporary allocation");
            owner
                .acknowledge(&mut transaction, &withdrawals, /*now*/ 20)
                .fixture("acknowledgement");
            assert_eq!(
                effect_inventory(&directory.0),
                [5, 1, 1, 1, MAX_HEAD_RECORDS * 2, 2]
            );
        }
    }
}
