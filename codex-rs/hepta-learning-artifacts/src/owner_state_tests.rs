use super::tests::*;
use super::*;
use crate::ArtifactOwnerStateIntentV1;
use crate::ArtifactOwnerStateTransitionV1;
use crate::ArtifactState;
use crate::DatasetWithdrawalNoticeV1;
use crate::LearningArtifactStatePublishRequestV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::fs;

fn opened(directory: &TestDir, key: &SigningKey) -> LearningArtifactOwnerService {
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(key, scope_digest),
        writer_lease: lease(key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals,
        storage_binding: digest("binding"),
        now: 20,
    })
    .fixture("open")
}
fn registered(directory: &TestDir, key: &SigningKey) -> LearningArtifactOwnerService {
    let mut service = opened(directory, key);
    let predecessor = service.registry.snapshot().head_digest;
    let admission = admit_manifest_at_withdrawal_head_v3(
        &service.withdrawal_registry,
        service.withdrawal_registry.head_digest(),
        manifest(),
        20,
    )
    .fixture("admit");
    let preview = ArtifactPublicationTransactionV1::begin(
        id("operation"),
        admission,
        &service.withdrawal_registry,
        &service.registry,
        predecessor,
        20,
    )
    .fixture("preview");
    let mut staged = service.registry.clone();
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, 20)
        .fixture("stage");
    let request = publish_request(
        key,
        &service.withdrawal_registry,
        predecessor,
        staged.snapshot().head_digest,
    );
    service.publish(request).fixture("publish artifact");
    service
}
fn withdraw(registry: &DatasetWithdrawalRegistry, name: &str) -> DatasetWithdrawalRegistry {
    let mut next = registry.clone();
    next.append(DatasetWithdrawalNoticeV1 {
        notice_id: id(&format!("notice-{name}")),
        dataset_digest: digest(name),
        source_tombstone_digest: digest("tombstone"),
        authority_id: id("dataset-authority"),
        credential_chain_digest: digest("credential"),
        signing_key_digest: digest("dataset-key"),
        authority_epoch: 1,
        issued_at: 30,
    })
    .fixture("withdraw");
    next
}
fn state_request(
    service: &LearningArtifactOwnerService,
    key: &SigningKey,
    name: &str,
    transition: ArtifactOwnerStateTransitionV1,
    next: DatasetWithdrawalRegistry,
) -> LearningArtifactStatePublishRequestV1 {
    let intent = ArtifactOwnerStateIntentV1 {
        operation_id: id(name),
        transition,
        evaluator_id: id("independent-evaluator"),
        reason_digest: digest("reason"),
        expected_registry_predecessor_head: service.registry.snapshot().head_digest,
        expected_withdrawal_predecessor_head: service.withdrawal_registry.head_digest(),
        next_withdrawal_registry: next,
    };
    let staged = service
        .prepare_state_registry(&intent)
        .fixture("prepare without writes");
    let mut signed = service
        .host
        .discover_current_head(30)
        .fixture("discover")
        .fixture("current")
        .signed;
    if signed.witness.head_digest != staged.snapshot().head_digest {
        signed.witness.generation = signed.witness.generation.next().fixture("next generation");
        signed.witness.predecessor_head_digest = intent.expected_registry_predecessor_head;
        signed.witness.head_digest = staged.snapshot().head_digest;
        signed.witness.issued_at = 30;
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    }
    let mut request = LearningArtifactStatePublishRequestV1 {
        intent,
        signed_current_head: signed,
        now: 30,
        authorized_at: 30,
        authorization_expires_at: 1_000,
        state_authorization_signature: [0; 64],
    };
    request.state_authorization_signature =
        key.sign(&request.authorization_signing_bytes()).to_bytes();
    request
}

