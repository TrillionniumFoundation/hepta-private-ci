//! Request identity, interrupted binding and strict historical replay regressions.

use super::*;
use pretty_assertions::assert_eq;
use crate::owner_service::request_record::RequestRecord;

fn fixture() -> (TestDir, LearningArtifactOwnerService, LearningArtifactPublishRequestV1,
    LearningArtifactOwnerServiceConfigV1)
{
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let config = LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(), trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest), required_current_head: None,
        withdrawal_registry: withdrawals.clone(), storage_binding: digest("binding"), now: 20,
    };
    let service = LearningArtifactOwnerService::open(config.clone()).fixture("open");
    let mut staged = service.registry().clone();
    let predecessor = staged.snapshot().head_digest;
    let admission = admit_manifest_at_withdrawal_head_v3(&withdrawals,
        withdrawals.head_digest(), manifest(), 20).fixture("admit");
    let preview = ArtifactPublicationTransactionV1::begin(id("operation"), admission,
        &withdrawals, &staged, predecessor, 20).fixture("preview");
    service.host.stage_compatibility_registration(&preview, &mut staged, 20).fixture("project");
    let request = publish_request(&key, &withdrawals, predecessor, staged.snapshot().head_digest);
    (directory, service, request, config)
}

fn record_path(directory: &TestDir, operation: &StableId) -> PathBuf {
    directory.0.join("writer/request-identities-v1").join(format!(
        "{}.request", Digest32::of_bytes(operation.as_str().as_bytes())))
}

#[test]
fn binding_without_prepared_survives_reopen_and_drain() {
    let (directory, mut service, mut request, config) = fixture();
    let identity = service.request_identity.verify(&request).fixture("verify");
    let record = RequestRecord::from_request(&request, identity).fixture("record");
    service.request_journal.bind(record, &service.request_identity).fixture("bind before Prepared");
    let original = fs::read(record_path(&directory, &request.operation_id)).fixture("saved identity");
    assert!(service.host.recover_publication(&request.operation_id).fixture("inspect").is_none());
    drop(service);
    let mut service = LearningArtifactOwnerService::open(config).fixture("reopen identity-only operation");
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
    service.begin_drain_durable().fixture("durable drain");
    assert!(!service.is_drained());
    let mut changed = request.clone();
    changed.signed_current_head.witness.expires_at -= 1;
    changed.signed_current_head.signature = key().sign(&changed.signed_current_head.signing_bytes()).to_bytes();
    assert!(matches!(service.publish(changed), Err(LearningArtifactOwnerServiceError::RequestMismatch)));
    request.now += 1;
    let receipt = service.publish(request.clone()).fixture("exact retry with new observation time");
    assert_eq!(service.publish(request).fixture("terminal replay"), receipt);
    assert!(service.is_drained());
    assert_eq!(fs::read(record_path(&directory, &id("operation"))).fixture("same bytes"), original);
}

#[test]
fn canonical_record_rejects_every_truncation_and_byte_corruption() {
    let (_directory, service, request, _config) = fixture();
    let identity = service.request_identity.verify(&request).fixture("verify");
    let record = RequestRecord::from_request(&request, identity).fixture("record");
    let bytes = record.encode().fixture("encode");
    let decoded = RequestRecord::decode(&bytes, &service.request_identity).fixture("canonical decode");
    assert_eq!(decoded.encode().fixture("roundtrip"), bytes);
    for length in 0..bytes.len() {
        assert!(RequestRecord::decode(&bytes[..length], &service.request_identity).is_err());
    }
    for index in 0..bytes.len() {
        let mut changed = bytes.clone(); changed[index] ^= 1;
        assert!(RequestRecord::decode(&changed, &service.request_identity).is_err());
    }
    let mut extended = bytes;
    extended.push(0);
    assert!(RequestRecord::decode(&extended, &service.request_identity).is_err());
}

#[test]
fn rehashed_metadata_substitution_still_checks_signature_and_manifest_digest() {
    let (_directory, service, request, _config) = fixture();
    let identity = service.request_identity.verify(&request).fixture("verify");
    let mut record = RequestRecord::from_request(&request, identity).fixture("record");
    record.admission.validated_manifest.manifest.runtime_tuple_digest = digest("substitution");
    assert!(RequestRecord::decode(&record.encode().fixture("reseal"), &service.request_identity).is_err());
    let mut record = RequestRecord::from_request(&request, identity).fixture("record");
    record.signed_head.witness.expires_at += 1;
    assert!(RequestRecord::decode(&record.encode().fixture("reseal"), &service.request_identity).is_err());
}

#[test]
fn partial_request_record_fences_publication_and_never_becomes_drained() {
    let (directory, mut service, request, config) = fixture();
    let path = record_path(&directory, &request.operation_id);
    fs::write(&path, b"").fixture("interrupted creation fixture");
    assert!(service.publish(request.clone()).is_err());
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
    service.begin_drain();
    assert!(!service.is_drained());
    assert!(service.publish(request).is_err());
    assert_eq!(fs::read(path).fixture("not overwritten"), Vec::<u8>::new());
    drop(service);
    assert!(LearningArtifactOwnerService::open(config).is_err());
}

#[test]
fn complete_uncertain_record_reuses_its_original_binding_time() {
    let (directory, mut service, mut request, _config) = fixture();
    let identity = service.request_identity.verify(&request).fixture("verify");
    let record = RequestRecord::from_request(&request, identity).fixture("record");
    let bytes = record.encode().fixture("encode");
    let path = record_path(&directory, &request.operation_id);
    fs::write(&path, &bytes).fixture("complete but unacknowledged write fixture");
    request.now += 1;
    service.publish(request).fixture("reconcile same metadata and original time");
    assert_eq!(fs::read(path).fixture("retained bytes"), bytes);
}

#[test]
fn legacy_prepared_without_request_binding_requires_explicit_migration() {
    let (_directory, mut service, request, _config) = fixture();
    service.host.begin_publication(request.operation_id.clone(), request.admission.clone(),
        service.withdrawal_registry(), service.registry(), request.expected_registry_predecessor_head,
        request.now).fixture("legacy Prepared fixture");
    assert!(matches!(service.publish(request), Err(LearningArtifactOwnerServiceError::LegacyRequestUnbound)));
    assert_eq!(service.host.recover_publication(&id("operation")).fixture("inspect")
        .fixture("pending").checkpoint.phase, ArtifactPublicationPhaseV1::Prepared);
}

#[test]
fn journal_rejects_symlinks_hardlinks_foreign_names_and_oversized_records() {
    use std::os::unix::fs::symlink;
    for kind in ["symlink", "hardlink", "name", "oversize"] {
        let (directory, service, request, config) = fixture();
        let identity = service.request_identity.verify(&request).fixture("verify");
        let record = RequestRecord::from_request(&request, identity).fixture("record");
        let bytes = record.encode().fixture("encode");
        let path = record_path(&directory, &request.operation_id);
        let outside = directory.0.join("retained-record");
        fs::write(&outside, bytes).fixture("outside record");
        match kind {
            "symlink" => symlink(&outside, &path).fixture("symlink fixture"),
            "hardlink" => fs::hard_link(&outside, &path).fixture("hardlink fixture"),
            "name" => fs::write(path.with_file_name("unexpected"), b"record").fixture("name fixture"),
            "oversize" => fs::write(&path, vec![0u8; 128 * 1024 + 1]).fixture("oversize fixture"),
            _ => unreachable!(),
        }
        drop(service);
        assert!(LearningArtifactOwnerService::open(config).is_err(), "accepted {kind}");
    }
}
