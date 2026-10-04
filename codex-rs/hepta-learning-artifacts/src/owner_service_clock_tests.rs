use super::tests::*;
use super::*;
use crate::test_support::FixtureValue;

fn publication_fixture() -> (
    TestDir,
    LearningArtifactOwnerService,
    LearningArtifactPublishRequestV1,
) {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    })
    .fixture("real owner");
    let admission = crate::admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest(),
        20,
    )
    .fixture("admission");
    let preview = service
        .preview_registered_head(id("operation"), admission, 20)
        .fixture("actual head");
    let request = publish_request(&key, &withdrawals, preview.predecessor, preview.head_digest);
    (directory, service, request)
}

#[test]
fn publication_clock_rejects_expiry_after_real_payload_checkpoint() {
    let (directory, mut service, request) = publication_fixture();
    let payload = directory.0.join("payloads").join(format!(
        "{}-{}.bin",
        request.admission.validated_manifest.manifest.artifact_id,
        request.admission.validated_manifest.manifest.bytes_digest
    ));
    let mut clock = || Ok(if payload.exists() { 1_001 } else { 20 });
    let result = service.publish_with_clock(request.clone(), &mut clock);
    assert!(
        result.is_err(),
        "EXPIRED_AFTER_PAYLOAD_PUBLICATION_ACKNOWLEDGED: {result:?}"
    );
    assert!(payload.is_file());
    let recovered = service
        .host
        .recover_publication(&request.operation_id)
        .fixture("original recovery")
        .fixture("original checkpoint");
    assert_eq!(
        recovered.checkpoint.phase,
        ArtifactPublicationPhaseV1::PayloadDurable
    );
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
    assert_eq!(
        service.registry().head_digest(),
        request.expected_registry_predecessor_head
    );
    assert!(
        service
            .host
            .discover_current_head(20)
            .fixture("no current")
            .is_none()
    );
}

#[test]
fn publication_clock_rejects_expiry_after_real_registry_checkpoint() {
    let (directory, mut service, request) = publication_fixture();
    let mut clock = || {
        let written = std::fs::read_dir(directory.0.join("registries"))
            .fixture("registry directory")
            .next()
            .is_some();
        Ok(if written { 1_001 } else { 20 })
    };
    assert!(
        service
            .publish_with_clock(request.clone(), &mut clock)
            .is_err()
    );
    let recovered = service
        .host
        .recover_publication(&request.operation_id)
        .fixture("recovery")
        .fixture("checkpoint");
    assert_eq!(
        recovered.checkpoint.phase,
        ArtifactPublicationPhaseV1::RegistryDurable
    );
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
    assert!(
        service
            .host
            .discover_current_head(20)
            .fixture("no current")
            .is_none()
    );
}

#[test]
fn publication_clock_rejects_expiry_after_real_witness_without_erasing_current() {
    let (directory, mut service, request) = publication_fixture();
    let mut clock = || {
        let written = std::fs::read_dir(directory.0.join("heads"))
            .fixture("head directory")
            .next()
            .is_some();
        Ok(if written { 1_001 } else { 20 })
    };
    assert!(
        service
            .publish_with_clock(request.clone(), &mut clock)
            .is_err()
    );
    let recovered = service
        .host
        .recover_publication(&request.operation_id)
        .fixture("recovery")
        .fixture("checkpoint");
    assert_eq!(
        recovered.checkpoint.phase,
        ArtifactPublicationPhaseV1::WitnessDurable
    );
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
    let current = service
        .host
        .discover_current_head(20)
        .fixture("historical current")
        .fixture("signed head already durable");
    assert_eq!(current.signed, request.signed_current_head);
    assert!(service.host.discover_current_head(1_001).is_err());
}

