//! These tests execute the real artifact owner and files. Keys and model
//! metadata are explicit fixtures, never a positive-learning/adoption claim.

use std::fs;

use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::tests::TestDir;
use super::tests::digest;
use super::tests::id;
use super::tests::key;
use super::tests::lease;
use super::tests::manifest;
use super::tests::scope;
use super::tests::trust;
use super::*;
use crate::OriginalArtifactPublicationReadbackErrorV1;
use crate::RegistryHeadWitnessV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;

#[path = "owner_service_readback_support_tests.rs"]
mod support;
use support::OriginalPublicationReadbackFixture;

#[test]
fn original_publication_readback_observes_lost_reply_without_republishing() {
    let fixture = OriginalPublicationReadbackFixture::fresh();
    let before = fixture.bytes();
    let original = fixture
        .service
        .host
        .recover_publication(&fixture.baseline.operation_id)
        .fixture("actual checkpoint")
        .fixture("started original operation")
        .checkpoint;
    let read = fixture
        .service
        .read_original_publication_current(&fixture.baseline.operation_id, fixture.baseline_intent)
        .fixture("actual original readback");
    assert_eq!(read.checkpoint(), &original);
    assert_eq!(
        read.checkpoint().phase,
        ArtifactPublicationPhaseV1::Acknowledged
    );
    assert_eq!(
        read.current().receipt(),
        original.registry_receipt.fixture("original registry")
    );
    assert!(!read.authority().grants_any());
    assert!(read.observed_unix_millis() >= fixture.baseline.now);
    assert_eq!(fixture.bytes(), before);
    assert!(fixture.service.recovery_required().is_none());
}

#[test]
fn original_publication_readback_leaves_pending_and_recovery_block_unchanged() {
    let mut fixture = OriginalPublicationReadbackFixture::fresh();
    let (request, intent) = fixture.begin_pending();
    let before = fixture.bytes();
    let original_registry = fixture.service.registry().clone();
    let read = fixture
        .service
        .read_original_publication_current(&request.operation_id, intent)
        .fixture("pending original readback");
    assert_eq!(
        read.checkpoint().phase,
        ArtifactPublicationPhaseV1::Prepared
    );
    assert_eq!(read.checkpoint().registry_receipt, None);
    assert_eq!(
        read.current().receipt().head_digest,
        original_registry.snapshot().head_digest
    );
    assert_eq!(
        fixture.service.recovery_required(),
        Some(&request.operation_id)
    );
    assert_eq!(
        fixture.service.registry().records(),
        original_registry.records()
    );
    assert_eq!(
        fixture.service.registry().snapshot().head_digest,
        original_registry.snapshot().head_digest
    );
    assert_eq!(fixture.bytes(), before);
}

#[test]
fn original_publication_readback_cold_reopens_exact_pending_without_completion() {
    let mut fixture = OriginalPublicationReadbackFixture::fresh();
    let (request, intent) = fixture.begin_pending();
    let before = fixture.bytes();
    let fixture = fixture.reopen();
    let read = fixture
        .service
        .read_original_publication_current(&request.operation_id, intent)
        .fixture("original pending after reopen");
    assert_eq!(
        read.checkpoint().phase,
        ArtifactPublicationPhaseV1::Prepared
    );
    assert_eq!(
        fixture.service.recovery_required(),
        Some(&request.operation_id)
    );
    assert_eq!(fixture.bytes(), before);
}

#[test]
fn original_publication_readback_refuses_missing_or_changed_expected_operation() {
    let fixture = OriginalPublicationReadbackFixture::fresh();
    let before = fixture.bytes();
    for (operation, intent) in [
        (fixture.baseline.operation_id.clone(), Digest32::ZERO),
        (
            fixture.baseline.operation_id.clone(),
            digest("another-original-intent"),
        ),
        (
            id("never-started-original-operation"),
            fixture.baseline_intent,
        ),
    ] {
        assert!(
            fixture
                .service
                .read_original_publication_current(&operation, intent)
                .is_err()
        );
        assert_eq!(fixture.bytes(), before);
        assert!(fixture.service.recovery_required().is_none());
    }
}

