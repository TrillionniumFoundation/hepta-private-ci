use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tempfile::TempDir;

use super::MAX_JOURNAL_EVENTS;
use crate::CognitiveStore;
use crate::CompactCheckpoint;
use crate::CompactFence;
use crate::CompactLease;
use crate::CompactLossReport;
use crate::CompactParentSnapshot;
use crate::CompactPersistenceAppend;
use crate::CompactPersistenceJournal;
use crate::CompactPersistenceState;
use crate::CompactProtectedRef;
use crate::CompactSummaryReceipt;
use crate::LocalAtomicWitnessError;
use crate::LocalCompactExecutorError;
use crate::checkpoint_digest;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::write_local_rehydration_witness;

async fn assert_sqlite_integrity(store: &CognitiveStore) {
    assert!(
        sqlx::query("PRAGMA foreign_key_check")
            .fetch_all(&store.pool)
            .await
            .expect("foreign key check")
            .is_empty()
    );
    let integrity: String = sqlx::query_scalar("PRAGMA integrity_check")
        .fetch_one(&store.pool)
        .await
        .expect("integrity check");
    assert_eq!(integrity, "ok");
}

#[tokio::test]
async fn journal_capacity_rejects_growth_preserves_exact_replay_and_reopens() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(232);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let fence = CompactFence::new(3, 8, 1, "compact-capacity-fence").expect("fence");
    let parent = CompactParentSnapshot::new(
        "ctx:compact-capacity",
        20,
        30,
        7,
        Sha256Digest::for_bytes(b"compact-capacity-parent"),
        fence.clone(),
    )
    .expect("parent snapshot");
    let checkpoint = CompactCheckpoint::new(
        "checkpoint:compact-capacity",
        CompactLease::from_snapshot(parent.clone()),
        vec![
            CompactProtectedRef::new("approval:capacity", "approval", true).expect("protected ref"),
        ],
        CompactSummaryReceipt::new(
            Sha256Digest::for_bytes(b"compact-capacity-summary"),
            Sha256Digest::for_bytes(b"compact-capacity-model"),
            Sha256Digest::for_bytes(b"compact-capacity-policy"),
        ),
        CompactLossReport::new(Vec::new(), 0, Vec::new(), 0).expect("loss report"),
        0,
    )
    .expect("checkpoint");
    let journal_id = "journal:compact-capacity";
    let lease_id = "lease:compact-capacity";
    let expires_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs()
        + 3_600;
    let lease = store
        .acquire_host_bound_lease(
            lease_id,
            fence.authority_epoch,
            fence.owner_epoch,
            fence.generation,
            fence.fencing_token.clone(),
            expires_at,
        )
        .await
        .expect("bound lease")
        .into_handle();
    let executor = store
        .open_local_compact_executor_bound(journal_id, fence.clone(), &lease)
        .await
        .expect("executor");

    // Build a valid contract chain once and persist it through the real
    // private insert helper in one transaction. Public mutations reload the
    // complete chain, so using them for fixture setup would cost O(N^2).
    let mut journal = CompactPersistenceJournal::new(fence.clone()).expect("journal");
    for index in 0..MAX_JOURNAL_EVENTS - 1 {
        journal
            .append_intent(format!("op:compact-capacity:{index}"), &checkpoint, &parent)
            .expect("seed intent");
    }
    let mut transaction = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("seed transaction");
    for entry in journal.entries() {
        executor
            .insert_event(&mut transaction, entry)
            .await
            .expect("seed event");
    }
    transaction.commit().await.expect("commit seed chain");
    let seeded = executor
        .snapshot()
        .await
        .expect("verify complete seed chain");
    assert_eq!(seeded.entries.len(), MAX_JOURNAL_EVENTS - 1);
    assert_eq!(seeded, journal.snapshot());
    assert_sqlite_integrity(&store).await;

    let final_operation = format!("op:compact-capacity:{}", MAX_JOURNAL_EVENTS - 2);
    let checkpoint_sha256 = checkpoint_digest(&checkpoint).expect("checkpoint digest");
    let final_sequence = u64::try_from(MAX_JOURNAL_EVENTS).expect("event limit fits u64");
    assert_eq!(
        executor
            .commit_checkpoint(&final_operation, &checkpoint_sha256)
            .await
            .expect("fill final event slot"),
        CompactPersistenceAppend::Appended {
            sequence: final_sequence,
        }
    );
    let full = executor.snapshot().await.expect("verify full chain");
    assert_eq!(full.entries.len(), MAX_JOURNAL_EVENTS);
    assert!(matches!(
        executor
            .append_intent("op:compact-capacity:overflow", &checkpoint, &parent)
            .await,
        Err(LocalCompactExecutorError::Invalid(message))
            if message.contains("event reopen limit")
    ));
    assert!(matches!(
        executor
            .commit_checkpoint("op:compact-capacity:0", &checkpoint_sha256)
            .await,
        Err(LocalCompactExecutorError::Invalid(message))
            if message.contains("event reopen limit")
    ));
    // This public writer uses insert_event directly rather than mutate.
    assert!(matches!(
        write_local_rehydration_witness(&lease, &executor, &final_operation, &checkpoint, 0)
            .await,
        Err(LocalAtomicWitnessError::Compact(LocalCompactExecutorError::Invalid(message)))
            if message.contains("event reopen limit")
    ));
    assert_eq!(
        executor
            .append_intent(&final_operation, &checkpoint, &parent)
            .await
            .expect("intent replay at capacity"),
        CompactPersistenceAppend::Replay {
            sequence: final_sequence - 1,
        }
    );
    assert_eq!(
        executor
            .commit_checkpoint(&final_operation, &checkpoint_sha256)
            .await
            .expect("commit replay at capacity"),
        CompactPersistenceAppend::Replay {
            sequence: final_sequence,
        }
    );
    let unchanged = executor.snapshot().await.expect("verify rejected writes");
    assert_eq!(unchanged, full);
    assert_sqlite_integrity(&store).await;

    let lease_head = store
        .inspect_local_lease_head(lease_id)
        .await
        .expect("lease head")
        .head
        .expect("existing lease");
    store.pool.close().await;
    drop(executor);
    drop(lease);
    drop(store);
    let reopened_store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("reopen store at capacity");
    let reopened_lease = reopened_store
        .reopen_host_bound_lease(
            lease_head,
            fence.authority_epoch,
            fence.owner_epoch,
            expires_at,
        )
        .await
        .expect("reopen bound lease");
    let reopened = reopened_store
        .open_local_compact_executor_bound(journal_id, fence, &reopened_lease)
        .await
        .expect("reopen executor at capacity");
    let reopened_snapshot = reopened.snapshot().await.expect("verify reopened chain");
    assert_eq!(reopened_snapshot, full);
    let reopened_journal =
        CompactPersistenceJournal::reopen(reopened_snapshot).expect("reopen contract chain");
    assert_eq!(
        reopened_journal.state(&final_operation),
        Some(CompactPersistenceState::Committed)
    );
    assert_eq!(
        reopened_journal.state("op:compact-capacity:0"),
        Some(CompactPersistenceState::Pending)
    );
    assert_eq!(
        reopened
            .commit_checkpoint(&final_operation, &checkpoint_sha256)
            .await
            .expect("exact replay after reopen"),
        CompactPersistenceAppend::Replay {
            sequence: final_sequence,
        }
    );
    assert_sqlite_integrity(&reopened_store).await;
}
