//! Exercise original managed SQLite/lease/publication paths. The protocol peer
//! is an explicit test double; these are not native or Root-service evidence.

use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn original_owner_current_acknowledges_exact_cut_without_objective_or_retirement() {
    let fixture = ManagedFixture::new().await;
    fixture
        .writer
        .admit("native-current-observation", "native-current", "{}")
        .await
        .unwrap();
    let committed = fixture.store.recovery_anchor().await.unwrap();
    let old = fixture.peer.receipt.lock().unwrap().clone();
    assert_eq!(old.head.phase, CognitiveCheckpointPhase::Dirty);
    fixture.writer.acknowledge_current().await.unwrap();
    let observed = fixture.peer.receipt.lock().unwrap().clone();
    assert_eq!(observed.head.phase, CognitiveCheckpointPhase::Current);
    assert_eq!(observed.head.last_current, committed);
    assert_eq!(observed.head.proposal, None);
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), committed);
    assert!(!fixture.store.commit_gate.commit_allowed());
    assert!(!fixture.writer.checkpoint_fenced());

    // Repeating a confirmed observation does not append another source event
    // or increment the actual protected Current's publication counter.
    fixture.writer.acknowledge_current().await.unwrap();
    assert_eq!(*fixture.peer.receipt.lock().unwrap(), observed);
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), committed);
}

#[tokio::test]
async fn original_owner_current_ack_rechecks_revocation_after_publication() {
    let fixture = ManagedFixture::new().await;
    fixture
        .peer
        .revoke_after_publication
        .store(true, Ordering::SeqCst);
    assert!(fixture.writer.acknowledge_current().await.is_err());
    assert_eq!(
        fixture.peer.receipt.lock().unwrap().head.phase,
        CognitiveCheckpointPhase::Current
    );
    assert!(fixture.writer.checkpoint_fenced());
    assert!(!fixture.store.commit_gate.commit_allowed());
}

#[tokio::test]
async fn lost_original_current_reply_fences_the_same_writer_without_retrying_publication() {
    let fixture = ManagedFixture::new().await;
    fixture
        .peer
        .hold_current_reply
        .store(true, Ordering::SeqCst);
    assert!(matches!(
        fixture.writer.acknowledge_current().await,
        Err(ProductionWriterError::CheckpointFenced)
    ));
    assert_eq!(
        fixture.peer.receipt.lock().unwrap().head.phase,
        CognitiveCheckpointPhase::Current
    );
    assert!(fixture.writer.checkpoint_fenced());
    assert!(!fixture.store.commit_gate.commit_allowed());
    let committed = fixture.peer.receipt.lock().unwrap().clone();
    let commands = fixture.peer.commands.lock().unwrap().len();
    let cut = fixture.store.recovery_anchor().await.unwrap();
    fixture
        .peer
        .hold_current_reply
        .store(false, Ordering::SeqCst);
    // The original permanently fenced coordinator may settle this unchanged
    // cut by an independent ReadHead. It cannot retry publication, reopen the
    // writer, mint a send ticket or admit another source write.
    fixture.writer.acknowledge_current().await.unwrap();
    assert_eq!(
        &fixture.peer.commands.lock().unwrap()[commands..],
        &[CognitiveCheckpointCommand::ReadHead]
    );
    assert_eq!(*fixture.peer.receipt.lock().unwrap(), committed);
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), cut);
    assert!(fixture.writer.checkpoint_fenced());
    assert!(!fixture.store.commit_gate.commit_allowed());
    assert!(
        fixture
            .writer
            .admit("fenced-native-current", "native-current", "{}")
            .await
            .is_err()
    );
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), cut);
}
