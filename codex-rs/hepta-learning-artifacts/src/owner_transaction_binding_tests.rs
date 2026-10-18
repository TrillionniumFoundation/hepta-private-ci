use super::tests::*;
use super::*;

use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;

fn detached_publication(
    withdrawals: &DatasetWithdrawalRegistry,
    producer: StableId,
) -> (ArtifactRegistry, ArtifactPublicationTransactionV1) {
    let mut v2 = manifest();
    v2.producer_id = producer;
    let admission = admit_manifest_at_withdrawal_head_v3(
        withdrawals,
        withdrawals.head_digest(),
        v2,
        /*now*/ 20,
    )
    .fixture("pure admission");
    let mut registry = ArtifactRegistry::new();
    let transaction = ArtifactPublicationTransactionV1::begin(
        id("detached-operation"),
        admission,
        withdrawals,
        &registry,
        Digest32::ZERO,
        /*now*/ 20,
    )
    .fixture("pure transaction");
    let admission = &transaction.intent().admission;
    let v2 = &admission.validated_manifest.manifest;
    registry
        .append(ArtifactEvent::Register {
            event_id: id("detached-registration"),
            manifest: ArtifactManifest {
                artifact_id: v2.artifact_id.clone(),
                kind: v2.kind,
                generation: v2.generation,
                predecessor_id: None,
                content_digest: v2.bytes_digest,
                objective_digest: v2.objective_class_digest,
                support_digest: admission.validated_manifest.manifest_digest,
                producer_id: v2.producer_id.clone(),
                compatibility_digest: v2.compatibility_digest,
                encoded_size_bytes: v2.encoded_size_bytes,
            },
        })
        .fixture("pure registry projection");
    (registry, transaction)
}

fn record_pure_registry(
    transaction: &mut ArtifactPublicationTransactionV1,
    registry: &ArtifactRegistry,
    withdrawals: &DatasetWithdrawalRegistry,
) {
    transaction
        .record_payload_durable(digest("payload"), /*encoded_bytes*/ 7)
        .fixture("pure payload phase");
    let encoded = encode_snapshot(registry, digest("binding")).fixture("snapshot bytes");
    transaction
        .record_registry_durable(
            registry,
            RegistrySnapshotReceipt {
                binding: digest("binding"),
                head_digest: registry.snapshot().head_digest,
                file_digest: Digest32::of_bytes(&encoded),
                records: registry.records().len(),
                encoded_bytes: encoded.len(),
            },
            withdrawals,
            /*now*/ 20,
        )
        .fixture("pure registry phase");
}

fn effect_inventory(root: &Path) -> Vec<usize> {
    [
        "payloads",
        "registries",
        "witnesses",
        "heads",
        "transactions",
    ]
    .into_iter()
    .map(|directory| {
        fs::read_dir(root.join(directory))
            .fixture("effects")
            .count()
    })
    .collect()
}

#[test]
fn detached_public_transactions_cannot_cross_owner_durability_boundaries() {
    for boundary in ["payload", "registry", "witness", "acknowledgement"] {
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
        let (registry, mut transaction) = detached_publication(&withdrawals, id("trainer"));
        let signed = signed_head(&key, scope.digest(), registry.snapshot().head_digest);
        match boundary {
            "registry" => transaction
                .record_payload_durable(digest("payload"), /*encoded_bytes*/ 7)
                .fixture("pure payload phase"),
            "witness" | "acknowledgement" => {
                record_pure_registry(&mut transaction, &registry, &withdrawals);
                if boundary == "acknowledgement" {
                    let requirement = RegistryHeadRequirementV1 {
                        registry_id: signed.witness.registry_id.clone(),
                        minimum_generation: signed.witness.generation,
                        expected_predecessor_head_digest: Digest32::ZERO,
                        minimum_authority_epoch: 1,
                        now: 20,
                    };
                    let witness = validate_registry_head_witness(&signed.witness, &requirement)
                        .fixture("pure witness");
                    let encoded = encode_head_witness(&signed.witness, signed.binding)
                        .fixture("pure witness bytes");
                    transaction
                        .record_witness_durable(
                            &signed.witness,
                            &requirement,
                            RegistryHeadWitnessReceipt {
                                binding: signed.binding,
                                witness_digest: witness.witness_digest,
                                file_digest: Digest32::of_bytes(&encoded),
                                encoded_bytes: encoded.len(),
                            },
                            &withdrawals,
                            /*now*/ 20,
                        )
                        .fixture("pure witness phase");
                    // Reproduce the CURRENT side effect which the detached
                    // witness call used to expose before any Prepared existed.
                    owner
                        .persist_signed_head_record(&signed)
                        .fixture("head effect");
                }
            }
            "payload" => {}
            _ => unreachable!(),
        }
        let before = transaction.snapshot();
        let effects = effect_inventory(&directory.0);
        let result = match boundary {
            "payload" => owner
                .ensure_payload_durable(&mut transaction, &registry, b"payload", /*now*/ 20)
                .map(|_| ()),
            "registry" => owner
                .ensure_registry_durable(
                    &mut transaction,
                    &registry,
                    &withdrawals,
                    digest("binding"),
                    /*now*/ 20,
                )
                .map(|_| ()),
            "witness" => owner
                .ensure_witness_durable(&mut transaction, &signed, &withdrawals, /*now*/ 20)
                .map(|_| ()),
            "acknowledgement" => owner
                .acknowledge(&mut transaction, &withdrawals, /*now*/ 20)
                .map(|_| ()),
            _ => unreachable!(),
        };
        assert!(matches!(
            result,
            Err(ArtifactOwnerHostError::CheckpointMissing)
        ));
        assert_eq!(transaction.snapshot(), before);
        assert_eq!(effect_inventory(&directory.0), effects);
        assert_eq!(
            owner
                .recover_publication(&id("detached-operation"))
                .fixture("recovery"),
            None
        );
    }
}

