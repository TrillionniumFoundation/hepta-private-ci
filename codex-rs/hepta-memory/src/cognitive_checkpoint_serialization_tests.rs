//! Retain the entire publication as one asynchronous admission interval while
//! allowing receipt data guards to remain synchronous and short lived.

use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn protected_checkpoint_publication_excludes_queued_checkout_until_both_acks() {
    let fixture = ManagedFixture::new().await;
    fixture
        .peer
        .hold_prepare_reply
        .store(true, Ordering::SeqCst);
    let sender = fixture.sender();
    let sending = tokio::spawn(async move { sender.retain_before_send(request()).await });
    tokio::time::timeout(Duration::from_secs(2), fixture.peer.prepared.notified())
        .await
        .expect("publication reached the protected Prepare ACK barrier");
    let preparing = fixture.peer.receipt.lock().unwrap().clone();
    assert_eq!(preparing.head.phase, CognitiveCheckpointPhase::Publishing);
    assert!(!fixture.store.commit_gate.commit_allowed());

    // Poll a real coordinator admission to Pending, then cancel it while it
    // is queued. This must not fence the active publication or release its
    // admission interval. No state/transport mutation belongs to this waiter.
    {
        let waiting = fixture.checkpoint.before_checkout();
        tokio::pin!(waiting);
        assert!(futures::poll!(&mut waiting).is_pending());
    }
    assert!(!fixture.store.commit_gate.is_fenced());

    // Exercise the actual SQLite pool's checkout hook as a second waiter.
    let checkout = fixture.store.pool.acquire();
    tokio::pin!(checkout);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), &mut checkout)
            .await
            .is_err()
    );
    assert_eq!(
        fixture.peer.commands.lock().unwrap().as_slice(),
        &[
            CognitiveCheckpointCommand::ReadHead,
            CognitiveCheckpointCommand::BeginWrites,
            CognitiveCheckpointCommand::PreparePublication,
        ],
        "no competing BeginWrites or read may interleave the two publication ACKs",
    );

    fixture
        .peer
        .hold_prepare_reply
        .store(false, Ordering::SeqCst);
    fixture.peer.resume_prepare.notify_one();
    let _ticket = tokio::time::timeout(Duration::from_secs(2), sending)
        .await
        .unwrap()
        .unwrap()
        .expect("original publication completes");
    let current = fixture.peer.receipt.lock().unwrap().clone();
    assert_eq!(current.head.phase, CognitiveCheckpointPhase::Current);
    assert_eq!(current.head.counter, preparing.head.counter + 1);
    assert!(!fixture.store.commit_gate.commit_allowed());

    let connection = tokio::time::timeout(Duration::from_secs(2), &mut checkout)
        .await
        .unwrap()
        .expect("queued original-owner checkout resumes");
    let dirty = fixture.peer.receipt.lock().unwrap().clone();
    assert_eq!(dirty.head.phase, CognitiveCheckpointPhase::Dirty);
    assert_eq!(dirty.head.counter, current.head.counter + 1);
    assert_eq!(dirty.head.last_current, current.head.last_current);
    assert!(fixture.store.commit_gate.commit_allowed());
    assert!(!fixture.store.commit_gate.is_fenced());
    assert_eq!(
        fixture.peer.commands.lock().unwrap().as_slice(),
        &[
            CognitiveCheckpointCommand::ReadHead,
            CognitiveCheckpointCommand::BeginWrites,
            CognitiveCheckpointCommand::PreparePublication,
            CognitiveCheckpointCommand::CommitPublication,
            CognitiveCheckpointCommand::BeginWrites,
        ],
    );
    drop(connection);
}

#[tokio::test]
async fn protected_checkpoint_cancelled_publication_fences_before_queued_checkout_enters() {
    let fixture = ManagedFixture::new().await;
    fixture
        .peer
        .hold_prepare_reply
        .store(true, Ordering::SeqCst);
    let sender = fixture.sender();
    let sending = tokio::spawn(async move { sender.retain_before_send(request()).await });
    tokio::time::timeout(Duration::from_secs(2), fixture.peer.prepared.notified())
        .await
        .expect("protected Prepare transition reached");
    let checkout = fixture.store.pool.acquire();
    tokio::pin!(checkout);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), &mut checkout)
            .await
            .is_err()
    );
    sending.abort();
    assert!(matches!(sending.await, Err(error) if error.is_cancelled()));
    let mut connection = tokio::time::timeout(Duration::from_secs(2), &mut checkout)
        .await
        .unwrap()
        .expect("fenced owner still permits inspection");
    assert!(fixture.store.commit_gate.is_fenced());
    assert!(!fixture.store.commit_gate.commit_allowed());
    assert!(
        sqlx::query("CREATE TABLE cancelled_prepare_bypass(v INTEGER)")
            .execute(&mut *connection)
            .await
            .is_err()
    );
    assert_eq!(
        fixture.peer.commands.lock().unwrap().as_slice(),
        &[
            CognitiveCheckpointCommand::ReadHead,
            CognitiveCheckpointCommand::BeginWrites,
            CognitiveCheckpointCommand::PreparePublication,
        ],
        "cancellation must not let the queued checkout begin a fresh transition",
    );
    assert_eq!(
        fixture.peer.receipt.lock().unwrap().head.phase,
        CognitiveCheckpointPhase::Publishing
    );
}