#[test]
fn withdrawal_publishes_current_retries_and_recovers_frontier() {
    let directory = TestDir::new();
    let key = key();
    let mut service = registered(&directory, &key);
    let request = state_request(
        &service,
        &key,
        "withdraw",
        ArtifactOwnerStateTransitionV1::InstallWithdrawalFrontier,
        withdraw(&service.withdrawal_registry, "dataset"),
    );
    let receipt = service
        .publish_state(request.clone())
        .fixture("publish withdrawal");
    assert_eq!(
        service.registry.state(&id("candidate")),
        Some(ArtifactState::Revoked)
    );
    assert!(
        !service
            .current_registry_view(30)
            .fixture("strict current")
            .is_eligible(&id("candidate"))
    );
    assert_eq!(
        service.publish_state(request).fixture("exact retry"),
        receipt
    );
    let current = service
        .host
        .discover_current_head(30)
        .fixture("discover")
        .fixture("current")
        .signed;
    drop(service);
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let reopened = LearningArtifactOwnerService::open_v2(LearningArtifactOwnerServiceConfigV2 {
        owner: LearningArtifactOwnerServiceConfigV1 {
            root: directory.0.clone(),
            trust: trust(&key, withdrawals.scope_digest().fixture("scope")),
            writer_lease: lease(&key, withdrawals.scope_digest().fixture("scope")),
            required_current_head: Some(current),
            withdrawal_registry: withdrawals,
            storage_binding: digest("binding"),
            now: 31,
        },
        required_withdrawal_head_digest: receipt.withdrawal_head_digest,
    })
    .fixture("recover independent withdrawal floor");
    assert_eq!(
        reopened.withdrawal_registry.head_digest(),
        receipt.withdrawal_head_digest
    );
    assert!(reopened.recovery_required.is_none());
}

#[test]
fn no_op_frontiers_advance_without_head_self_loops_and_reject_stale_operations() {
    let directory = TestDir::new();
    let key = key();
    let mut service = registered(&directory, &key);
    let original = service
        .host
        .discover_current_head(30)
        .fixture("head")
        .fixture("current")
        .signed;
    let stale = state_request(
        &service,
        &key,
        "stale",
        ArtifactOwnerStateTransitionV1::InstallWithdrawalFrontier,
        service.withdrawal_registry.clone(),
    );
    for name in ["unused-a", "unused-b"] {
        let request = state_request(
            &service,
            &key,
            name,
            ArtifactOwnerStateTransitionV1::InstallWithdrawalFrontier,
            withdraw(&service.withdrawal_registry, name),
        );
        service
            .publish_state(request)
            .fixture("advance unused source frontier");
        assert_eq!(
            service
                .host
                .discover_current_head(30)
                .fixture("head")
                .fixture("current")
                .signed,
            original
        );
    }
    let head = service.withdrawal_registry.head_digest();
    assert!(matches!(
        service.publish_state(stale),
        Err(LearningArtifactOwnerServiceError::WithdrawalFrontierConflict)
    ));
    assert_eq!(service.withdrawal_registry.head_digest(), head);
}

#[test]
fn quarantine_and_revoke_are_durable_and_require_independent_state_authorization() {
    let directory = TestDir::new();
    let key = key();
    let mut service = registered(&directory, &key);
    for (name, transition, expected) in [
        (
            "quarantine",
            ArtifactOwnerStateTransitionV1::Quarantine {
                artifact_id: id("candidate"),
            },
            ArtifactState::Quarantined,
        ),
        (
            "revoke",
            ArtifactOwnerStateTransitionV1::Revoke {
                artifact_id: id("candidate"),
            },
            ArtifactState::Revoked,
        ),
    ] {
        let request = state_request(
            &service,
            &key,
            name,
            transition,
            service.withdrawal_registry.clone(),
        );
        let mut bad = request.clone();
        bad.state_authorization_signature[0] ^= 1;
        let before = service.registry.snapshot();
        assert!(service.publish_state(bad).is_err());
        assert_eq!(service.registry.snapshot(), before);
        assert!(service.recovery_required.is_none());
        service
            .publish_state(request)
            .fixture("authorized restriction");
        assert_eq!(service.registry.state(&id("candidate")), Some(expected));
    }
}

#[test]
fn memory_only_withdrawal_and_uncommitted_backfill_are_rejected() {
    let directory = TestDir::new();
    let key = key();
    let mut service = opened(&directory, &key);
    assert!(matches!(
        service.install_withdrawal_frontier(withdraw(&service.withdrawal_registry, "dataset")),
        Err(LearningArtifactOwnerServiceError::DurableStatePublicationRequired)
    ));
    let admission = admit_manifest_at_withdrawal_head_v3(
        &service.withdrawal_registry,
        service.withdrawal_registry.head_digest(),
        manifest(),
        20,
    )
    .fixture("admit");
    let tx = service
        .host
        .begin_publication(
            id("operation"),
            admission.clone(),
            &service.withdrawal_registry,
            &service.registry,
            Digest32::ZERO,
            20,
        )
        .fixture("prepare");
    let mut staged = service.registry.clone();
    service
        .host
        .stage_compatibility_registration(&tx, &mut staged, 20)
        .fixture("stage");
    assert!(
        service
            .host
            .backfill_artifact_admission(&admission, &staged, digest("wrong-binding"), 20)
            .is_err()
    );
    assert_eq!(
        fs::read_dir(directory.0.join("admissions"))
            .fixture("admissions dir")
            .count(),
        0
    );
}

