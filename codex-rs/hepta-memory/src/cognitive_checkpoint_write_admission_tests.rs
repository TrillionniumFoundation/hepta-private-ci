//! Real queued SQLite writes across a later protected Current publication.

use super::*;
use crate::LocalOutcomeState;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn queued_write_rechecks_dirty_after_a_later_current_publication() {
    queued_write_after_current(false).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn queued_write_rejects_wrong_owner_dirty_ack_without_committing() {
    queued_write_after_current(true).await;
}

async fn queued_write_after_current(wrong_owner: bool) {
    let fixture = ManagedFixture::new().await;
    let mut barrier = fixture.store.begin_checkpoint_barrier().await.unwrap();
    fixture
        .writer
        .acknowledge_bound_owner_transaction(&mut barrier)
        .await
        .unwrap();
    assert_eq!(
        fixture.peer.receipt.lock().unwrap().head.phase,
        CognitiveCheckpointPhase::Current
    );

    // LocalLeaseOutbox::admit goes directly from its guarded checkout into
    // BEGIN IMMEDIATE. It has no earlier read checkout to confuse this signal.
    let lease = fixture.writer.lease.clone();
    let mut mutation =
        tokio::spawn(async move { lease.admit("queued-owner-write", "fixture", "{}").await });
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let dirty =
                fixture.peer.receipt.lock().unwrap().head.phase == CognitiveCheckpointPhase::Dirty;
            if dirty && fixture.store.commit_gate.commit_allowed() {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert!(
        tokio::time::timeout(Duration::from_millis(100), &mut mutation)
            .await
            .is_err()
    );

    // The writer already checked out, but still cannot hold SQLite's lock.
    // Republish under the retained barrier, then release exactly that lock.
    fixture
        .writer
        .acknowledge_bound_owner_transaction(&mut barrier)
        .await
        .unwrap();
    assert!(!fixture.store.commit_gate.commit_allowed());
    let current = fixture.peer.receipt.lock().unwrap().clone();
    fixture
        .peer
        .wrong_owner_reply
        .store(wrong_owner, Ordering::SeqCst);
    barrier.rollback().await.unwrap();
    let result = tokio::time::timeout(Duration::from_secs(5), mutation)
        .await
        .unwrap()
        .unwrap();
    let count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_events WHERE occurrence_key = 'queued-owner-write'",
    )
    .fetch_one(fixture.store.observation_pool())
    .await
    .unwrap();
    if wrong_owner {
        assert!(result.is_err());
        assert!(fixture.store.commit_gate.is_fenced());
        assert_eq!(count, 0);
        assert_eq!(
            fixture.store.recovery_anchor().await.unwrap(),
            current.head.last_current
        );
    } else {
        result.unwrap();
        assert!(!fixture.store.commit_gate.is_fenced());
        assert!(fixture.store.commit_gate.commit_allowed());
        assert_eq!(count, 1);
        assert_eq!(
            fixture.writer.status("queued-owner-write").await.unwrap(),
            LocalOutcomeState::Queued
        );
        assert_eq!(
            fixture.peer.receipt.lock().unwrap().head.phase,
            CognitiveCheckpointPhase::Dirty
        );
        assert_ne!(
            fixture.store.recovery_anchor().await.unwrap(),
            current.head.last_current
        );
        fixture.writer.acknowledge_current().await.unwrap();
        let published = fixture
            .peer
            .receipt
            .lock()
            .unwrap()
            .head
            .last_current
            .clone();
        assert_eq!(published, fixture.store.recovery_anchor().await.unwrap());
    }
}