#[test]
fn original_publication_readback_refuses_actual_checkpoint_or_current_damage() {
    let fixture = OriginalPublicationReadbackFixture::fresh();
    let checkpoint = fixture.checkpoint_file(&fixture.baseline.operation_id, "0");
    let original = fs::read(&checkpoint).fixture("checkpoint before mutation");
    fs::write(&checkpoint, b"actual malformed original checkpoint").fixture("damage checkpoint");
    let damaged = fixture.bytes();
    assert!(
        fixture
            .service
            .read_original_publication_current(
                &fixture.baseline.operation_id,
                fixture.baseline_intent,
            )
            .is_err()
    );
    assert_eq!(fixture.bytes(), damaged);
    fs::write(&checkpoint, original).fixture("restore only the test's own checkpoint");
    let head = fs::read_dir(fixture.directory.0.join("heads"))
        .fixture("heads")
        .next()
        .fixture("head entry")
        .fixture("actual head")
        .path();
    let mut bytes = fs::read(&head).fixture("head bytes");
    let last = bytes.last_mut().fixture("nonempty original head");
    *last ^= 1;
    fs::write(&head, bytes).fixture("damage actual head");
    let damaged = fixture.bytes();
    assert!(
        fixture
            .service
            .read_original_publication_current(
                &fixture.baseline.operation_id,
                fixture.baseline_intent,
            )
            .is_err()
    );
    assert_eq!(fixture.bytes(), damaged);
}

#[test]
fn original_publication_readback_uses_live_clock_not_an_old_request_timestamp() {
    let fixture = OriginalPublicationReadbackFixture::expired_current();
    fixture
        .service
        .current_registry_view(fixture.baseline.now)
        .fixture("legacy explicit historical clock is not this new readback");
    let before = fixture.bytes();
    assert!(matches!(
        fixture.service.read_original_publication_current(
            &fixture.baseline.operation_id,
            fixture.baseline_intent,
        ),
        Err(OriginalArtifactPublicationReadbackErrorV1::Owner(
            ArtifactOwnerHostError::CurrentHeadExpired | ArtifactOwnerHostError::CurrentHeadContext
        ))
    ));
    assert_eq!(fixture.bytes(), before);
}

#[test]
fn original_publication_readback_bounds_the_actual_transaction_scan() {
    let fixture = OriginalPublicationReadbackFixture::fresh();
    let directory = fixture.directory.0.join("transactions");
    // These are real regular files ignored by the legacy receipt decoder. The
    // actual bounded scanner must count them, not only matching checkpoints.
    for index in 0..4_097 {
        fs::write(
            directory.join(format!("readback-bound-{index}.ignored")),
            b"",
        )
        .fixture("actual original transaction-directory entry");
    }
    let before = fixture.bytes();
    assert!(matches!(
        fixture.service.read_original_publication_current(
            &fixture.baseline.operation_id,
            fixture.baseline_intent,
        ),
        Err(OriginalArtifactPublicationReadbackErrorV1::Owner(
            ArtifactOwnerHostError::Capacity
        ))
    ));
    assert_eq!(fixture.bytes(), before);
    assert!(fixture.service.recovery_required().is_none());
}

#[test]
fn original_publication_readback_refuses_pending_physical_withdrawal() {
    let fixture = OriginalPublicationReadbackFixture::fresh();
    let pending = fixture.directory.0.join("withdrawal.pending");
    fs::write(&pending, b"unresolved original withdrawal").fixture("pending original frontier");
    let before = fixture.bytes();
    assert!(matches!(
        fixture.service.read_original_publication_current(
            &fixture.baseline.operation_id,
            fixture.baseline_intent,
        ),
        Err(OriginalArtifactPublicationReadbackErrorV1::Owner(
            ArtifactOwnerHostError::Indeterminate
        ))
    ));
    assert_eq!(fixture.bytes(), before);
    assert_eq!(
        fs::read(pending).fixture("pending marker is not repaired by readback"),
        b"unresolved original withdrawal"
    );
    assert!(fixture.service.recovery_required().is_none());
}

#[test]
fn original_publication_readback_bounds_all_head_directory_entries() {
    let fixture = OriginalPublicationReadbackFixture::fresh();
    let directory = fixture.directory.0.join("heads");
    for index in 0..4_097 {
        fs::write(
            directory.join(format!("readback-bound-{index}.ignored")),
            b"",
        )
        .fixture("actual original head-directory entry");
    }
    let before = fixture.bytes();
    assert!(matches!(
        fixture.service.read_original_publication_current(
            &fixture.baseline.operation_id,
            fixture.baseline_intent,
        ),
        Err(OriginalArtifactPublicationReadbackErrorV1::Owner(
            ArtifactOwnerHostError::Capacity
        ))
    ));
    assert_eq!(fixture.bytes(), before);
    assert!(fixture.service.recovery_required().is_none());
}

