//! Real SQLite qualification with an explicitly test-only authority verifier.
//! The opaque payloads here establish byte custody, not a RecallPacket codec.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf_learning::EngramPopulationV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellManifestV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellRoleV1;
use codex_hepta_cognitive_types::hnmf::ModalityKindV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::ProductionDurableWriter;
use crate::CognitiveAccess;
use crate::CognitiveRecoveryRequirement;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::ForgetMemoryDraft;
use crate::MemoryCellCheckpointDraftV1;
use crate::MemoryCellCheckpointHeaderV1;
use crate::MemoryCellCheckpointReadPinsV1;
use crate::MemoryCellCheckpointReceiptV1;
use crate::MemoryCellStateErrorV1;
use crate::MemoryDraft;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityToken;
use crate::ProductionAuthorityVerifier;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;

const NOW: i64 = 300;
const SCOPE: CognitiveScope = CognitiveScope::AgentPrivate;

struct TestOwner {
    temp: TempDir,
    store: CognitiveStore,
    writer: Arc<ProductionDurableWriter>,
    access: CognitiveAccess,
    revoked: Arc<AtomicBool>,
}

async fn owner() -> TestOwner {
    let temp = TempDir::new().unwrap();
    let agent = agent_id(184);
    let store = CognitiveStore::open(&layout(&temp, &agent)).await.unwrap();
    let authority = ProductionAuthorityLease::from_verified_parts(
        agent.clone(),
        Sha256Digest::for_bytes(b"test-only-memory-cell-grant"),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        crate::production_writer::now_unix_seconds().unwrap() + 3600,
        ProductionAuthorityToken::from_verified_bytes(b"test-only-memory-cell-token".to_vec())
            .unwrap(),
    )
    .unwrap();
    let revoked = Arc::new(AtomicBool::new(false));
    let revocation = Arc::clone(&revoked);
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |grant: &ProductionAuthorityLease, expected: &AgentId| {
            if revocation.load(Ordering::SeqCst)
                || grant.agent_id != *expected
                || grant.grant_digest != Sha256Digest::for_bytes(b"test-only-memory-cell-grant")
            {
                Err("test-only grant is not current".into())
            } else {
                Ok(())
            }
        },
    );
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store.clone(),
            authority,
            verifier,
            "memory-cell-tests",
            /*generation*/ 1,
        )
        .await
        .unwrap(),
    );
    TestOwner {
        temp,
        store,
        writer,
        access: CognitiveAccess::agent_private(agent),
        revoked,
    }
}

fn digest(bytes: &[u8]) -> ContractDigestV1 {
    ContractDigestV1::from_digest(Digest32::of_bytes(bytes)).unwrap()
}

async fn draft(owner: &TestOwner) -> MemoryCellCheckpointDraftV1 {
    let state = b"opaque-test-state\0\x01\xff".to_vec();
    let recall = b"opaque-test-recall\0\x02\xfe".to_vec();
    let manifest = MemoryCellManifestV1 {
        schema_version: 1,
        cell_id: ContractIdV1::new("test-memory-cell").unwrap(),
        role: MemoryCellRoleV1::Semantic,
        parent_cell_id: None,
        shared_base_digest: digest(b"test-base"),
        encoder_digest: digest(b"test-encoder"),
        adapter_artifact_digest: digest(b"test-adapter"),
        head_artifact_digest: digest(b"test-head"),
        state_schema_digest: digest(b"opaque-test-state-schema"),
        source_frontier_digest: digest(b"test-source-frontier"),
        forget_frontier_digest: digest(b"test-forget-frontier"),
        lineage_digest: digest(b"test-lineage"),
        modalities: [ModalityKindV1::Text].into_iter().collect(),
        populations: [EngramPopulationV1::SemanticConcept].into_iter().collect(),
        graph_generation: ContractGenerationV1::new(1).unwrap(),
        model_generation: ContractGenerationV1::new(1).unwrap(),
        max_active_cells: 1,
        max_state_bytes: 1024,
    };
    let cut = owner
        .store
        .lane_c_snapshot(&owner.access, &SCOPE, NOW)
        .await
        .unwrap();
    MemoryCellCheckpointDraftV1 {
        header: MemoryCellCheckpointHeaderV1 {
            manifest,
            logical_sequence: 1,
            predecessor_digest: None,
            owner_cut_digest: ContractDigestV1::from_digest(cut.cut_digest()).unwrap(),
            recall_packet_digest: digest(b"test-logical-packet"),
            state_content_digest: digest(&state),
            recall_content_digest: digest(&recall),
        },
        state_bytes: state,
        recall_bytes: recall,
    }
}

