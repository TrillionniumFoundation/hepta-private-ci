use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::memory_cell_test_support::*;
use super::*;

#[tokio::test]
async fn memory_cell_real_owner_commit_and_persistent_replay() {
    let f = fixture().await;
    let a = f
        .writer
        .admit_memory_cell(&f.access, &f.query, &f.claim)
        .await
        .unwrap();
    f.writer.revalidate_memory_cell(&a).await.unwrap();
    let digest = Digest32::of_bytes(b"execution-receipt");
    let finished = f.writer.finish_memory_cell(&a, digest).await.unwrap();
    assert_eq!(
        (&finished.binding, finished.execution_digest),
        (a.binding(), digest)
    );
    assert!(matches!(
        f.writer.finish_memory_cell(&a, digest).await,
        Err(MemoryCellSourceError::Replay)
    ));
    let store = f.writer.store.clone();
    let authority = f.writer.authority.clone();
    drop(f.writer);
    let reopened = ProductionDurableWriter::open_with_live_verifier(
        store,
        authority,
        f.verifier,
        "memory-cell-test",
        1,
    )
    .await
    .unwrap();
    assert!(matches!(
        reopened
            .admit_memory_cell(&f.access, &f.query, &f.claim)
            .await,
        Err(MemoryCellSourceError::Replay)
    ));
    drop(f.temp);
}

#[tokio::test]
async fn memory_cell_forged_self_consistent_receipt_does_not_authorize() {
    let f = fixture().await;
    let mut forged = f.claim.clone();
    forged.production.authority_grant_digest = Sha256Digest::for_bytes(b"forged");
    forged.production.receipt_sha256 = forged.production.compute_receipt_sha256();
    forged.production.validate().unwrap();
    assert!(
        f.writer
            .admit_memory_cell(&f.access, &f.query, &forged)
            .await
            .is_err()
    );
    let mut forged = f.claim.clone();
    forged.production.provenance_commit_event_id = "invented-commit".to_string();
    forged.production.receipt_sha256 = forged.production.compute_receipt_sha256();
    assert!(
        f.writer
            .admit_memory_cell(&f.access, &f.query, &forged)
            .await
            .is_err()
    );
    // Failed preflight does not consume the valid nonce or call a backend.
    assert!(
        f.writer
            .admit_memory_cell(&f.access, &f.query, &f.claim)
            .await
            .is_ok()
    );
}

#[tokio::test]
async fn memory_cell_wrong_key_role_and_provenance_fail_closed() {
    let f = fixture().await;
    let mut wrong = f.query.clone();
    wrong.key.entity = "pipeline-99".to_string();
    assert!(
        f.writer
            .admit_memory_cell(&f.access, &wrong, &f.claim)
            .await
            .is_err()
    );
    wrong.key = f.query.key.clone();
    wrong.key.role = MemoryCellRoleV1::Procedural;
    assert!(
        f.writer
            .admit_memory_cell(&f.access, &wrong, &f.claim)
            .await
            .is_err()
    );
    let mut forged = f.claim.clone();
    forged.event.provenance[0].source_revision += 1;
    assert!(
        f.writer
            .admit_memory_cell(&f.access, &f.query, &forged)
            .await
            .is_err()
    );
    let foreign = CognitiveAccess::agent_private(
        codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2caa").unwrap(),
    );
    assert!(
        f.writer
            .admit_memory_cell(&foreign, &f.query, &f.claim)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn memory_cell_correction_fences_pending_read_and_old_training_root() {
    let f = fixture().await;
    let a = f
        .writer
        .admit_memory_cell(&f.access, &f.query, &f.claim)
        .await
        .unwrap();
    let source = source(&f.query, "build-43", "invalidate-cache");
    let changed = f
        .writer
        .cognitive_mutation_capability()
        .unwrap()
        .correct_with_kg(
            &f.access,
            &f.claim.production.write.memory.id.memory_id,
            1,
            &source,
            &revision(&source),
            &KgFactSetDraft::default(),
        )
        .await
        .unwrap();
    assert!(f.writer.revalidate_memory_cell(&a).await.is_err());
    assert!(
        f.writer
            .finish_memory_cell(&a, Digest32::of_bytes(b"late-output"))
            .await
            .is_err()
    );
    let mut query = f.query.clone();
    query.request_id = StableId::new("read:2").unwrap();
    assert!(
        f.writer
            .admit_memory_cell(&f.access, &query, &f.claim)
            .await
            .is_err()
    );
    let current = claim(&query, changed);
    let new = f
        .writer
        .admit_memory_cell(&f.access, &query, &current)
        .await
        .unwrap();
    assert_ne!(
        a.binding().source_content_sha256,
        new.binding().source_content_sha256
    );
}

#[tokio::test]
async fn memory_cell_withdrawal_and_authority_revocation_fence_pending_use() {
    let f = fixture().await;
    let a = f
        .writer
        .admit_memory_cell(&f.access, &f.query, &f.claim)
        .await
        .unwrap();
    f.verifier.0.store(true, Ordering::SeqCst);
    assert!(f.writer.revalidate_memory_cell(&a).await.is_err());
    f.verifier.0.store(false, Ordering::SeqCst);
    let source = SourceDraft {
        content: b"withdrawn".to_vec(),
        event_key: "withdraw:42".to_string(),
        ..source(&f.query, "unused", "unused")
    };
    let draft = ForgetMemoryDraft {
        scope: source.scope.clone(),
        reason: "withdrawn".to_string(),
        valid_from_unix_seconds: source.observed_at_unix_seconds,
        citations: vec![],
    };
    f.writer
        .cognitive_mutation_capability()
        .unwrap()
        .forget_with_kg(
            &f.access,
            &f.claim.production.write.memory.id.memory_id,
            1,
            &source,
            &draft,
        )
        .await
        .unwrap();
    assert!(f.writer.revalidate_memory_cell(&a).await.is_err());
    assert!(
        f.writer
            .finish_memory_cell(&a, Digest32::of_bytes(b"late-output"))
            .await
            .is_err()
    );
}

#[tokio::test]
async fn memory_cell_concurrent_duplicate_admission_has_one_winner() {
    let f = fixture().await;
    let writer = Arc::clone(&f.writer);
    let (left, right) = tokio::join!(
        f.writer.admit_memory_cell(&f.access, &f.query, &f.claim),
        writer.admit_memory_cell(&f.access, &f.query, &f.claim)
    );
    assert_eq!((left.is_ok() as u8) + (right.is_ok() as u8), 1);
    assert!(matches!(
        left.err().or_else(|| right.err()),
        Some(MemoryCellSourceError::Replay)
    ));
}
