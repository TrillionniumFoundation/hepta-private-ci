//! These tests execute the real artifact owner and files. Keys and model
//! metadata are explicit fixtures, never a positive-learning/adoption claim.

use std::fs;

use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use super::tests::TestDir;
use super::tests::digest;
use super::tests::id;
use super::tests::key;
use super::tests::lease;
use super::tests::manifest;
use super::tests::scope;
use super::tests::trust;
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
    let original = fixture.service.host.recover_publication(&fixture.baseline.operation_id)
        .fixture("actual checkpoint").fixture("started original operation").checkpoint;
    let read = fixture.service.read_original_publication_current(
        &fixture.baseline.operation_id, fixture.baseline_intent,
    ).fixture("actual original readback");
    assert_eq!(read.checkpoint(), &original);
    assert_eq!(read.checkpoint().phase, ArtifactPublicationPhaseV1::Acknowledged);
    assert_eq!(read.current().receipt(), original.registry_receipt.fixture("original registry"));
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
    let read = fixture.service.read_original_publication_current(&request.operation_id, intent)
        .fixture("pending original readback");
    assert_eq!(read.checkpoint().phase, ArtifactPublicationPhaseV1::Prepared);
    assert_eq!(read.checkpoint().registry_receipt, None);
    assert_eq!(read.current().receipt().head_digest, original_registry.snapshot().head_digest);
    assert_eq!(fixture.service.recovery_required(), Some(&request.operation_id));
    assert_eq!(fixture.service.registry().records(), original_registry.records());
    assert_eq!(fixture.service.registry().snapshot().head_digest,
        original_registry.snapshot().head_digest);
    assert_eq!(fixture.bytes(), before);
}

#[test]
fn original_publication_readback_cold_reopens_exact_pending_without_completion() {
    let mut fixture = OriginalPublicationReadbackFixture::fresh();
    let (request, intent) = fixture.begin_pending();
    let before = fixture.bytes();
    let fixture = fixture.reopen();
    let read = fixture.service.read_original_publication_current(&request.operation_id, intent)
        .fixture("original pending after reopen");
    assert_eq!(read.checkpoint().phase, ArtifactPublicationPhaseV1::Prepared);
    assert_eq!(fixture.service.recovery_required(), Some(&request.operation_id));
    assert_eq!(fixture.bytes(), before);
}

#[test]
fn original_publication_readback_refuses_missing_or_changed_expected_operation() {
    let fixture = OriginalPublicationReadbackFixture::fresh();
    let before = fixture.bytes();
    for (operation, intent) in [
        (fixture.baseline.operation_id.clone(), Digest32::ZERO),
        (fixture.baseline.operation_id.clone(), digest("another-original-intent")),
        (id("never-started-original-operation"), fixture.baseline_intent),
    ] {
        assert!(fixture.service.read_original_publication_current(&operation, intent).is_err());
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
    assert!(fixture.service.read_original_publication_current(
        &fixture.baseline.operation_id, fixture.baseline_intent,
    ).is_err());
    assert_eq!(fixture.bytes(), damaged);
    fs::write(&checkpoint, original).fixture("restore only the test's own checkpoint");
    let head = fs::read_dir(fixture.directory.0.join("heads")).fixture("heads")
        .next().fixture("head entry").fixture("actual head").path();
    let mut bytes = fs::read(&head).fixture("head bytes");
    let last = bytes.last_mut().fixture("nonempty original head");
    *last ^= 1;
    fs::write(&head, bytes).fixture("damage actual head");
    let damaged = fixture.bytes();
    assert!(fixture.service.read_original_publication_current(
        &fixture.baseline.operation_id, fixture.baseline_intent,
    ).is_err());
    assert_eq!(fixture.bytes(), damaged);
}

#[test]
fn original_publication_readback_uses_live_clock_not_an_old_request_timestamp() {
    let fixture = OriginalPublicationReadbackFixture::expired_current();
    fixture.service.current_registry_view(fixture.baseline.now)
        .fixture("legacy explicit historical clock is not this new readback");
    let before = fixture.bytes();
    assert!(matches!(
        fixture.service.read_original_publication_current(
            &fixture.baseline.operation_id, fixture.baseline_intent,
        ),
        Err(OriginalArtifactPublicationReadbackErrorV1::Owner(
            ArtifactOwnerHostError::CurrentHeadExpired | ArtifactOwnerHostError::CurrentHeadContext
        ))
    ));
    assert_eq!(fixture.bytes(), before);
}