fn pins(
    draft: &MemoryCellCheckpointDraftV1,
    receipt: &MemoryCellCheckpointReceiptV1,
) -> MemoryCellCheckpointReadPinsV1 {
    MemoryCellCheckpointReadPinsV1 {
        manifest: draft.header.manifest.clone(),
        checkpoint_digest: receipt.checkpoint_digest,
        owner_cut_digest: draft.header.owner_cut_digest,
    }
}

fn state(draft: &mut MemoryCellCheckpointDraftV1, bytes: Vec<u8>) {
    draft.header.state_content_digest = digest(&bytes);
    draft.state_bytes = bytes;
}

#[tokio::test]
async fn exact_recovery_preserves_real_blobs_and_all_version_pins() {
    let owner = owner().await;
    let cap = owner.writer.memory_cell_state_capability().unwrap();
    let before = owner.store.recovery_anchor().await.unwrap();
    let draft = draft(&owner).await;
    let receipt = cap
        .commit(&owner.access, &SCOPE, &draft, NOW)
        .await
        .unwrap();
    assert_eq!(
        receipt.authority(),
        codex_hepta_types::AuthorityPosture::DENY_ALL
    );
    let current = owner.store.recovery_anchor().await.unwrap();
    assert_ne!(before.state_digest, current.state_digest);
    let retained = pins(&draft, &receipt);
    let TestOwner {
        temp,
        store,
        writer,
        access,
        ..
    } = owner;
    let authority = writer.authority().clone();
    let verifier = Arc::clone(writer.live_verifier.as_ref().unwrap());
    drop(cap);
    drop(writer);
    store.pool.close().await;
    drop(store);
    let reopened = CognitiveStore::open_with_recovery(
        &layout(&temp, &authority.agent_id),
        CognitiveRecoveryRequirement::ExactCurrentCut(&current),
        &authority,
        verifier.as_ref(),
    )
    .await
    .unwrap();
    assert_eq!(reopened.recovery_anchor().await.unwrap(), current);
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            reopened,
            authority,
            verifier,
            "memory-cell-tests",
            /*generation*/ 1,
        )
        .await
        .unwrap(),
    );
    let loaded = writer
        .memory_cell_state_capability()
        .unwrap()
        .read_current(&access, &SCOPE, &retained, NOW)
        .await
        .unwrap();
    assert_eq!((loaded.draft, loaded.receipt), (draft, receipt));
}

#[tokio::test]
async fn retries_predecessors_and_competing_head_updates_are_exact() {
    let owner = owner().await;
    let cap = owner.writer.memory_cell_state_capability().unwrap();
    let mut first = draft(&owner).await;
    let receipt = cap
        .commit(&owner.access, &SCOPE, &first, NOW)
        .await
        .unwrap();
    let before_retry = owner.store.recovery_anchor().await.unwrap();
    let mut expected_retry = receipt.clone();
    expected_retry.replayed = true;
    assert_eq!(
        cap.commit(&owner.access, &SCOPE, &first, NOW)
            .await
            .unwrap(),
        expected_retry
    );
    assert_eq!(owner.store.recovery_anchor().await.unwrap(), before_retry);
    state(&mut first, b"different-but-correctly-hashed-bytes".to_vec());
    assert!(matches!(
        cap.commit(&owner.access, &SCOPE, &first, NOW).await,
        Err(MemoryCellStateErrorV1::Conflict(_))
    ));
    first.header.logical_sequence = 2;
    first.header.predecessor_digest = Some(digest(b"wrong-predecessor"));
    assert!(matches!(
        cap.commit(&owner.access, &SCOPE, &first, NOW).await,
        Err(MemoryCellStateErrorV1::Conflict(_))
    ));
    first.header.predecessor_digest = Some(receipt.checkpoint_digest);
    let mut competing = first.clone();
    state(&mut competing, b"competing-state".to_vec());
    let (left, right) = tokio::join!(
        cap.commit(&owner.access, &SCOPE, &first, NOW),
        cap.commit(&owner.access, &SCOPE, &competing, NOW)
    );
    assert_eq!(usize::from(left.is_ok()) + usize::from(right.is_ok()), 1);
    let loser = if left.is_ok() { right } else { left };
    assert!(matches!(loser, Err(MemoryCellStateErrorV1::Conflict(_))));
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM cognitive_memory_cell_checkpoints")
        .fetch_one(&owner.store.pool)
        .await
        .unwrap();
    assert_eq!(count, 2);
    assert!(
        cap.read_current(
            &owner.access,
            &SCOPE,
            &pins(&draft(&owner).await, &receipt),
            NOW
        )
        .await
        .is_err()
    );
}

