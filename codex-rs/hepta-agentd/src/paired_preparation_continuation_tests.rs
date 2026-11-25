//! Synthetic registrations, actual journal transactions and original owner
//! cancellation. These controls never construct VerifiedHumanTurn or a
//! VerifiedPairedTurn, mint a grant, or provide material/participant authority.
use pretty_assertions::assert_eq;

use super::*;

#[tokio::test]
async fn fresh_original_receipt_is_unique_under_concurrent_journal_preparation() {
    let fixture = Fixture::new();
    let journal = fixture.journal().await;
    let request = request(&journal);
    let left_preparing = AtomicBool::new(false);
    let right_preparing = AtomicBool::new(false);
    let (left, right) = tokio::join!(
        journal.retain_original_receipt(&request, payload(&journal, &request), &left_preparing),
        journal.retain_original_receipt(&request, payload(&journal, &request), &right_preparing),
    );
    let (left, right) = (left.unwrap(), right.unwrap());
    let (fresh, retained) = match (left, right) {
        (fresh @ PreparedOriginal::Fresh { .. }, PreparedOriginal::Retained(retained))
        | (PreparedOriginal::Retained(retained), fresh @ PreparedOriginal::Fresh { .. }) => {
            (fresh, retained)
        }
        (PreparedOriginal::Fresh { .. }, PreparedOriginal::Fresh { .. })
        | (PreparedOriginal::Retained(_), PreparedOriginal::Retained(_)) => {
            panic!("one original transaction must own the only fresh continuation")
        }
    };
    assert_eq!(
        fresh.into_observation(),
        PairedPreparationResponse::FreshPrepared(retained),
    );
    let before = journal.writer.recovery_anchor().await.unwrap();
    let original = journal.retained(&request).await.unwrap().unwrap();
    let repeat = journal
        .retain_original_receipt(
            &request,
            payload(&journal, &request),
            &AtomicBool::new(false),
        )
        .await
        .unwrap();
    assert!(matches!(&repeat, PreparedOriginal::Retained(_)));
    assert_eq!(
        repeat.into_observation(),
        PairedPreparationResponse::RetainedReadOnly(original),
    );
    assert_eq!(journal.writer.recovery_anchor().await.unwrap(), before);
}

#[tokio::test]
async fn dropped_fresh_receipt_cannot_be_reconstructed_after_writer_reopen() {
    let fixture = Fixture::new();
    let journal = fixture.journal().await;
    let request = request(&journal);
    let fresh = journal
        .retain_original_receipt(
            &request,
            payload(&journal, &request),
            &AtomicBool::new(false),
        )
        .await
        .unwrap();
    assert!(matches!(&fresh, PreparedOriginal::Fresh { .. }));
    let original = journal.retained(&request).await.unwrap().unwrap();
    let held_writer = Arc::downgrade(&journal.writer);
    drop(journal);
    // The private value holds this actual writer until it is consumed/dropped;
    // it is not an identity that reopens another writer from a path.
    assert!(held_writer.upgrade().is_some());
    drop(fresh);
    assert!(held_writer.upgrade().is_none());
    let reopened = fixture.journal().await;
    let before = reopened.writer.recovery_anchor().await.unwrap();
    let repeat = reopened
        .retain_original_receipt(
            &request,
            payload(&reopened, &request),
            &AtomicBool::new(false),
        )
        .await
        .unwrap();
    assert!(matches!(&repeat, PreparedOriginal::Retained(_)));
    assert_eq!(
        repeat.into_observation(),
        PairedPreparationResponse::RetainedReadOnly(original),
    );
    assert_eq!(reopened.writer.recovery_anchor().await.unwrap(), before);
}

enum ContinuationLoss {
    OriginalOwner,
    CallerReply,
}

async fn lose_after_original_commit(loss: ContinuationLoss) {
    let fixture = Fixture::new();
    let journal = Arc::new(fixture.journal().await);
    let request = request(&journal);
    let (client, mut lane) = channel(
        Arc::clone(&journal.writer),
        journal.registration.clone(),
        journal.route.clone(),
    )
    .unwrap();
    let call = request.clone();
    let caller = tokio::spawn(async move { client.prepare(call).await });
    let pending = lane.receiver.recv().await.unwrap();
    drop(lane);
    let preparing = Arc::clone(&pending.preparing);
    let cancellation = CancellationToken::new();
    let owner_cancel = cancellation.clone();
    let owner_journal = Arc::clone(&journal);
    let call = request.clone();
    let (committed, entered) = oneshot::channel();
    let (released, observed) = oneshot::channel();
    struct ReleaseOnDrop(Option<oneshot::Sender<()>>);
    impl Drop for ReleaseOnDrop {
        fn drop(&mut self) {
            if let Some(sender) = self.0.take() {
                let _ = sender.send(());
            }
        }
    }
    let owner = tokio::spawn(async move {
        pending
            .complete_on_owner(&owner_cancel, async {
                let _released = ReleaseOnDrop(Some(released));
                let original = owner_journal
                    .retain_original_receipt(&call, payload(&owner_journal, &call), &preparing)
                    .await?;
                assert!(matches!(&original, PreparedOriginal::Fresh { .. }));
                let _ = committed.send(());
                std::future::pending::<()>().await;
                Ok(original.into_observation())
            })
            .await;
    });
    entered.await.unwrap();
    // Only the journal and its actual fresh continuation own this writer.
    assert_eq!(Arc::strong_count(&journal.writer), 2);
    match loss {
        ContinuationLoss::OriginalOwner => {
            cancellation.cancel();
            assert_eq!(
                caller.await.unwrap().unwrap(),
                PairedPreparationResponse::Unknown {
                    operation_id: operation_id(request.original.delivery_id),
                },
            );
        }
        ContinuationLoss::CallerReply => {
            caller.abort();
            assert!(matches!(caller.await, Err(error) if error.is_cancelled()));
        }
    }
    tokio::time::timeout(Duration::from_secs(1), owner)
        .await
        .unwrap()
        .unwrap();
    observed.await.unwrap();
    assert_eq!(Arc::strong_count(&journal.writer), 1);
    let original = journal.retained(&request).await.unwrap().unwrap();
    let held_writer = Arc::downgrade(&journal.writer);
    drop(journal);
    assert!(held_writer.upgrade().is_none());
    let reopened = fixture.journal().await;
    let before = reopened.writer.recovery_anchor().await.unwrap();
    let repeat = reopened
        .retain_original_receipt(
            &request,
            payload(&reopened, &request),
            &AtomicBool::new(false),
        )
        .await
        .unwrap();
    assert!(matches!(&repeat, PreparedOriginal::Retained(_)));
    assert_eq!(
        repeat.into_observation(),
        PairedPreparationResponse::RetainedReadOnly(original),
    );
    assert_eq!(reopened.writer.recovery_anchor().await.unwrap(), before);
}

#[tokio::test]
async fn cancelled_original_owner_drops_actual_fresh_receipt_before_reopen() {
    lose_after_original_commit(ContinuationLoss::OriginalOwner).await;
}

#[tokio::test]
async fn lost_caller_reply_drops_actual_fresh_receipt_before_reopen() {
    lose_after_original_commit(ContinuationLoss::CallerReply).await;
}
