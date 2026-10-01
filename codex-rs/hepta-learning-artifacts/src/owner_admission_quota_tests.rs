use super::tests::*;
use super::*;

use pretty_assertions::assert_eq;

use crate::admit_manifest_at_withdrawal_head_v3;
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

#[test]
fn admission_quota_bounds_orphans_and_preserves_exact_sidecar_reconciliation() {
    for retained in ["complete-sidecars", "admission-only"] {
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
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            manifest(),
            /*now*/ 20,
        )
        .fixture("admission");
        // Model the admission effects preceding an interrupted Prepared write.
        owner
            .persist_admission(&admission)
            .fixture("sidecars before Prepared");
        if retained == "admission-only" {
            fs::remove_file(directory.0.join("admissions").join(format!(
                "{}.manifest",
                admission.validated_manifest.manifest_digest
            )))
            .fixture("interrupt manifest index publication");
        }
        let quota = MAX_HEAD_RECORDS * 4;
        for index in 0..quota - 2 {
            fs::write(
                directory
                    .0
                    .join("admissions")
                    .join(format!("owner-interrupted-{index}.pending")),
                b"",
            )
            .fixture("bounded interrupted admission orphan");
        }
        let before = effect_inventory(&directory.0);
        assert_eq!(
            before,
            [
                0,
                0,
                0,
                0,
                0,
                quota - usize::from(retained == "admission-only")
            ]
        );
        assert_eq!(
            owner
                .recover_publication(&id("previously-interrupted-operation"))
                .fixture("Prepared is absent"),
            None
        );
        let mut fresh_manifest = manifest();
        fresh_manifest.artifact_id = id("fresh-candidate");
        let fresh = admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            fresh_manifest,
            /*now*/ 20,
        )
        .fixture("fresh legal admission");
        assert!(
            owner
                .begin_publication(
                    id("fresh-operation"),
                    fresh,
                    &withdrawals,
                    &ArtifactRegistry::new(),
                    Digest32::ZERO,
                    /*now*/ 20,
                )
                .is_err()
        );
        assert_eq!(effect_inventory(&directory.0), before);
        let mut registry = ArtifactRegistry::new();
        let mut transaction = owner
            .begin_publication(
                id("previously-interrupted-operation"),
                admission,
                &withdrawals,
                &registry,
                Digest32::ZERO,
                /*now*/ 20,
            )
            .fixture("reuse existing sidecars and only the actually missing index");
        assert_eq!(effect_inventory(&directory.0), [1, 0, 0, 0, 0, quota]);
        owner
            .stage_compatibility_registration(&transaction, &mut registry, /*now*/ 20)
            .fixture("registration");
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
        owner
            .ensure_witness_durable(&mut transaction, &signed, &withdrawals, /*now*/ 20)
            .fixture("witness");
        owner
            .acknowledge(&mut transaction, &withdrawals, /*now*/ 20)
            .fixture("acknowledgement at admission capacity");
        assert_eq!(effect_inventory(&directory.0), [5, 1, 1, 1, 1, quota]);
        assert_eq!(
            owner
                .recovery_required_operations()
                .fixture("capacity did not leave unfinished work"),
            Vec::new()
        );
    }
}

#[test]
fn admission_quota_reserves_the_temporary_peak_when_only_admission_bytes_are_missing() {
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
    let original = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest(),
        /*now*/ 20,
    )
    .fixture("original admission");
    owner
        .persist_admission(&original)
        .fixture("complete original sidecars");
    let quota = MAX_HEAD_RECORDS * 4;
    for index in 0..quota - 3 {
        fs::write(
            directory
                .0
                .join("admissions")
                .join(format!("interrupted-{index}.pending")),
            b"",
        )
        .fixture("reserve only one final slot");
    }
    let later = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest(),
        /*now*/ 21,
    )
    .fixture("same manifest with a new admission instant");
    assert_eq!(later.validated_manifest, original.validated_manifest);
    assert_ne!(later.admission_digest, original.admission_digest);
    let before = effect_inventory(&directory.0);
    assert_eq!(before, [0, 0, 0, 0, 0, quota - 1]);
    assert!(
        owner
            .begin_publication(
                id("later-operation"),
                later,
                &withdrawals,
                &ArtifactRegistry::new(),
                Digest32::ZERO,
                /*now*/ 21,
            )
            .is_err()
    );
    assert_eq!(effect_inventory(&directory.0), before);
    let reused = owner
        .begin_publication(
            id("original-operation"),
            original,
            &withdrawals,
            &ArtifactRegistry::new(),
            Digest32::ZERO,
            /*now*/ 21,
        )
        .fixture("already complete sidecars allocate no temporary entry");
    assert_eq!(reused.phase(), ArtifactPublicationPhaseV1::Prepared);
    assert_eq!(effect_inventory(&directory.0), [1, 0, 0, 0, 0, quota - 1]);
}
