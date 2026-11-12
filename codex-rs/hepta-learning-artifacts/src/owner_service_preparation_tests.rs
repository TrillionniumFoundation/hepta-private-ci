use super::*;
use super::super::tests as fixture;
use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::RegistryHeadWitnessV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
use std::cell::Cell;
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::path::PathBuf;

fn configuration(directory: &fixture::TestDir) -> LearningArtifactOwnerServiceConfigV1 {
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(fixture::scope());
    let scope = withdrawals.scope_digest().fixture("scope");
    LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(), trust: fixture::trust(&fixture::key(), scope),
        writer_lease: fixture::lease(&fixture::key(), scope), required_current_head: None,
        withdrawal_registry: withdrawals, storage_binding: fixture::digest("binding"), now: 20,
    }
}

fn context(service: &LearningArtifactOwnerService) -> OriginalArtifactPublicationContextV1 {
    OriginalArtifactPublicationContextV1 {
        operation_id: fixture::id("original-prepare"),
        admission: admit_manifest_at_withdrawal_head_v3(service.withdrawal_registry(),
            service.withdrawal_registry().head_digest(), fixture::manifest(), 20).fixture("admission"),
        expected_registry_predecessor_head: Digest32::ZERO,
    }
}

fn signed(proof: &OriginalArtifactRegistryDurableV1) -> SignedCurrentArtifactHeadV1 {
    let key = fixture::key();
    let mut value = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: proof.checkpoint().withdrawal_scope_digest,
        binding: proof.registry_receipt().binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: fixture::id("learning-artifacts"), generation: Generation::new(1).fixture("generation"),
            head_digest: proof.registry_receipt().head_digest,
            predecessor_head_digest: proof.checkpoint().expected_registry_predecessor_head,
            authority_epoch: 1, signer_id: fixture::id("owner-authority"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: 20, expires_at: 1_000,
        }, signature: [0; 64],
    };
    value.signature = key.sign(&value.signing_bytes()).to_bytes();
    value
}

// All immutable publication bytes; the separately held writer/owner.lock is
// intentionally never reopened while its original OS exclusive lock is held.
fn files(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    ["transactions", "payloads", "registries", "witnesses", "heads"].into_iter()
        .flat_map(|name| fs::read_dir(root.join(name)).fixture("read directory"))
        .map(|entry| { let path = entry.fixture("entry").path();
            (path.strip_prefix(root).fixture("relative path").to_path_buf(), fs::read(path).fixture("read bytes")) })
        .collect()
}

#[test]
fn original_registry_preparation_stops_before_head_and_finishes_same_writer_once() {
    let directory = fixture::TestDir::new();
    let mut service = LearningArtifactOwnerService::open(configuration(&directory)).fixture("open");
    let context = context(&service);
    let prepared = service.prepare_original_registry_with_clock(context.clone(), b"payload", &|| Ok(20)).fixture("prepare");
    assert_eq!(prepared.registry_durable().checkpoint().phase, ArtifactPublicationPhaseV1::RegistryDurable);
    assert!(prepared.registry_durable().current_head().is_none());
    assert_eq!(service.registry().snapshot().head_digest, Digest32::ZERO);
    let before = files(&directory.0);
    assert!(!before.keys().any(|path| path.starts_with("heads") || path.starts_with("witnesses")));
    let observed = service.read_original_registry_durable_with_clock(&context, &|| Ok(21)).fixture("physical read");
    assert!(observed.same_original_read(prepared.registry_durable()));
    assert_eq!(files(&directory.0), before);
    let head = signed(&observed);
    let receipt = service.finish_original_registry_with_clock(prepared, head.clone(), &|| Ok(30)).fixture("finish");
    let after = files(&directory.0);
    let completed = service.read_original_registry_durable_with_clock(&context, &|| Ok(31)).fixture("completed read");
    assert_eq!(completed.checkpoint().phase, ArtifactPublicationPhaseV1::Acknowledged);
    assert_eq!(completed.checkpoint().state_digest, receipt.state_digest);
    assert_eq!(completed.current_head(), Some(&head));
    assert_eq!(completed.registry_snapshot(), &service.registry().snapshot());
    assert!(matches!(service.prepare_original_registry_with_clock(context, b"payload", &|| Ok(31)),
        Err(OriginalArtifactPreparationErrorV1::ReadbackRequired)));
    assert_eq!(files(&directory.0), after);
}

#[test]
fn original_registry_lost_return_and_cold_readback_cannot_recreate_continuation() {
    let directory = fixture::TestDir::new();
    let config = configuration(&directory);
    let mut service = LearningArtifactOwnerService::open(config.clone()).fixture("open");
    let context = context(&service);
    let prepared = service.prepare_original_registry_with_clock(context.clone(), b"payload", &|| Ok(20)).fixture("prepare");
    let head = signed(prepared.registry_durable());
    let before = files(&directory.0);
    assert!(matches!(service.prepare_original_registry_with_clock(context.clone(), b"payload", &|| Ok(21)),
        Err(OriginalArtifactPreparationErrorV1::ReadbackRequired)));
    assert!(matches!(service.publish(crate::LearningArtifactPublishRequestV1 {
        operation_id: context.operation_id.clone(), admission: context.admission.clone(),
        payload: b"payload".to_vec(), signed_current_head: head.clone(),
        expected_registry_predecessor_head: context.expected_registry_predecessor_head, now: 21,
    }), Err(crate::LearningArtifactOwnerServiceError::RecoveryRequired(_))));
    assert_eq!(files(&directory.0), before);
    drop(service);
    // Explicit original deployment open, followed only by the pure read path.
    let mut recovered = LearningArtifactOwnerService::open(config).fixture("cold open");
    assert!(recovered.read_original_registry_durable_with_clock(&context, &|| Ok(21)).is_ok());
    assert!(matches!(recovered.finish_original_registry_with_clock(prepared, head, &|| Ok(21)),
        Err(OriginalArtifactPreparationErrorV1::ReadbackRequired)));
    assert!(matches!(recovered.prepare_original_registry_with_clock(context, b"payload", &|| Ok(21)),
        Err(OriginalArtifactPreparationErrorV1::ReadbackRequired)));
    assert_eq!(files(&directory.0), before);
}

