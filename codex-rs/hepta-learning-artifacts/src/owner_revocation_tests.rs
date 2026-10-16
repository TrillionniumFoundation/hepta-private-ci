use super::tests::*;
use super::*;
use crate::ArtifactState;
use crate::StateChange;
use crate::test_support::FixtureValue;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use std::sync::atomic::Ordering;

pub(super) fn published() -> (
    TestDir,
    LearningArtifactOwnerServiceConfigV1,
    LearningArtifactOwnerService,
    LearningArtifactRevokeRequestV1,
) {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let config = LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    };
    let mut service = LearningArtifactOwnerService::open(config.clone()).fixture("open");
    let mut request = publish_request(&key, &withdrawals, Digest32::ZERO, digest("pending"));
    let preview = ArtifactPublicationTransactionV1::begin(
        request.operation_id.clone(),
        request.admission.clone(),
        &withdrawals,
        service.registry(),
        Digest32::ZERO,
        /*now*/ 20,
    )
    .fixture("preview");
    let mut staged = service.registry().clone();
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, /*now*/ 20)
        .fixture("stage");
    request.signed_current_head.witness.head_digest = staged.snapshot().head_digest;
    request.signed_current_head.signature = key
        .sign(&request.signed_current_head.signing_bytes())
        .to_bytes();
    service.publish(request.clone()).fixture("publish");
    let change = StateChange {
        event_id: id("withdraw-candidate"),
        artifact_id: id("candidate"),
        evaluator_id: id("owner-authority"),
        reason_digest: digest("withdrawal decision"),
    };
    let predecessor = staged.snapshot().head_digest;
    staged
        .append(crate::ArtifactEvent::Revoke(change.clone()))
        .fixture("revoke preview");
    let mut signed = request.signed_current_head;
    signed.witness.generation = Generation::new(/*value*/ 2).fixture("generation");
    signed.witness.predecessor_head_digest = predecessor;
    signed.witness.head_digest = staged.snapshot().head_digest;
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let revoke = LearningArtifactRevokeRequestV1 {
        operation_id: change.event_id.clone(),
        change,
        signed_current_head: signed,
        expected_registry_predecessor_head: predecessor,
        now: 20,
    };
    (directory, config, service, revoke)
}

#[test]
fn named_revoke_is_durable_idempotent_and_restart_retains_independent_signed_head() {
    let (_directory, mut config, mut service, request) = published();
    let receipt = service.revoke(request.clone()).fixture("revoke");
    assert_eq!(
        service.registry().state(&request.change.artifact_id),
        Some(ArtifactState::Revoked)
    );
    assert!(!service.registry().is_eligible(&request.change.artifact_id));
    assert_eq!(
        service.revoke(request.clone()).fixture("exact retry"),
        receipt
    );
    config.required_current_head = Some(request.signed_current_head.clone());
    drop(service);
    let mut reopened = LearningArtifactOwnerService::open(config).fixture("anchored reopen");
    assert_eq!(
        reopened.revoke(request.clone()).fixture("restart retry"),
        receipt
    );
    assert_eq!(
        reopened.registry().state(&request.change.artifact_id),
        Some(ArtifactState::Revoked)
    );
    assert!(reopened.current_registry_view(/*now*/ 20).is_ok());
}

#[test]
fn revocation_ack_sync_uncertainty_blocks_readers_and_unrelated_writes_until_exact_sync() {
    let (_directory, mut config, mut service, request) = published();
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    let reader = {
        let anchor = service
            .host
            .discover_current_head(/*now*/ 20)
            .fixture("anchor")
            .fixture("published anchor");
        let reader = crate::ArtifactOwnerCurrentReaderV1::open(
            &config.root,
            config.trust.clone(),
            anchor.signed,
        )
        .fixture("live reader");
        assert!(
            reader
                .current_registry_view(/*now*/ 20)
                .fixture("read alongside live writer")
                .registry()
                .is_eligible(&request.change.artifact_id)
        );
        reader
    };
    let probe = std::fs::OpenOptions::new()
        .read(/*read*/ true)
        .write(/*write*/ true)
        .open(config.root.join("writer/current-observation.lock"))
        .fixture("observation lock");
    probe
        .try_lock_shared()
        .fixture("independent current reader");
    assert!(matches!(
        service.revoke(request.clone()),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::CurrentObservationBusy
        ))
    ));
    assert!(service.recovery_required().is_none());
    probe.unlock().fixture("release current reader");
    service
        .host
        .acknowledgement_sync_fault
        .store(/*val*/ true, Ordering::Relaxed);
    assert!(matches!(
        service.revoke(request.clone()),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::Indeterminate
        ))
    ));
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
    assert!(service.current_registry_view(/*now*/ 20).is_err());
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    assert!(matches!(
        reader.current_registry_view(/*now*/ 20),
        Err(ArtifactOwnerHostError::CurrentObservationBusy)
    ));
    assert!(matches!(
        probe.try_lock_shared(),
        Err(std::fs::TryLockError::WouldBlock)
    ));
    let mut unrelated = request.clone();
    unrelated.operation_id = id("unrelated");
    assert!(matches!(
        service.revoke(unrelated),
        Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
    ));
    service
        .host
        .acknowledgement_sync_fault
        .store(/*val*/ true, Ordering::Relaxed);
    assert!(service.revoke(request.clone()).is_err());
    assert!(service.current_registry_view(/*now*/ 20).is_err());
    let receipt = service.revoke(request.clone()).fixture("actual ack sync");
    probe
        .try_lock_shared()
        .fixture("settled writer releases observation lock");
    probe.unlock().fixture("release observation");
    assert_eq!(
        service.registry().snapshot().head_digest,
        receipt.registry_head_digest
    );
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    {
        let view = reader
            .current_registry_view(/*now*/ 20)
            .fixture("cached reader observes live revoke");
        assert_eq!(
            view.registry().state(&request.change.artifact_id),
            Some(ArtifactState::Revoked)
        );
        assert_eq!(view.receipt().head_digest, receipt.registry_head_digest);
    }
    config.required_current_head = Some(request.signed_current_head);
    drop(service);
    let reopened = LearningArtifactOwnerService::open(config).fixture("reopen synced revoke");
    assert_eq!(
        reopened.registry().state(&request.change.artifact_id),
        Some(ArtifactState::Revoked)
    );
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    assert_eq!(
        reader
            .current_registry_view(/*now*/ 20)
            .fixture("cached reader survives writer reopen")
            .receipt()
            .head_digest,
        receipt.registry_head_digest
    );
}