#[test]
fn backfill_restores_only_original_exact_published_admission() {
    let directory = TestDir::new();
    let key = key();
    let service = registered(&directory, &key);
    let admission = admit_manifest_at_withdrawal_head_v3(
        &service.withdrawal_registry,
        service.withdrawal_registry.head_digest(),
        manifest(),
        20,
    )
    .fixture("admit");
    let path = fs::read_dir(directory.0.join("admissions"))
        .fixture("dir")
        .next()
        .fixture("sidecar")
        .fixture("entry")
        .path();
    fs::remove_file(&path).fixture("simulate missing historical sidecar");
    assert!(service.current_registry_view(30).is_err());
    service
        .backfill_artifact_admission(&admission, 30)
        .fixture("exact backfill");
    assert!(
        service
            .current_registry_view(30)
            .fixture("strict restored")
            .is_eligible(&id("candidate"))
    );
    let mut altered = admission;
    altered.validated_manifest.manifest.expires_at += 1;
    assert!(service.backfill_artifact_admission(&altered, 30).is_err());
}

#[test]
fn interrupted_state_publication_recovers_exactly_and_fences_other_operations() {
    let directory = TestDir::new();
    let key = key();
    let mut service = registered(&directory, &key);
    let request = state_request(
        &service,
        &key,
        "interrupted",
        ArtifactOwnerStateTransitionV1::Revoke {
            artifact_id: id("candidate"),
        },
        service.withdrawal_registry.clone(),
    );
    let old = service
        .host
        .discover_current_head(30)
        .fixture("head")
        .fixture("current")
        .signed;
    let requirement = crate::RegistryHeadRequirementV1 {
        registry_id: id("learning-artifacts"),
        minimum_generation: Generation::new(1).fixture("generation"),
        expected_predecessor_head_digest: request
            .signed_current_head
            .witness
            .predecessor_head_digest,
        minimum_authority_epoch: 1,
        now: 30,
    };
    let witness =
        crate::validate_registry_head_witness(&request.signed_current_head.witness, &requirement)
            .fixture("witness");
    let blocker = directory.0.join("witnesses").join(format!(
        "{}-{}.witness",
        request.signed_current_head.witness.generation.get(),
        witness.witness_digest
    ));
    fs::create_dir(&blocker).fixture("inject witness failure");
    assert!(service.publish_state(request.clone()).is_err());
    assert_eq!(service.recovery_required(), Some(&id("interrupted")));
    let other = state_request(
        &service,
        &key,
        "other",
        ArtifactOwnerStateTransitionV1::Quarantine {
            artifact_id: id("candidate"),
        },
        service.withdrawal_registry.clone(),
    );
    assert!(matches!(
        service.publish_state(other),
        Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
    ));
    fs::remove_dir(&blocker).fixture("remove fault");
    drop(service);
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let mut reopened = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, withdrawals.scope_digest().fixture("scope")),
        writer_lease: lease(&key, withdrawals.scope_digest().fixture("scope")),
        required_current_head: Some(old),
        withdrawal_registry: withdrawals,
        storage_binding: digest("binding"),
        now: 31,
    })
    .fixture("recover interrupted");
    assert_eq!(reopened.recovery_required(), Some(&id("interrupted")));
    let mut retry = request;
    retry.now = 31;
    reopened.publish_state(retry).fixture("exact resume");
    assert_eq!(
        reopened.registry.state(&id("candidate")),
        Some(ArtifactState::Revoked)
    );
    assert!(reopened.recovery_required().is_none());
}