#[tokio::test]
async fn source_and_forget_changes_reject_stale_reads_and_writes() {
    let owner = owner().await;
    let cap = owner.writer.memory_cell_state_capability().unwrap();
    let old = draft(&owner).await;
    let receipt = cap.commit(&owner.access, &SCOPE, &old, NOW).await.unwrap();
    let citation = owner
        .store
        .append_source(&owner.access, &source(SCOPE, "new-source", "evidence"))
        .await
        .unwrap();
    assert!(matches!(
        cap.read_current(&owner.access, &SCOPE, &pins(&old, &receipt), NOW)
            .await,
        Err(MemoryCellStateErrorV1::Conflict(_))
    ));
    assert!(matches!(
        cap.commit(&owner.access, &SCOPE, &old, NOW).await,
        Err(MemoryCellStateErrorV1::Conflict(_))
    ));
    let memory = owner
        .store
        .remember_memory(
            &owner.access,
            &MemoryDraft {
                stable_key: "forget-race".into(),
                revision: memory_revision(SCOPE, "remembered", citation.clone()),
            },
        )
        .await
        .unwrap();
    let mut before_forget = draft(&owner).await;
    before_forget.header.logical_sequence = 2;
    before_forget.header.predecessor_digest = Some(receipt.checkpoint_digest);
    let before_receipt = cap
        .commit(&owner.access, &SCOPE, &before_forget, NOW)
        .await
        .unwrap();
    owner
        .store
        .forget_memory(
            &owner.access,
            &memory.id.memory_id,
            memory.id.revision,
            &ForgetMemoryDraft {
                scope: SCOPE,
                reason: "test memory withdrawn".into(),
                valid_from_unix_seconds: 200,
                citations: vec![citation],
            },
        )
        .await
        .unwrap();
    assert!(matches!(
        cap.read_current(
            &owner.access,
            &SCOPE,
            &pins(&before_forget, &before_receipt),
            NOW
        )
        .await,
        Err(MemoryCellStateErrorV1::Conflict(_))
    ));
    assert!(matches!(
        cap.commit(&owner.access, &SCOPE, &before_forget, NOW).await,
        Err(MemoryCellStateErrorV1::Conflict(_))
    ));
    let fresh = owner
        .store
        .lane_c_snapshot(&owner.access, &SCOPE, NOW)
        .await
        .unwrap();
    assert_eq!(fresh.frontiers().tombstone, 1);
}

