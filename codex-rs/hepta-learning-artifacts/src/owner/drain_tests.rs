//! Draining preserves the existing owner and its recovery state.

use super::*;

use pretty_assertions::assert_eq;

fn config(
    directory: &TestDir,
    key: &SigningKey,
    withdrawals: &DatasetWithdrawalRegistry,
) -> LearningArtifactOwnerServiceConfigV1 {
    let scope_digest = withdrawals.scope_digest().fixture("scope digest");
    LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(key, scope_digest),
        writer_lease: lease(key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    }
}

fn request_for(
    service: &LearningArtifactOwnerService,
    key: &SigningKey,
    withdrawals: &DatasetWithdrawalRegistry,
) -> LearningArtifactPublishRequestV1 {
    let mut staged = service.registry().clone();
    let predecessor = staged.snapshot().head_digest;
    let admission =
        admit_manifest_at_withdrawal_head_v3(withdrawals, withdrawals.head_digest(), manifest(), 20)
            .fixture("preview admission");
    let preview = ArtifactPublicationTransactionV1::begin(
        id("operation"),
        admission,
        withdrawals,
        &staged,
        predecessor,
        20,
    )
    .fixture("preview transaction");
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, 20)
        .fixture("preview registry");
    publish_request(key, withdrawals, predecessor, staged.snapshot().head_digest)
}

#[test]
fn drain_rejects_new_publication_without_creating_prepared() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    let request = request_for(&service, &key, &withdrawals);
    let head = service.registry().snapshot().head_digest;
    assert!(!service.is_drained());
    service.begin_drain();
    service.begin_drain();
    assert!(service.is_drained());
    assert!(matches!(
        service.publish(request.clone()),
        Err(LearningArtifactOwnerServiceError::Draining)
    ));
    assert!(
        service
            .host
            .recover_publication(&request.operation_id)
            .fixture("no new checkpoint")
            .is_none()
    );
    assert_eq!(service.registry().snapshot().head_digest, head);
    assert!(service.is_drained());
}

#[test]
fn drain_serves_exact_terminal_receipt_without_reopening_admission() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    let request = request_for(&service, &key, &withdrawals);
    let receipt = service.publish(request.clone()).fixture("publish");
    service.begin_drain();
    assert_eq!(
        service.publish(request.clone()).fixture("historical receipt"),
        receipt
    );
    let mut altered = request.clone();
    altered.payload[0] ^= 1;
    assert!(service.publish(altered).is_err());
    let mut unrelated = request;
    unrelated.operation_id = id("unrelated");
    assert!(matches!(
        service.publish(unrelated),
        Err(LearningArtifactOwnerServiceError::Draining)
    ));
    assert!(service.is_drained());
    assert_eq!(
        service.registry().snapshot().head_digest,
        receipt.registry_head_digest
    );
}

#[test]
fn drain_resumes_only_pending_publication_and_keeps_writer_fence() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    let request = request_for(&service, &key, &withdrawals);
    let _prepared = service
        .host
        .begin_publication(
            request.operation_id.clone(),
            request.admission.clone(),
            &withdrawals,
            service.registry(),
            request.expected_registry_predecessor_head,
            request.now,
        )
        .fixture("durable Prepared before restart");
    drop(service);
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("recover pending publication");
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
    service.begin_drain();
    assert!(!service.is_drained());
    let mut unrelated = request.clone();
    unrelated.operation_id = id("unrelated");
    assert!(matches!(
        service.publish(unrelated),
        Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
    ));
    let receipt = service
        .publish(request.clone())
        .fixture("resume pending publication");
    assert!(service.is_drained());
    assert_eq!(service.publish(request).fixture("exact replay"), receipt);
    assert!(LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals)).is_err());
    drop(service);
    assert!(LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals)).is_ok());
}

#[test]
fn corrupt_checkpoint_never_becomes_drained() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    let request = request_for(&service, &key, &withdrawals);
    let path = directory.0.join("transactions").join(format!(
        "{}-0.checkpoint",
        Digest32::of_bytes(request.operation_id.as_str().as_bytes())
    ));
    fs::write(path, b"truncated").fixture("inject uncertain checkpoint");
    assert!(service.publish(request.clone()).is_err());
    service.begin_drain();
    assert!(!service.is_drained());
    assert!(service.publish(request).is_err());
    assert!(!service.is_drained());
    assert!(matches!(
        service.current_registry_view(20),
        Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
    ));
}

#[cfg(unix)]
#[test]
fn durable_drain_survives_restart_and_remains_idempotent() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    let request = request_for(&service, &key, &withdrawals);
    service.begin_drain_durable().fixture("durable stop");
    let path = directory.0.join("writer/DRAIN.v1");
    let original = fs::read(&path).fixture("read stop");
    service.begin_drain_durable().fixture("exact stop retry");
    assert_eq!(fs::read(&path).fixture("read retry"), original);
    drop(service);
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("reopen stopped service");
    assert!(service.durable_drain_requested());
    assert!(service.is_drained());
    assert!(matches!(
        service.publish(request.clone()),
        Err(LearningArtifactOwnerServiceError::Draining)
    ));
    assert!(
        service.host.recover_publication(&request.operation_id)
            .fixture("no Prepared").is_none()
    );
}

