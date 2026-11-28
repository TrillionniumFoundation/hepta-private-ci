//! Original PendingTraining lifetime controls before preparation. The waiting
//! future is synthetic; signed SQLite Ack races are covered beside the relay.
use std::future::Future;
use std::pin::Pin;
use std::task::Poll;

use super::*;

async fn first_pending<F: Future>(mut owner: Pin<&mut F>) {
    std::future::poll_fn(|context| {
        assert!(owner.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
}

#[tokio::test]
async fn paired_training_unacknowledged_wait_uses_the_original_pending_deadline() {
    let (pending, response) = pending();
    pending.preparing.store(/*val*/ false, Ordering::SeqCst);
    let end = pending.deadline;
    let (started_tx, started_rx) = oneshot::channel();
    let (released_tx, released_rx) = oneshot::channel();
    let owned = Released(Some(released_tx));
    let cancellation = CancellationToken::new();
    let owner = pending.complete_on_owner(&cancellation, async move {
        let _owned = owned;
        started_tx.send(()).unwrap();
        std::future::pending().await
    });
    tokio::pin!(owner);
    first_pending(owner.as_mut()).await;
    started_rx.await.unwrap();
    tokio::time::timeout(Duration::from_secs(2), owner)
        .await
        .unwrap();
    released_rx.await.unwrap();
    assert!(Instant::now() >= end);
    assert!(response.await.unwrap().is_err());
}

#[tokio::test]
async fn paired_training_owner_cancellation_drops_unacknowledged_wait_before_preparation() {
    let (pending, response) = pending();
    pending.preparing.store(/*val*/ false, Ordering::SeqCst);
    let cancellation = CancellationToken::new();
    let (started_tx, started_rx) = oneshot::channel();
    let (released_tx, released_rx) = oneshot::channel();
    let owned = Released(Some(released_tx));
    let owner = pending.complete_on_owner(&cancellation, async move {
        let _owned = owned;
        started_tx.send(()).unwrap();
        std::future::pending().await
    });
    tokio::pin!(owner);
    first_pending(owner.as_mut()).await;
    started_rx.await.unwrap();
    cancellation.cancel();
    tokio::time::timeout(Duration::from_secs(2), owner)
        .await
        .unwrap();
    released_rx.await.unwrap();
    assert!(response.await.unwrap().is_err());
}