#[test]
fn original_registry_partial_prepare_is_pending_and_readback_never_completes_it() {
    let directory = fixture::TestDir::new();
    let mut service = LearningArtifactOwnerService::open(configuration(&directory)).fixture("open");
    let context = context(&service);
    let manifest = &context.admission.validated_manifest.manifest;
    let path = directory.0.join("payloads").join(format!("{}-{}.bin", manifest.artifact_id, manifest.bytes_digest));
    fs::write(&path, b"invalid").fixture("test corruption");
    assert!(service.prepare_original_registry_with_clock(context.clone(), b"payload", &|| Ok(20)).is_err());
    let before = files(&directory.0);
    assert!(matches!(service.read_original_registry_durable_with_clock(&context, &|| Ok(20)),
        Err(OriginalArtifactPreparationErrorV1::Pending(ArtifactPublicationPhaseV1::Prepared))));
    assert_eq!(files(&directory.0), before);
    fs::write(path, b"payload").fixture("restore original test bytes");
    let restored = files(&directory.0);
    assert!(matches!(service.read_original_registry_durable_with_clock(&context, &|| Ok(20)),
        Err(OriginalArtifactPreparationErrorV1::Pending(ArtifactPublicationPhaseV1::Prepared))));
    assert!(matches!(service.prepare_original_registry_with_clock(context, b"payload", &|| Ok(20)),
        Err(OriginalArtifactPreparationErrorV1::ReadbackRequired)));
    assert_eq!(files(&directory.0), restored);
}

#[test]
fn original_registry_physical_corruption_fences_even_after_original_bytes_return() {
    for changed in ["registries", "payloads", "transactions"] {
        let directory = fixture::TestDir::new();
        let mut service = LearningArtifactOwnerService::open(configuration(&directory)).fixture("open");
        let context = context(&service);
        let prepared = service.prepare_original_registry_with_clock(context.clone(), b"payload", &|| Ok(20)).fixture("prepare");
        let head = signed(prepared.registry_durable());
        let original = files(&directory.0);
        let (path, bytes) = original.iter().find(|(path, _)| path.starts_with(changed)).fixture("file");
        let mut corrupt = bytes.clone();
        corrupt[0] ^= 1;
        fs::write(directory.0.join(path), corrupt).fixture("test corruption");
        assert!(service.read_original_registry_durable_with_clock(&context, &|| Ok(20)).is_err());
        fs::write(directory.0.join(path), bytes).fixture("restore test bytes");
        assert!(matches!(service.read_original_registry_durable_with_clock(&context, &|| Ok(20)),
            Err(OriginalArtifactPreparationErrorV1::Fenced)));
        assert!(service.finish_original_registry_with_clock(prepared, head, &|| Ok(20)).is_err());
        assert_eq!(files(&directory.0), original);
    }
}

#[test]
fn original_registry_wrong_context_is_refused_before_consuming_the_writer() {
    let directory = fixture::TestDir::new();
    let mut service = LearningArtifactOwnerService::open(configuration(&directory)).fixture("open");
    let valid = context(&service);
    let before = files(&directory.0);
    let mut wrong = valid.clone();
    wrong.expected_registry_predecessor_head = fixture::digest("other-head");
    assert!(service.prepare_original_registry_with_clock(wrong, b"payload", &|| Ok(20)).is_err());
    assert!(service.prepare_original_registry_with_clock(valid.clone(), b"different", &|| Ok(20)).is_err());
    assert_eq!(files(&directory.0), before);
    assert!(service.recovery_required().is_none());
    assert!(service.prepare_original_registry_with_clock(valid, b"payload", &|| Ok(20)).is_ok());
}

#[test]
fn original_registry_finish_requires_original_signature_withdrawal_and_fresh_time() {
    for failure in ["signature", "withdrawal", "clock"] {
        let directory = fixture::TestDir::new();
        let mut service = LearningArtifactOwnerService::open(configuration(&directory)).fixture("open");
        let context = context(&service);
        let prepared = service.prepare_original_registry_with_clock(context.clone(), b"payload", &|| Ok(20)).fixture("prepare");
        let mut head = signed(prepared.registry_durable());
        let before = files(&directory.0);
        if failure == "signature" { head.signature[0] ^= 1; }
        if failure == "withdrawal" {
            let mut next = service.withdrawal_registry().clone();
            next.append(DatasetWithdrawalNoticeV1 { notice_id: fixture::id("withdraw"), dataset_digest: fixture::digest("dataset"),
                source_tombstone_digest: fixture::digest("tombstone"), authority_id: fixture::id("withdrawal-owner"),
                credential_chain_digest: fixture::digest("credential"), signing_key_digest: fixture::digest("withdrawal-key"),
                authority_epoch: 1, issued_at: 21 }).fixture("withdraw");
            service.install_withdrawal_frontier(next).fixture("install original frontier");
        }
        let calls = Cell::new(0);
        let clock = || { let count = calls.get(); calls.set(count + 1); Ok(if failure == "clock" && count > 0 { 19 } else { 21 }) };
        assert!(service.finish_original_registry_with_clock(prepared, head, &clock).is_err());
        assert_eq!(files(&directory.0), before);
        assert!(service.recovery_required().is_some());
    }
}
