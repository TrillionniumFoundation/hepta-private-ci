use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tempfile::TempDir;

use crate::CognitiveStore;
use crate::CompactCheckpoint;
use crate::CompactFence;
use crate::CompactLease;
use crate::CompactLossReport;
use crate::CompactParentSnapshot;
use crate::CompactPersistenceAppend;
use crate::CompactSummaryReceipt;
use crate::LOCAL_ATOMIC_WITNESS_EXTERNAL_EFFECTS;
use crate::LOCAL_ATOMIC_WITNESS_KG_WRITE_AUTHORITY;
use crate::LOCAL_ATOMIC_WITNESS_LEASE_EPOCH_BOUND;
use crate::LOCAL_ATOMIC_WITNESS_LEASE_EXPIRY_BOUND;
use crate::LOCAL_ATOMIC_WITNESS_LIFECYCLE_REGISTERED;
use crate::LOCAL_ATOMIC_WITNESS_NAMESPACE;
use crate::LocalAtomicWitnessError;
use crate::LocalAtomicWitnessFault;
use crate::LocalLeaseAcquire;
use crate::LocalRehydrationWitnessReceipt;
use crate::LocalRehydrationWitnessWrite;
use crate::checkpoint_digest;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::write_local_rehydration_witness_with_fault;

fn fence() -> CompactFence {
    CompactFence::new(7, 11, 1, "e16-fence").expect("fence")
}

fn snapshot(fence: CompactFence) -> CompactParentSnapshot {
    CompactParentSnapshot::new(
        "ctx:e16",
        1,
        4,
        2,
        Sha256Digest::for_bytes(b"e16-parent"),
        fence,
    )
    .expect("parent snapshot")
}

fn checkpoint(fence: CompactFence) -> CompactCheckpoint {
    CompactCheckpoint::new(
        "checkpoint:e16",
        CompactLease::from_snapshot(snapshot(fence)),
        Vec::new(),
        CompactSummaryReceipt::new(
            Sha256Digest::for_bytes(b"e16-summary"),
            Sha256Digest::for_bytes(b"e16-model"),
            Sha256Digest::for_bytes(b"e16-policy"),
        ),
        CompactLossReport::new(Vec::new(), 0, Vec::new(), 0).expect("loss report"),
        0,
    )
    .expect("checkpoint")
}

async fn prepared(
    number: u8,
) -> (
    TempDir,
    CognitiveStore,
    crate::LocalLeaseOutbox,
    crate::LocalCompactExecutor,
    CompactCheckpoint,
) {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(number);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let current_fence = fence();
    let expires_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_secs()
        + 3600;
    let lease = match store
        .acquire_local_lease_bound(
            "lease:e16",
            current_fence.authority_epoch,
            current_fence.owner_epoch,
            1,
            current_fence.fencing_token.clone(),
            expires_at,
        )
        .await
        .expect("lease")
    {
        LocalLeaseAcquire::Acquired(lease) | LocalLeaseAcquire::Replay(lease) => lease,
    };
    let executor = store
        .open_local_compact_executor_bound("journal:e16", current_fence.clone(), &lease)
        .await
        .expect("executor");
    let current = snapshot(current_fence.clone());
    let checkpoint = checkpoint(current_fence);
    assert_eq!(
        executor
            .append_intent("operation:e16", &checkpoint, &current)
            .await
            .expect("intent"),
        CompactPersistenceAppend::Appended { sequence: 1 }
    );
    let digest = checkpoint_digest(&checkpoint).expect("checkpoint digest");
    assert_eq!(
        executor
            .commit_checkpoint("operation:e16", &digest)
            .await
            .expect("commit"),
        CompactPersistenceAppend::Appended { sequence: 2 }
    );
    (temp, store, lease, executor, checkpoint)
}