#[test]
fn publication_clock_failure_preserves_payload_and_exact_recovery() {
    let (directory, mut service, request) = publication_fixture();
    let mut clock = || {
        let written = std::fs::read_dir(directory.0.join("payloads"))
            .fixture("payload directory")
            .next()
            .is_some();
        if written {
            Err(LearningArtifactOwnerServiceError::ClockUnavailable)
        } else {
            Ok(20)
        }
    };
    assert!(matches!(
        service.publish_with_clock(request.clone(), &mut clock),
        Err(LearningArtifactOwnerServiceError::ClockUnavailable)
    ));
    let original = service
        .host
        .recover_publication(&request.operation_id)
        .fixture("recovery")
        .fixture("checkpoint")
        .checkpoint;
    assert_eq!(original.phase, ArtifactPublicationPhaseV1::PayloadDurable);
    let mut unrelated = request.clone();
    unrelated.operation_id = id("unrelated");
    assert!(matches!(
        service.publish_with_clock(unrelated, &mut || Ok(21)),
        Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
    ));
    let receipt = service
        .publish_with_clock(request.clone(), &mut || Ok(21))
        .fixture("same original operation resumes");
    assert_eq!(receipt.operation_id, request.operation_id);
    assert_eq!(receipt.admission_digest, original.admission_digest);
    assert_eq!(receipt.acknowledged_at, 21);
    assert!(service.recovery_required().is_none());
}

#[test]
fn publication_clock_rejects_regression_and_preserves_partial_identity() {
    let (directory, mut service, request) = publication_fixture();
    let mut clock = || {
        let written = std::fs::read_dir(directory.0.join("payloads"))
            .fixture("payload directory")
            .next()
            .is_some();
        Ok(if written { 19 } else { 20 })
    };
    assert!(matches!(
        service.publish_with_clock(request.clone(), &mut clock),
        Err(LearningArtifactOwnerServiceError::ClockRegression)
    ));
    let recovered = service
        .host
        .recover_publication(&request.operation_id)
        .fixture("recovery")
        .fixture("checkpoint");
    assert_eq!(
        recovered.checkpoint.phase,
        ArtifactPublicationPhaseV1::PayloadDurable
    );
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
}

#[test]
fn publication_clock_terminal_replay_never_samples_or_readmits() {
    let (_directory, mut service, mut request) = publication_fixture();
    let receipt = service
        .publish_with_clock(request.clone(), &mut || Ok(20))
        .fixture("original durable ACK");
    request.now = 1_001;
    let mut calls = 0;
    let retry = service
        .publish_with_clock(request, &mut || {
            calls += 1;
            Err(LearningArtifactOwnerServiceError::ClockUnavailable)
        })
        .fixture("historical terminal retry");
    assert_eq!(retry, receipt);
    assert_eq!(calls, 0);
}

#[test]
fn publication_clock_expired_entry_has_no_checkpoint_or_recovery_fence() {
    let (_directory, mut service, request) = publication_fixture();
    assert!(
        service
            .publish_with_clock(request.clone(), &mut || Ok(1_001))
            .is_err()
    );
    assert!(
        service
            .host
            .recover_publication(&request.operation_id)
            .fixture("no mutation")
            .is_none()
    );
    assert!(service.recovery_required().is_none());
}

#[test]
fn publication_clock_rejects_backward_sample_above_original_request_floor() {
    let (directory, mut service, request) = publication_fixture();
    assert_eq!(request.now, 20);
    let mut clock = || {
        let written = std::fs::read_dir(directory.0.join("payloads"))
            .fixture("payload directory")
            .next()
            .is_some();
        Ok(if written { 25 } else { 30 })
    };
    assert!(matches!(
        service.publish_with_clock(request.clone(), &mut clock),
        Err(LearningArtifactOwnerServiceError::ClockRegression)
    ));
    let recovered = service
        .host
        .recover_publication(&request.operation_id)
        .fixture("recovery")
        .fixture("checkpoint");
    assert_eq!(
        recovered.checkpoint.phase,
        ArtifactPublicationPhaseV1::PayloadDurable
    );
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
}
