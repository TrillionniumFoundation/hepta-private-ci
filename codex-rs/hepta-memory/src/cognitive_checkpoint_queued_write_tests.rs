//! A checked-out writer must reauthorize Dirty after a queued SQLite BEGIN.

use super::*;

#[tokio::test]
async fn queued_writer_reconfirms_dirty_after_intervening_current_publication() {
    let fixture = ManagedFixture::new().await;
    fixture.writer.acknowledge_current().await.unwrap();
    fixture.peer.commands.lock().unwrap().clear();
    let mut barrier = fixture.store.begin_checkpoint_barrier().await.unwrap();
    let dirty = fixture.peer.dirty.notified();
    tokio::pin!(dirty);
    let _ = dirty.as_mut().enable();
    let writer = fixture.writer.clone();
    let mut mutation = tokio::spawn(async move {
        writer.admit("queued-after-current", "fixture", "{}").await
    });
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), &mut dirty)
        .await
        .unwrap();
    // Checkout has received Dirty, but this real SQLite lock keeps BEGIN queued.
    fixture
        .writer
        .acknowledge_bound_owner_transaction(&mut barrier)
        .await
        .unwrap();
    let current = fixture
        .peer
        .receipt
        .lock()
        .unwrap()
        .head
        .last_current
        .clone();
    assert!(!fixture.store.commit_gate.commit_allowed());
    assert!(
        tokio::time::timeout(Duration::from_millis(/*millis*/ 20), &mut mutation)
            .await
            .is_err()
    );
    barrier.rollback().await.unwrap();
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), mutation)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(
        fixture.peer.commands.lock().unwrap().as_slice(),
        &[
            CognitiveCheckpointCommand::BeginWrites,
            CognitiveCheckpointCommand::PreparePublication,
            CognitiveCheckpointCommand::CommitPublication,
            CognitiveCheckpointCommand::BeginWrites,
        ]
    );
    assert!(!fixture.writer.checkpoint_fenced());
    assert!(fixture.store.commit_gate.commit_allowed());
    assert_ne!(fixture.store.recovery_anchor().await.unwrap(), current);
}

#[tokio::test]
async fn queued_writer_rejects_mismatched_dirty_ack_after_acquiring_sqlite_lock() {
    let fixture = ManagedFixture::new().await;
    fixture.writer.acknowledge_current().await.unwrap();
    let mut barrier = fixture.store.begin_checkpoint_barrier().await.unwrap();
    let dirty = fixture.peer.dirty.notified();
    tokio::pin!(dirty);
    let _ = dirty.as_mut().enable();
    let writer = fixture.writer.clone();
    let mutation = tokio::spawn(async move {
        writer.admit("queued-wrong-owner", "fixture", "{}").await
    });
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), &mut dirty)
        .await
        .unwrap();
    fixture
        .writer
        .acknowledge_bound_owner_transaction(&mut barrier)
        .await
        .unwrap();
    let current = fixture
        .peer
        .receipt
        .lock()
        .unwrap()
        .head
        .last_current
        .clone();
    fixture
        .peer
        .wrong_owner_reply
        .store(/*val*/ true, Ordering::SeqCst);
    barrier.rollback().await.unwrap();
    assert!(
        tokio::time::timeout(Duration::from_secs(/*secs*/ 5), mutation)
            .await
            .unwrap()
            .unwrap()
            .is_err()
    );
    assert!(fixture.writer.checkpoint_fenced());
    assert!(!fixture.store.commit_gate.commit_allowed());
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), current);
    fixture
        .peer
        .wrong_owner_reply
        .store(/*val*/ false, Ordering::SeqCst);
    assert!(
        fixture
            .writer
            .admit("after-wrong-dirty", "fixture", "{}")
            .await
            .is_err()
    );
}

#[tokio::test]
async fn cancelled_queued_writer_fences_uncertain_dirty_and_releases_sqlite_lock() {
    let fixture = ManagedFixture::new().await;
    fixture.writer.acknowledge_current().await.unwrap();
    let mut barrier = fixture.store.begin_checkpoint_barrier().await.unwrap();
    let first_dirty = fixture.peer.dirty.notified();
    tokio::pin!(first_dirty);
    let _ = first_dirty.as_mut().enable();
    let writer = fixture.writer.clone();
    let mutation = tokio::spawn(async move {
        writer.admit("queued-cancelled", "fixture", "{}").await
    });
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), &mut first_dirty)
        .await
        .unwrap();
    fixture
        .writer
        .acknowledge_bound_owner_transaction(&mut barrier)
        .await
        .unwrap();
    let current = fixture
        .peer
        .receipt
        .lock()
        .unwrap()
        .head
        .last_current
        .clone();
    fixture
        .peer
        .hold_dirty_reply
        .store(/*val*/ true, Ordering::SeqCst);
    let next_dirty = fixture.peer.dirty.notified();
    tokio::pin!(next_dirty);
    let _ = next_dirty.as_mut().enable();
    barrier.rollback().await.unwrap();
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), &mut next_dirty)
        .await
        .unwrap();
    mutation.abort();
    assert!(matches!(mutation.await, Err(error) if error.is_cancelled()));
    assert!(fixture.writer.checkpoint_fenced());
    assert!(!fixture.store.commit_gate.commit_allowed());
    let barrier = tokio::time::timeout(
        Duration::from_secs(/*secs*/ 5),
        fixture.store.begin_checkpoint_barrier(),
    )
    .await
    .unwrap()
    .unwrap();
    barrier.rollback().await.unwrap();
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), current);
    fixture
        .peer
        .hold_dirty_reply
        .store(/*val*/ false, Ordering::SeqCst);
    assert!(
        fixture
            .writer
            .admit("after-cancelled-dirty", "fixture", "{}")
            .await
            .is_err()
    );
}