#[cfg(any(target_os = "linux", target_os = "macos"))]
#[test]
fn bounded_current_reader_wait_finishes_when_live_owner_exact_retry_settles() {
    let (_directory, config, mut service, request) = published();
    let anchor = service
        .host
        .discover_current_head(/*now*/ 20)
        .fixture("anchor")
        .fixture("published anchor");
    let reader =
        crate::ArtifactOwnerCurrentReaderV1::open(&config.root, config.trust, anchor.signed)
            .fixture("reader");
    service
        .host
        .acknowledgement_sync_fault
        .store(/*val*/ true, Ordering::Relaxed);
    assert!(matches!(
        service.revoke(request.clone()),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::Indeterminate
        ))
    ));
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(/*n*/ 2));
    let retry_barrier = barrier.clone();
    let publisher = std::thread::spawn(move || {
        retry_barrier.wait();
        std::thread::sleep(std::time::Duration::from_millis(/*millis*/ 10));
        let receipt = service
            .revoke(request)
            .fixture("independent owner exact retry");
        (service, receipt)
    });
    barrier.wait();
    let view = reader
        .current_registry_view(/*now*/ 20)
        .fixture("bounded retry observes settled current");
    let (_service, receipt) = publisher.join().fixture("publisher joined");
    assert_eq!(view.receipt().head_digest, receipt.registry_head_digest);
    assert_eq!(
        view.registry().state(&receipt.change.artifact_id),
        Some(ArtifactState::Revoked)
    );
}

#[test]
fn revocation_refuses_self_evaluation_wrong_key_stale_head_and_changed_reason() {
    for mode in ["self", "key", "head", "reason", "expired", "operation"] {
        let (_directory, _config, mut service, mut request) = published();
        let before = service.registry().snapshot();
        match mode {
            "self" => request.change.evaluator_id = id("trainer"),
            "key" => request.signed_current_head.signature = [0; 64],
            "head" => request.expected_registry_predecessor_head = digest("wrong predecessor"),
            "reason" => request.change.reason_digest = digest("unsigned reason"),
            "expired" => request.now = 1_001,
            "operation" => request.operation_id = id("unsigned-operation"),
            _ => unreachable!(),
        }
        assert!(service.revoke(request).is_err());
        assert_eq!(service.registry().snapshot(), before);
        assert!(service.recovery_required().is_none());
    }
}

#[test]
fn revocation_reopens_each_durable_crash_cut_without_unfencing_unrelated_work() {
    for phase in [
        ArtifactPublicationPhaseV1::Prepared,
        ArtifactPublicationPhaseV1::RegistryDurable,
        ArtifactPublicationPhaseV1::WitnessDurable,
        ArtifactPublicationPhaseV1::Acknowledged,
    ] {
        let (_directory, mut config, mut service, request) = published();
        *service
            .host
            .revocation_checkpoint_sync_fault
            .lock()
            .fixture("fault lock") = Some(phase);
        assert!(matches!(
            service.revoke(request.clone()),
            Err(LearningArtifactOwnerServiceError::Host(
                ArtifactOwnerHostError::Indeterminate
            ))
        ));
        assert!(service.current_registry_view(/*now*/ 20).is_err());
        let observed = service
            .host
            .discover_current_head(/*now*/ 20)
            .fixture("observed current")
            .fixture("current");
        config.required_current_head = Some(observed.signed);
        drop(service);
        let mut reopened = LearningArtifactOwnerService::open(config).fixture("reopen crash cut");
        if phase != ArtifactPublicationPhaseV1::Acknowledged {
            assert_eq!(reopened.recovery_required(), Some(&request.operation_id));
            assert!(reopened.current_registry_view(/*now*/ 20).is_err());
        }
        let receipt = reopened
            .revoke(request.clone())
            .fixture("exact recovered revoke");
        assert_eq!(
            reopened.registry().state(&request.change.artifact_id),
            Some(ArtifactState::Revoked)
        );
        assert_eq!(
            reopened.registry().snapshot().head_digest,
            receipt.registry_head_digest
        );
        assert!(reopened.current_registry_view(/*now*/ 20).is_ok());
    }
}