#[test]
fn owner_drain_closes_admission_but_preserves_original_readback_and_fence() {
    let mut fixture = OriginalPublicationReadbackFixture::fresh();
    let before = fixture.bytes();
    let lease = &fixture.config.writer_lease;
    let status = fixture.service.status(fixture.config.now);
    assert!(status.ready);
    assert_eq!(status.successful_requests, 1);
    assert!(!status.authority.grants_any());
    assert!(!fixture.service.status(lease.expires_at + 1).ready);

    assert!(!fixture.service.is_drained());
    fixture.service.begin_shutdown();
    fixture.service.begin_shutdown();
    assert!(fixture.service.is_drained());
    let status = fixture.service.status(fixture.config.now);
    assert!(status.draining);
    assert!(!status.ready);
    assert!(matches!(
        LearningArtifactOwnerService::open(fixture.config.clone()),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::WriterFenceBusy
        ))
    ));
    let (request, _) = fixture.pending_request();
    let context = OriginalArtifactPublicationContextV1 {
        operation_id: request.operation_id.clone(),
        admission: request.admission.clone(),
        expected_registry_predecessor_head: request.expected_registry_predecessor_head,
    };
    assert!(matches!(
        fixture
            .service
            .prepare_original_registry(context, &request.payload),
        Err(OriginalArtifactPreparationErrorV1::ShuttingDown)
    ));
    assert!(matches!(
        fixture.service.publish(request),
        Err(LearningArtifactOwnerServiceError::ShuttingDown)
    ));
    assert_eq!(
        fixture.service.status(fixture.config.now).rejected_requests,
        1
    );
    assert!(
        fixture
            .service
            .read_original_publication(&fixture.baseline.operation_id)
            .is_ok()
    );
    assert_eq!(fixture.bytes(), before);
    assert!(fixture.service.is_drained());
}

#[test]
fn original_terminal_retry_checks_signed_head_without_replaying_an_effect() {
    let mut fixture = OriginalPublicationReadbackFixture::fresh();
    let before = fixture.bytes();
    let mut altered = fixture.baseline.clone();
    altered.signed_current_head.signature[0] ^= 1;
    assert!(matches!(
        fixture.service.publish(altered),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::InvalidSignature
        ))
    ));
    assert!(fixture.service.recovery_required().is_none());
    let (mut new_request, _) = fixture.pending_request();
    new_request.now = fixture.config.now - 1;
    assert!(matches!(
        fixture.service.publish(new_request),
        Err(LearningArtifactOwnerServiceError::NonMonotonicTime)
    ));
    let receipt = fixture
        .service
        .publish(fixture.baseline.clone())
        .fixture("original exact receipt");
    assert_eq!(
        fixture
            .service
            .read_original_publication(&fixture.baseline.operation_id)
            .fixture("read original"),
        receipt
    );
    assert_eq!(
        fixture.service.status(fixture.config.now).terminal_replays,
        1
    );
    assert_eq!(fixture.bytes(), before);
}

#[test]
fn legacy_writer_fences_after_uncertain_checkpoint_read() {
    let mut fixture = OriginalPublicationReadbackFixture::fresh();
    let checkpoint = fixture.checkpoint_file(&fixture.baseline.operation_id, "0");
    let original = fs::read(&checkpoint).fixture("retained original checkpoint");
    fs::write(&checkpoint, b"malformed checkpoint fixture").fixture("damage owned fixture");
    assert!(fixture.service.publish(fixture.baseline.clone()).is_err());
    assert_eq!(
        fixture.service.recovery_required(),
        Some(&fixture.baseline.operation_id)
    );
    let (another, _) = fixture.pending_request();
    assert!(matches!(
        fixture.service.publish(another),
        Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
    ));
    fs::write(checkpoint, original).fixture("restore exact fixture");
    assert!(fixture.service.publish(fixture.baseline.clone()).is_ok());
    assert!(fixture.service.recovery_required().is_none());
}

#[cfg(unix)]
#[test]
fn durable_drain_keeps_the_same_record_and_terminal_receipt_on_reopen() {
    let mut fixture = OriginalPublicationReadbackFixture::fresh();
    let original = fixture
        .service
        .read_original_publication(&fixture.baseline.operation_id)
        .fixture("original acknowledged receipt");
    fixture
        .service
        .begin_drain_durable()
        .fixture("durable stop");
    let after_stop = fixture.bytes();
    assert_eq!(
        after_stop[std::path::Path::new("writer/DRAIN.v1")],
        format!(
            "HEPTA-ARTIFACT-DRAIN-V1\n{}\n{}\n{}\n",
            fixture.config.trust.registry_id,
            fixture.config.trust.withdrawal_scope_digest,
            fixture.config.storage_binding
        )
        .into_bytes()
    );
    fixture
        .service
        .begin_drain_durable()
        .fixture("retry exact stop");
    assert_eq!(fixture.bytes(), after_stop);
    let mut fixture = fixture.reopen();
    assert!(fixture.service.durable_drain_requested());
    assert!(fixture.service.is_drained());
    assert!(!fixture.service.status(fixture.config.now).ready);
    assert_eq!(
        fixture
            .service
            .publish(fixture.baseline.clone())
            .fixture("observe original terminal outcome"),
        original
    );
    let (new_request, _) = fixture.pending_request();
    assert!(matches!(
        fixture.service.publish(new_request),
        Err(LearningArtifactOwnerServiceError::ShuttingDown)
    ));
    assert_eq!(fixture.bytes(), after_stop);
}