#[test]
fn forged_phase_records_cannot_substitute_for_missing_current_effects() {
    let directory = TestDir::new();
    let key = key();
    let mut service = registered(&directory, &key);
    let request = state_request(
        &service,
        &key,
        "phase-forgery",
        ArtifactOwnerStateTransitionV1::Revoke {
            artifact_id: id("candidate"),
        },
        service.withdrawal_registry.clone(),
    );
    service
        .publish_state(request.clone())
        .fixture("complete real state");
    let head_path = directory.0.join("heads").join(format!(
        "{}-{}.head",
        request.signed_current_head.witness.generation.get(),
        Digest32::of_bytes(&request.signed_current_head.signing_bytes())
    ));
    fs::remove_file(head_path).fixture("remove claimed current effect");
    assert!(
        service
            .host
            .recover_state_publication(&id("phase-forgery"))
            .is_err()
    );
    assert!(service.publish_state(request).is_err());
}

#[test]
fn state_header_cannot_lie_about_the_actual_registry_predecessor() {
    let directory = TestDir::new();
    let key = key();
    let mut service = registered(&directory, &key);
    let mut request = state_request(
        &service,
        &key,
        "lying-predecessor",
        ArtifactOwnerStateTransitionV1::Revoke {
            artifact_id: id("candidate"),
        },
        service.withdrawal_registry.clone(),
    );
    request.signed_current_head.witness.predecessor_head_digest = digest("different-chain");
    request.signed_current_head.signature = key
        .sign(&request.signed_current_head.signing_bytes())
        .to_bytes();
    request.state_authorization_signature =
        key.sign(&request.authorization_signing_bytes()).to_bytes();
    assert!(service.publish_state(request).is_err());
    assert_eq!(
        service.registry.state(&id("candidate")),
        Some(ArtifactState::Candidate)
    );
    assert!(service.recovery_required.is_none());
}

fn register_derived(
    service: &mut LearningArtifactOwnerService,
    key: &SigningKey,
    name: &str,
    generation: u64,
    parents: &[&str],
    dataset: &str,
) {
    let mut full = manifest();
    full.artifact_id = id(name);
    full.generation = Generation::new(generation).fixture("artifact generation");
    full.predecessor_ids = parents.iter().map(|name| id(name)).collect();
    full.source_dataset_digests = vec![digest(dataset)];
    let admission = admit_manifest_at_withdrawal_head_v3(
        &service.withdrawal_registry,
        service.withdrawal_registry.head_digest(),
        full,
        20,
    )
    .fixture("admit derived");
    let predecessor = service.registry.snapshot().head_digest;
    let preview = ArtifactPublicationTransactionV1::begin(
        id(&format!("publish-{name}")),
        admission.clone(),
        &service.withdrawal_registry,
        &service.registry,
        predecessor,
        20,
    )
    .fixture("preview derived");
    let mut staged = service.registry.clone();
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, 20)
        .fixture("stage derived");
    let mut head = service
        .host
        .discover_current_head(20)
        .fixture("head")
        .fixture("current")
        .signed;
    head.witness.generation = head
        .witness
        .generation
        .next()
        .fixture("next head generation");
    head.witness.predecessor_head_digest = predecessor;
    head.witness.head_digest = staged.snapshot().head_digest;
    head.signature = key.sign(&head.signing_bytes()).to_bytes();
    service
        .publish(LearningArtifactPublishRequestV1 {
            operation_id: id(&format!("publish-{name}")),
            admission,
            payload: b"payload".to_vec(),
            signed_current_head: head,
            expected_registry_predecessor_head: predecessor,
            now: 20,
        })
        .fixture("publish derived");
}

#[test]
fn withdrawing_the_second_parent_source_revokes_multi_parent_descendants() {
    let directory = TestDir::new();
    let key = key();
    let mut service = registered(&directory, &key);
    register_derived(&mut service, &key, "second", 1, &[], "second-dataset");
    register_derived(
        &mut service,
        &key,
        "child",
        2,
        &["candidate", "second"],
        "child-dataset",
    );
    register_derived(&mut service, &key, "leaf", 3, &["child"], "leaf-dataset");
    let request = state_request(
        &service,
        &key,
        "withdraw-second",
        ArtifactOwnerStateTransitionV1::InstallWithdrawalFrontier,
        withdraw(&service.withdrawal_registry, "second-dataset"),
    );
    service
        .publish_state(request)
        .fixture("revoke complete closure");
    assert_eq!(
        service.registry.state(&id("candidate")),
        Some(ArtifactState::Candidate)
    );
    for name in ["second", "child", "leaf"] {
        assert_eq!(
            service.registry.state(&id(name)),
            Some(ArtifactState::Revoked)
        );
    }
    let current = service.current_registry_view(30).fixture("strict view");
    assert!(current.is_eligible(&id("candidate")));
    assert!(!current.is_eligible(&id("child")));
}