#[cfg(unix)]
#[test]
fn every_truncated_drain_record_rejects_startup() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    service.begin_drain_durable().fixture("durable stop");
    drop(service);
    let path = directory.0.join("writer/DRAIN.v1");
    let bytes = fs::read(&path).fixture("read stop");
    for end in 0..bytes.len() {
        fs::write(&path, &bytes[..end]).fixture("truncate stop");
        assert!(
            LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals)).is_err(),
            "truncation at {end} reopened admission"
        );
    }
    fs::write(&path, &bytes).fixture("restore exact test fixture");
    let mut foreign = config(&directory, &key, &withdrawals);
    foreign.storage_binding = digest("another binding");
    assert!(LearningArtifactOwnerService::open(foreign).is_err());
    let service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("reopen canonical stop");
    assert!(service.is_drained());
}

#[cfg(unix)]
#[test]
fn failed_durable_stop_never_acknowledges_drain_or_reopens_admission() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    let request = request_for(&service, &key, &withdrawals);
    fs::create_dir(directory.0.join("writer/DRAIN.v1")).fixture("inject invalid record type");
    assert!(service.begin_drain_durable().is_err());
    assert!(!service.durable_drain_requested());
    assert!(!service.is_drained());
    assert!(matches!(
        service.publish(request),
        Err(LearningArtifactOwnerServiceError::Draining)
    ));
    service.begin_drain();
    assert!(!service.is_drained());
    drop(service);
    assert!(LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals)).is_err());
}

#[test]
fn wrong_signed_head_is_rejected_before_prepared() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    let mut request = request_for(&service, &key, &withdrawals);
    request.signed_current_head.witness.head_digest = digest("wrong proposed registry");
    request.signed_current_head.signature = key
        .sign(&request.signed_current_head.signing_bytes()).to_bytes();
    assert!(service.publish(request.clone()).is_err());
    assert!(service.host.recover_publication(&request.operation_id)
        .fixture("no Prepared for rejected head").is_none());
    assert!(service.recovery_required().is_none());
}

#[test]
fn recovered_payload_is_reopened_before_publication_advances() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    let request = request_for(&service, &key, &withdrawals);
    let mut transaction = service.host.begin_publication(
        request.operation_id.clone(),
        request.admission.clone(),
        &withdrawals,
        service.registry(),
        request.expected_registry_predecessor_head,
        request.now,
    ).fixture("prepare");
    let mut staged = service.registry().clone();
    service.host.stage_compatibility_registration(&transaction, &mut staged, 20).fixture("stage");
    let path = service.host.ensure_payload_durable(
        &mut transaction, &staged, &request.payload, 20,
    ).fixture("payload phase");
    drop(service);
    fs::write(directory.0.join(path), b"damaged").fixture("inject post-checkpoint corruption");
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("recover pending publication");
    assert!(service.publish(request.clone()).is_err());
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
    assert_eq!(
        service.host.recover_publication(&request.operation_id)
            .fixture("checkpoint").fixture("present").checkpoint.phase,
        ArtifactPublicationPhaseV1::PayloadDurable
    );
    service.begin_drain();
    assert!(!service.is_drained());
}

#[cfg(unix)]
#[test]
fn durable_stop_survives_sigkill() {
    use std::process::Child;
    use std::process::Command;
    use std::time::Duration;
    use std::time::Instant;

    const CHILD_ROOT: &str = "HEPTA_ARTIFACT_R3_STOP_CHILD_ROOT";
    if let Some(root) = std::env::var_os(CHILD_ROOT) {
        let directory = TestDir(PathBuf::from(root));
        let key = key();
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
        let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
            .fixture("child open");
        service.begin_drain_durable().fixture("child durable stop");
        fs::write(directory.0.join("child-ready"), b"durable").fixture("child ready");
        loop {
            std::thread::sleep(Duration::from_millis(50));
        }
    }

    struct ChildGuard(Child);
    impl Drop for ChildGuard {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    let directory = TestDir::new();
    let mut child = ChildGuard(
        Command::new(std::env::current_exe().fixture("test executable"))
            .arg("--exact")
            .arg("owner_service::tests::drain::durable_stop_survives_sigkill")
            .arg("--nocapture")
            .env(CHILD_ROOT, &directory.0)
            .spawn().fixture("spawn real writer child")
    );
    let started = Instant::now();
    while !directory.0.join("child-ready").exists() {
        assert!(
            child.0.try_wait().fixture("child status").is_none(),
            "child exited before stop"
        );
        assert!(started.elapsed() < Duration::from_secs(15), "child readiness timeout");
        std::thread::sleep(Duration::from_millis(10));
    }
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    assert!(LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals)).is_err());
    child.0.kill().fixture("kill writer without destructors");
    assert!(!child.0.wait().fixture("observe exit").success());
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("reopen after killed writer");
    assert!(service.durable_drain_requested());
    assert!(service.is_drained());
    let request = request_for(&service, &key, &withdrawals);
    assert!(matches!(
        service.publish(request),
        Err(LearningArtifactOwnerServiceError::Draining)
    ));
}