#[cfg(unix)]
#[test]
fn durable_drain_reopens_only_the_original_pending_publication() {
    let mut fixture = OriginalPublicationReadbackFixture::fresh();
    let (mut pending, _) = fixture.begin_pending();
    fixture
        .service
        .begin_drain_durable()
        .fixture("durable stop");
    assert!(!fixture.service.is_drained());
    let mut fixture = fixture.reopen();
    assert!(fixture.service.durable_drain_requested());
    assert_eq!(
        fixture.service.recovery_required(),
        Some(&pending.operation_id)
    );
    let before = fixture.bytes();
    let mut changed = pending.clone();
    changed.payload.push(0);
    assert!(matches!(
        fixture.service.publish(changed),
        Err(LearningArtifactOwnerServiceError::RequestMismatch)
    ));
    assert_eq!(fixture.bytes(), before);

    pending.now = fixture.config.now;
    let mut wrong_head = pending.clone();
    wrong_head.signed_current_head.signature[0] ^= 1;
    assert!(matches!(
        fixture.service.publish(wrong_head),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::InvalidSignature
        ))
    ));
    assert_eq!(fixture.bytes(), before);
    fixture
        .service
        .publish(pending)
        .fixture("recover exact original publication");
    assert!(fixture.service.is_drained());
    assert!(!fixture.service.status(fixture.config.now).ready);
}

#[cfg(unix)]
#[test]
fn durable_drain_never_acknowledges_a_corrupt_or_foreign_record() {
    let mut fixture = OriginalPublicationReadbackFixture::fresh();
    let record = fixture.config.root.join("writer/DRAIN.v1");
    fixture
        .service
        .begin_drain_durable()
        .fixture("durable stop");
    let original = std::fs::read(&record).fixture("original stop record");
    let mut foreign = original.clone();
    foreign[0] ^= 1;
    std::fs::write(&record, &foreign).fixture("controlled corrupt stop record");
    assert!(fixture.service.begin_drain_durable().is_err());
    assert!(!fixture.service.durable_drain_requested());
    assert!(!fixture.service.is_drained());
    let (request, _) = fixture.pending_request();
    assert!(matches!(
        fixture.service.publish(request),
        Err(LearningArtifactOwnerServiceError::ShuttingDown)
    ));
    assert_eq!(
        std::fs::read(&record).fixture("corrupt record remains"),
        foreign
    );
    let config = fixture.config.clone();
    drop(fixture.service);
    for size in [0, original.len() / 2, original.len() - 1] {
        std::fs::write(&record, &original[..size]).fixture("truncated stop record");
        assert!(matches!(
            LearningArtifactOwnerService::open(config.clone()),
            Err(LearningArtifactOwnerServiceError::Host(
                ArtifactOwnerHostError::Io(std::io::ErrorKind::InvalidData)
            ))
        ));
    }
}

#[cfg(unix)]
#[test]
fn durable_drain_revalidates_a_recovered_payload_before_advancing() {
    let mut fixture = OriginalPublicationReadbackFixture::fresh();
    let (mut request, _) = fixture.pending_request();
    let store = &fixture.service.host;
    let mut snapshot = fixture.service.registry().clone();
    let mut transaction = store
        .begin_publication(
            request.operation_id.clone(),
            request.admission.clone(),
            fixture.service.withdrawal_registry(),
            &snapshot,
            request.expected_registry_predecessor_head,
            request.now,
        )
        .fixture("write original Prepared phase");
    store
        .stage_compatibility_registration(&transaction, &mut snapshot, request.now)
        .fixture("stage original registry");
    let raw = store
        .ensure_payload_durable(&mut transaction, &snapshot, &request.payload, request.now)
        .fixture("write original PayloadDurable phase");
    std::fs::write(fixture.config.root.join(raw), b"corrupt documented payload")
        .fixture("corrupt synthetic payload");
    fixture
        .service
        .begin_drain_durable()
        .fixture("durable stop");
    let mut fixture = fixture.reopen();
    request.now = fixture.config.now;
    let operation = request.operation_id.clone();
    let before = fixture.bytes();
    assert!(fixture.service.publish(request).is_err());
    assert_eq!(fixture.bytes(), before);
    assert!(!fixture.service.is_drained());
    assert_eq!(
        fixture
            .service
            .host
            .recover_publication(&operation)
            .fixture("read retained recovery")
            .fixture("retained checkpoint")
            .checkpoint
            .phase,
        ArtifactPublicationPhaseV1::PayloadDurable
    );
}