fn bootstrap_request(
    service: &LearningArtifactOwnerService,
    key: &SigningKey,
    name: &str,
    next: DatasetWithdrawalRegistry,
) -> crate::LearningArtifactWithdrawalBootstrapRequestV1 {
    let mut request = crate::LearningArtifactWithdrawalBootstrapRequestV1 {
        operation_id: id(name),
        registry_id: id("learning-artifacts"),
        binding: digest("binding"),
        expected_withdrawal_head: service.withdrawal_registry.head_digest(),
        next_withdrawal_registry: next,
        signer_id: id("owner-authority"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: 1,
        issued_at: 30,
        expires_at: 90,
        signature: [0; 64],
    };
    request.signature = key.sign(&request.signing_bytes()).to_bytes();
    request
}

#[test]
fn signed_bootstrap_persists_before_first_current_and_blocks_withdrawn_admission() {
    let directory = TestDir::new();
    let signing = key();
    let mut service = opened(&directory, &signing);
    let next = withdraw(&service.withdrawal_registry, "dataset");
    let request = bootstrap_request(&service, &signing, "bootstrap", next);
    let receipt = service
        .publish_withdrawal_bootstrap(request.clone(), 30)
        .fixture("bootstrap");
    assert_eq!(
        service
            .publish_withdrawal_bootstrap(request, 31)
            .fixture("retry"),
        receipt
    );
    assert!(
        service
            .host
            .discover_current_head(31)
            .fixture("head")
            .is_none()
    );
    drop(service);
    let service = opened(&directory, &signing);
    assert_eq!(
        service.withdrawal_registry.head_digest(),
        receipt.withdrawal_receipt.head_digest
    );
    assert!(
        admit_manifest_at_withdrawal_head_v3(
            &service.withdrawal_registry,
            service.withdrawal_registry.head_digest(),
            manifest(),
            31
        )
        .is_err()
    );
}

#[test]
fn bootstrap_rejects_forged_and_stale_authorizations_without_rolling_back() {
    let directory = TestDir::new();
    let signing = key();
    let mut service = opened(&directory, &signing);
    let first = bootstrap_request(
        &service,
        &signing,
        "first",
        withdraw(&service.withdrawal_registry, "unrelated"),
    );
    let stale = bootstrap_request(
        &service,
        &signing,
        "stale",
        withdraw(&service.withdrawal_registry, "other"),
    );
    let mut forged = first.clone();
    forged.binding = digest("forged");
    assert!(service.publish_withdrawal_bootstrap(forged, 30).is_err());
    let receipt = service
        .publish_withdrawal_bootstrap(first, 30)
        .fixture("first");
    assert!(service.publish_withdrawal_bootstrap(stale, 30).is_err());
    assert_eq!(
        service.withdrawal_registry.head_digest(),
        receipt.withdrawal_receipt.head_digest
    );
}

#[test]
fn bootstrap_acknowledgement_cannot_recover_without_exact_snapshot() {
    let directory = TestDir::new();
    let signing = key();
    let mut service = opened(&directory, &signing);
    let request = bootstrap_request(
        &service,
        &signing,
        "bootstrap",
        withdraw(&service.withdrawal_registry, "unrelated"),
    );
    let receipt = service
        .publish_withdrawal_bootstrap(request, 30)
        .fixture("bootstrap");
    drop(service);
    fs::remove_file(directory.0.join("withdrawals").join(format!(
        "{}-{}.snapshot",
        receipt.withdrawal_receipt.head_digest, receipt.withdrawal_receipt.file_digest
    )))
    .fixture("remove snapshot");
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    assert!(
        LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
            root: directory.0.clone(),
            trust: trust(&signing, scope_digest),
            writer_lease: lease(&signing, scope_digest),
            required_current_head: None,
            withdrawal_registry: withdrawals,
            storage_binding: digest("binding"),
            now: 30
        })
        .is_err()
    );
}