#[test]
fn pure_phase_advancement_cannot_skip_owned_payload_and_registry_checkpoints() {
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
    record_pure_registry(&mut transaction, &registry, &withdrawals);
    let signed = signed_head(&key, scope.digest(), registry.snapshot().head_digest);
    let before = transaction.snapshot();
    let effects = effect_inventory(&directory.0);
    assert!(matches!(
        owner.ensure_witness_durable(&mut transaction, &signed, &withdrawals, /*now*/ 20),
        Err(ArtifactOwnerHostError::CheckpointMismatch)
    ));
    assert_eq!(transaction.snapshot(), before);
    assert_eq!(effect_inventory(&directory.0), effects);
    assert_eq!(owner.discover_current_head(20).fixture("no CURRENT"), None);
}

#[test]
fn different_producer_or_scope_cannot_resume_an_existing_owner_operation() {
    for replacement in ["producer", "scope"] {
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
        .fixture("original owner");
        let (_, transaction) = deterministic_publication(&owner, &withdrawals, /*now*/ 20);
        let snapshot = transaction.snapshot();
        drop(owner);
        let mut next_scope = scope;
        if replacement == "scope" {
            next_scope.scope_id = id("different-scope");
        }
        let mut next_lease = lease(&key, next_scope.digest());
        if replacement == "producer" {
            next_lease.producer_id = id("different-producer");
        }
        next_lease.signature = key.sign(&next_lease.signing_bytes()).to_bytes();
        let owner = LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, next_scope.digest()),
            next_lease,
            /*now*/ 21,
        )
        .fixture("replacement owner");
        let effects = effect_inventory(&directory.0);
        assert!(matches!(
            owner.resume_publication(snapshot, /*now*/ 21),
            Err(ArtifactOwnerHostError::WriterLeaseContext)
        ));
        assert_eq!(effect_inventory(&directory.0), effects);
        let (registry, mut foreign) = detached_publication(&withdrawals, id("trainer"));
        assert!(matches!(
            owner.ensure_payload_durable(&mut foreign, &registry, b"payload", /*now*/ 21),
            Err(ArtifactOwnerHostError::WriterLeaseContext)
        ));
        assert_eq!(effect_inventory(&directory.0), effects);
    }
}

#[cfg(target_os = "linux")]
#[test]
fn checkpoint_write_failure_preserves_the_proven_phase_and_allows_exact_retry() {
    let executable = std::env::current_exe().fixture("test executable");
    let status = std::process::Command::new("bash")
        .arg("-c")
        .arg("trap '' XFSZ; exec \"$@\"")
        .arg("checkpoint-fault-worker")
        .arg(executable)
        .args([
            "--exact",
            "owner_host::transaction_binding_tests::checkpoint_size_fault_worker",
            "--ignored",
            "--nocapture",
        ])
        .status()
        .fixture("checkpoint fault worker");
    assert!(status.success());
}

#[cfg(target_os = "linux")]
#[test]
#[ignore = "subprocess fixture runs with an isolated file-size fault"]
fn checkpoint_size_fault_worker() {
    use std::process::Command;

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
    let operation_id = id(&"checkpoint-fault-".repeat(7));
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest(),
        /*now*/ 20,
    )
    .fixture("admission");
    let mut registry = ArtifactRegistry::new();
    let mut transaction = owner
        .begin_publication(
            operation_id.clone(),
            admission,
            &withdrawals,
            &registry,
            Digest32::ZERO,
            /*now*/ 20,
        )
        .fixture("prepared");
    owner
        .stage_compatibility_registration(&transaction, &mut registry, /*now*/ 20)
        .fixture("projection");
    let before = transaction.snapshot();
    let checkpoint = checkpoint_from_snapshot(&before, owner.writer_lease_digest());
    assert!(encode_checkpoint(&checkpoint).len() > 512);
    let pid = std::process::id().to_string();
    let limits = Command::new("prlimit")
        .args(["--pid", &pid, "--fsize", "--noheadings", "--output", "SOFT"])
        .output()
        .fixture("original limit");
    assert!(limits.status.success());
    let original = String::from_utf8(limits.stdout).fixture("limit text");
    assert!(
        Command::new("prlimit")
            .args(["--pid", &pid, "--fsize=512:"])
            .status()
            .fixture("apply limit")
            .success()
    );
    let result =
        owner.ensure_payload_durable(&mut transaction, &registry, b"payload", /*now*/ 20);
    let restored = format!("--fsize={}:", original.trim());
    assert!(
        Command::new("prlimit")
            .args(["--pid", &pid, &restored])
            .status()
            .fixture("restore limit")
            .success()
    );
    assert!(matches!(result, Err(ArtifactOwnerHostError::Indeterminate)));
    assert_eq!(transaction.snapshot(), before);
    let recovered = owner
        .recover_publication(&operation_id)
        .fixture("recovery")
        .fixture("prepared exists");
    assert_eq!(
        recovered.checkpoint.phase,
        ArtifactPublicationPhaseV1::Prepared
    );
    let payloads = fs::read_dir(directory.0.join("payloads"))
        .fixture("payloads")
        .collect::<Result<Vec<_>, _>>()
        .fixture("payload inventory");
    assert_eq!(payloads.len(), 1);
    assert_eq!(
        fs::read(payloads[0].path()).fixture("durable payload effect"),
        b"payload"
    );
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", /*now*/ 20)
        .fixture("exact retry after limit restoration");
    assert_eq!(
        transaction.phase(),
        ArtifactPublicationPhaseV1::PayloadDurable
    );
}