#[tokio::test]
async fn writer_couples_lease_fence_and_compact_witness_idempotently() {
    let (_temp, store, lease, executor, checkpoint) = prepared(201).await;

    let first = store
        .write_local_rehydration_witness(&lease, &executor, "operation:e16", &checkpoint, 0)
        .await
        .expect("first witness");
    let LocalRehydrationWitnessWrite::Appended(first_receipt) = first else {
        panic!("first witness must append");
    };
    assert_eq!(first_receipt.witness_sequence, 3);
    assert!(!first_receipt.replayed);
    assert_eq!(first_receipt.namespace, LOCAL_ATOMIC_WITNESS_NAMESPACE);
    assert!(!first_receipt.external_effect);
    assert!(!first_receipt.kg_write_authority);
    assert!(!first_receipt.lifecycle_registered);
    assert!(first_receipt.lease_epoch_bound);
    assert!(first_receipt.lease_expiry_bound);

    let replay = store
        .write_local_rehydration_witness(&lease, &executor, "operation:e16", &checkpoint, 0)
        .await
        .expect("replay witness");
    let LocalRehydrationWitnessWrite::Replay(replay_receipt) = replay else {
        panic!("second witness must replay");
    };
    assert_eq!(
        replay_receipt.witness_sequence,
        first_receipt.witness_sequence
    );
    assert!(replay_receipt.replayed);
    assert_eq!(
        executor.snapshot().await.expect("snapshot").entries.len(),
        3
    );
    lease.verify_current().await.expect("lease remains active");
}

#[tokio::test]
async fn writer_fault_rolls_back_compact_row_and_allows_exact_retry() {
    let (_temp, store, lease, executor, checkpoint) = prepared(202).await;
    let error = write_local_rehydration_witness_with_fault(
        &lease,
        &executor,
        "operation:e16",
        &checkpoint,
        0,
        LocalAtomicWitnessFault::AfterWitnessInsertBeforeCommit,
    )
    .await
    .expect_err("fault must abort transaction");
    assert!(matches!(
        error,
        LocalAtomicWitnessError::TransactionAborted(_)
    ));
    assert_eq!(
        executor.snapshot().await.expect("snapshot").entries.len(),
        2
    );
    assert!(
        executor
            .rehydration("operation:e16")
            .await
            .expect("rehydration lookup")
            .is_none()
    );

    let retry = store
        .write_local_rehydration_witness(&lease, &executor, "operation:e16", &checkpoint, 0)
        .await
        .expect("retry");
    assert!(matches!(retry, LocalRehydrationWitnessWrite::Appended(_)));
}

#[tokio::test]
async fn writer_rejects_stale_or_terminal_lease_and_fence_rebinding() {
    let (_temp, store, lease, executor, checkpoint) = prepared(203).await;
    let released = lease.release().await.expect("release");
    let stale = store
        .write_local_rehydration_witness(&lease, &executor, "operation:e16", &checkpoint, 0)
        .await;
    assert!(matches!(stale, Err(LocalAtomicWitnessError::Lease(_))));
    assert_eq!(released.state, crate::LocalLeaseState::Released);

    let (_temp2, store2, lease2, _executor2, checkpoint2) = prepared(204).await;
    let wrong_fence = CompactFence::new(7, 11, 1, "other-fence").expect("wrong fence");
    let wrong_executor = store2
        .open_local_compact_executor("journal:wrong", wrong_fence.clone())
        .await
        .expect("wrong executor");
    let mismatch = store2
        .write_local_rehydration_witness(&lease2, &wrong_executor, "operation:e16", &checkpoint2, 0)
        .await;
    assert!(matches!(
        mismatch,
        Err(LocalAtomicWitnessError::FenceMismatch(_))
    ));
}

#[test]
fn writer_boundary_flags_are_fail_closed() {
    const {
        assert!(!LOCAL_ATOMIC_WITNESS_EXTERNAL_EFFECTS);
        assert!(!LOCAL_ATOMIC_WITNESS_KG_WRITE_AUTHORITY);
        assert!(!LOCAL_ATOMIC_WITNESS_LIFECYCLE_REGISTERED);
        assert!(LOCAL_ATOMIC_WITNESS_LEASE_EPOCH_BOUND);
        assert!(LOCAL_ATOMIC_WITNESS_LEASE_EXPIRY_BOUND);
    }
}

#[tokio::test]
async fn witness_receipt_validation_rejects_tampered_digest_and_identity() {
    let (_temp, store, lease, executor, checkpoint) = prepared(205).await;
    let write = store
        .write_local_rehydration_witness(&lease, &executor, "operation:e16", &checkpoint, 0)
        .await
        .expect("witness");
    let receipt = write.receipt().clone();

    let mut encoded = serde_json::to_value(&receipt).expect("receipt json");
    encoded["checkpoint_sha256"] = serde_json::Value::String("not-a-digest".to_string());
    let tampered: LocalRehydrationWitnessReceipt =
        serde_json::from_value(encoded).expect("tampered receipt shape");
    assert!(tampered.validate().is_err());

    let mut invalid_identity = receipt;
    invalid_identity.journal_id.push('\0');
    assert!(invalid_identity.validate().is_err());
}