#[tokio::test]
async fn invalid_bytes_budgets_identity_and_revoked_authority_fail_closed() {
    let owner = owner().await;
    let cap = owner.writer.memory_cell_state_capability().unwrap();
    let valid = draft(&owner).await;
    let mut invalid = valid.clone();
    invalid.state_bytes[0] ^= 1;
    assert!(matches!(
        cap.commit(&owner.access, &SCOPE, &invalid, NOW).await,
        Err(MemoryCellStateErrorV1::Invalid(_))
    ));
    state(&mut invalid, vec![1; 1025]);
    assert!(matches!(
        cap.commit(&owner.access, &SCOPE, &invalid, NOW).await,
        Err(MemoryCellStateErrorV1::Invalid(_))
    ));
    invalid = valid.clone();
    invalid.recall_bytes = vec![2; crate::MAX_MEMORY_CELL_CHECKPOINT_RECALL_BYTES + 1];
    invalid.header.recall_content_digest = digest(&invalid.recall_bytes);
    assert!(matches!(
        cap.commit(&owner.access, &SCOPE, &invalid, NOW).await,
        Err(MemoryCellStateErrorV1::Invalid(_))
    ));
    let receipt = cap
        .commit(&owner.access, &SCOPE, &valid, NOW)
        .await
        .unwrap();
    let mut wrong_pins = pins(&valid, &receipt);
    wrong_pins.manifest.encoder_digest = digest(b"wrong-encoder");
    assert!(matches!(
        cap.read_current(&owner.access, &SCOPE, &wrong_pins, NOW)
            .await,
        Err(MemoryCellStateErrorV1::Conflict(_))
    ));
    assert!(
        cap.read_current(
            &CognitiveAccess::agent_private(agent_id(185)),
            &SCOPE,
            &pins(&valid, &receipt),
            NOW
        )
        .await
        .is_err()
    );
    owner.revoked.store(true, Ordering::SeqCst);
    assert!(matches!(
        cap.read_current(&owner.access, &SCOPE, &pins(&valid, &receipt), NOW)
            .await,
        Err(MemoryCellStateErrorV1::Writer(_))
    ));
    assert!(matches!(
        cap.commit(&owner.access, &SCOPE, &valid, NOW).await,
        Err(MemoryCellStateErrorV1::Writer(_))
    ));
    owner.revoked.store(false, Ordering::SeqCst);
    owner.writer.lease.release().await.unwrap();
    assert!(matches!(
        cap.read_current(&owner.access, &SCOPE, &pins(&valid, &receipt), NOW)
            .await,
        Err(MemoryCellStateErrorV1::Writer(_))
    ));
    assert!(matches!(
        cap.commit(&owner.access, &SCOPE, &valid, NOW).await,
        Err(MemoryCellStateErrorV1::Writer(_))
    ));
}

#[tokio::test]
async fn failed_head_write_rolls_back_body_and_read_detects_tampering() {
    let owner = owner().await;
    let cap = owner.writer.memory_cell_state_capability().unwrap();
    let valid = draft(&owner).await;
    sqlx::query("CREATE TRIGGER test_reject_memory_cell_head BEFORE INSERT ON cognitive_memory_cell_heads BEGIN SELECT RAISE(ABORT, 'injected head failure'); END").execute(&owner.store.pool).await.unwrap();
    assert!(
        cap.commit(&owner.access, &SCOPE, &valid, NOW)
            .await
            .is_err()
    );
    let count: i64 = sqlx::query_scalar("SELECT count(*) FROM cognitive_memory_cell_checkpoints")
        .fetch_one(&owner.store.pool)
        .await
        .unwrap();
    assert_eq!(count, 0);
    sqlx::query("DROP TRIGGER test_reject_memory_cell_head")
        .execute(&owner.store.pool)
        .await
        .unwrap();
    let receipt = cap
        .commit(&owner.access, &SCOPE, &valid, NOW)
        .await
        .unwrap();
    assert!(
        sqlx::query("UPDATE cognitive_memory_cell_checkpoints SET state_bytes = X'01'")
            .execute(&owner.store.pool)
            .await
            .is_err()
    );
    sqlx::query("DROP TRIGGER cognitive_memory_cell_checkpoints_no_update")
        .execute(&owner.store.pool)
        .await
        .unwrap();
    sqlx::query("UPDATE cognitive_memory_cell_checkpoints SET state_bytes = X'01'")
        .execute(&owner.store.pool)
        .await
        .unwrap();
    assert!(matches!(
        cap.read_current(&owner.access, &SCOPE, &pins(&valid, &receipt), NOW)
            .await,
        Err(MemoryCellStateErrorV1::Corrupt(_))
    ));
}