#[test]
fn actual_owner_revoke_makes_published_descendant_ineligible() {
    let (_directory, config, mut service, mut request) = published();
    let key = key();
    let mut child = manifest();
    child.artifact_id = id("child-candidate");
    child.generation = Generation::new(/*value*/ 2).fixture("generation");
    child.predecessor_ids = vec![id("candidate")];
    child.rollback_predecessor = Some(id("candidate"));
    let admission = crate::admit_manifest_at_withdrawal_head_v3(
        &config.withdrawal_registry,
        config.withdrawal_registry.head_digest(),
        child,
        /*now*/ 20,
    )
    .fixture("child admission");
    let predecessor = service.registry().snapshot().head_digest;
    let preview = ArtifactPublicationTransactionV1::begin(
        id("child-publication"),
        admission.clone(),
        &config.withdrawal_registry,
        service.registry(),
        predecessor,
        /*now*/ 20,
    )
    .fixture("preview child");
    let mut staged = service.registry().clone();
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, /*now*/ 20)
        .fixture("stage child");
    let mut signed = request.signed_current_head.clone();
    signed.witness.head_digest = staged.snapshot().head_digest;
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    service
        .publish(LearningArtifactPublishRequestV1 {
            operation_id: id("child-publication"),
            admission,
            payload: b"payload".to_vec(),
            signed_current_head: signed,
            expected_registry_predecessor_head: predecessor,
            now: 20,
        })
        .fixture("publish child");
    request.expected_registry_predecessor_head = staged.snapshot().head_digest;
    staged
        .append(crate::ArtifactEvent::Revoke(request.change.clone()))
        .fixture("stage parent revocation");
    request.signed_current_head.witness.generation =
        Generation::new(/*value*/ 3).fixture("next generation");
    request.signed_current_head.witness.predecessor_head_digest =
        request.expected_registry_predecessor_head;
    request.signed_current_head.witness.head_digest = staged.snapshot().head_digest;
    request.signed_current_head.signature = key
        .sign(&request.signed_current_head.signing_bytes())
        .to_bytes();
    service.revoke(request).fixture("revoke ancestor");
    assert!(!service.registry().is_eligible(&id("child-candidate")));
    assert!(service.current_registry_view(/*now*/ 20).is_ok());
}

#[test]
fn historical_revoke_retry_preserves_later_current_and_bad_retry_cannot_fence_it() {
    let (_directory, config, mut service, request) = published();
    let first = service.revoke(request.clone()).fixture("first revocation");
    let key = key();
    let mut other = manifest();
    other.artifact_id = id("unrelated-model");
    let admission = crate::admit_manifest_at_withdrawal_head_v3(
        &config.withdrawal_registry,
        config.withdrawal_registry.head_digest(),
        other,
        /*now*/ 20,
    )
    .fixture("unrelated admission");
    let predecessor = service.registry().snapshot().head_digest;
    let preview = ArtifactPublicationTransactionV1::begin(
        id("unrelated-publication"),
        admission.clone(),
        &config.withdrawal_registry,
        service.registry(),
        predecessor,
        /*now*/ 20,
    )
    .fixture("preview unrelated");
    let mut staged = service.registry().clone();
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, /*now*/ 20)
        .fixture("stage unrelated");
    let mut signed = request.signed_current_head.clone();
    signed.witness.generation = Generation::new(/*value*/ 3).fixture("head generation");
    signed.witness.predecessor_head_digest = predecessor;
    signed.witness.head_digest = staged.snapshot().head_digest;
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let newer = service
        .publish(LearningArtifactPublishRequestV1 {
            operation_id: id("unrelated-publication"),
            admission,
            payload: b"payload".to_vec(),
            signed_current_head: signed,
            expected_registry_predecessor_head: predecessor,
            now: 20,
        })
        .fixture("publish unrelated");
    assert_eq!(
        service.revoke(request.clone()).fixture("historical retry"),
        first
    );
    assert_eq!(
        service.registry().snapshot().head_digest,
        newer.registry_head_digest
    );
    let mut bad = request;
    bad.change.reason_digest = digest("unsigned replacement");
    assert!(service.revoke(bad).is_err());
    assert!(service.recovery_required().is_none());
    assert_eq!(
        service
            .current_registry_view(/*now*/ 20)
            .fixture("current remains readable")
            .receipt()
            .head_digest,
        newer.registry_head_digest
    );
}
