//! Read-only whole-owner Current checks use the original protected peer.
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn owner_current_readback_is_exact_without_publishing_or_new_source_events() {
    let fixture = ManagedFixture::new().await;
    fixture.writer.acknowledge_current().await.unwrap();
    let before = fixture.peer.receipt.lock().unwrap().clone();
    let cut = fixture.store.recovery_anchor().await.unwrap();
    for _ in 0..2 {
        assert_eq!(
            fixture
                .writer
                .observed_current_owner_receipt()
                .await
                .unwrap(),
            before
        );
    }
    assert_eq!(*fixture.peer.receipt.lock().unwrap(), before);
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), cut);

    fixture
        .writer
        .admit("readback-dirty", "fixture", "{}")
        .await
        .unwrap();
    assert_eq!(
        fixture.peer.receipt.lock().unwrap().head.phase,
        CognitiveCheckpointPhase::Dirty
    );
    assert!(
        fixture
            .writer
            .observed_current_owner_receipt()
            .await
            .is_err()
    );
}

#[tokio::test]
async fn owner_current_readback_refuses_changed_peer_and_fenced_owner() {
    let fixture = ManagedFixture::new().await;
    fixture.writer.acknowledge_current().await.unwrap();
    fixture.peer.wrong_owner_reply.store(true, Ordering::SeqCst);
    assert!(
        fixture
            .writer
            .observed_current_owner_receipt()
            .await
            .is_err()
    );
    fixture
        .peer
        .wrong_owner_reply
        .store(false, Ordering::SeqCst);
    assert!(
        fixture
            .writer
            .observed_current_owner_receipt()
            .await
            .is_ok()
    );
    drop(fixture.store.commit_gate.transition_attempt());
    assert!(
        fixture
            .writer
            .observed_current_owner_receipt()
            .await
            .is_err()
    );
}

#[tokio::test]
async fn owner_current_readback_refuses_current_for_a_different_actual_local_cut() {
    let fixture = ManagedFixture::new().await;
    let earlier_cut = fixture
        .peer
        .receipt
        .lock()
        .unwrap()
        .head
        .last_current
        .clone();
    fixture.writer.acknowledge_current().await.unwrap();
    let current = fixture.peer.receipt.lock().unwrap().clone();
    assert_ne!(earlier_cut, current.head.last_current);
    // This explicit protected-protocol fixture presents a self-consistent
    // Current on both sides of the original coordinator, for an older cut.
    // Only the original SQLite barrier's actual cut equality can reject it.
    let mut stale = current.clone();
    stale.head.last_current = earlier_cut;
    stale.token = token_for(&stale.head);
    fixture
        .checkpoint
        .fixture_replace_receipt_for_stale_current_test(stale.clone())
        .await;
    *fixture.peer.receipt.lock().unwrap() = stale;
    assert!(
        fixture
            .writer
            .observed_current_owner_receipt()
            .await
            .is_err()
    );
    assert_eq!(
        fixture.store.recovery_anchor().await.unwrap(),
        current.head.last_current
    );
}
