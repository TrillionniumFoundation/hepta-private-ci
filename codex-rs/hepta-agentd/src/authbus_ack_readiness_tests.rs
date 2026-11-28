//! Real signed SQLite admission and relay Ack; the injected Core queue is
//! synthetic. These scheduling controls assert no human or material authority.
use std::future::Future;
use std::pin::Pin;
use std::task::Poll;

use pretty_assertions::assert_eq;

use super::*;

async fn require_pending<F: Future>(mut future: Pin<&mut F>) {
    std::future::poll_fn(|context| {
        assert!(future.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
}

fn accepting_queue() -> ReplyLostQueue {
    ReplyLostQueue {
        lose_reply: AtomicBool::new(/*v*/ false),
        ..ReplyLostQueue::default()
    }
}

#[tokio::test]
async fn original_ack_waiter_reads_ack_committed_before_its_hint() {
    let fixture = Fixture::new().await;
    let id = submit(&fixture.state, fixture.request(/*sequence*/ 1))
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let host = attached(&fixture.state).unwrap();
    let delivery = fixture.claim(&host, id).await;
    deliver(&fixture.state, &host, &accepting_queue(), delivery)
        .await
        .unwrap();
    tokio::time::timeout(Duration::from_secs(2), host.wait_for_original_ack(id))
        .await
        .unwrap()
        .unwrap();
    let retained = host.evidence.authbus_delivery_status(id).await.unwrap();
    assert_eq!(retained.state, AuthBusDeliveryState::Acked);
    assert!(retained.acknowledgement.is_some());
}

#[tokio::test]
async fn original_ack_waiter_enabled_before_commit_cannot_lose_its_wakeup() {
    let fixture = Fixture::new().await;
    let id = submit(&fixture.state, fixture.request(/*sequence*/ 1))
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let host = attached(&fixture.state).unwrap();
    let delivery = fixture.claim(&host, id).await;
    let wait = host.wait_for_original_ack(id);
    tokio::pin!(wait);
    require_pending(wait.as_mut()).await;
    let before = host.evidence.authbus_delivery_status(id).await.unwrap();
    assert_eq!(
        (before.state, before.acknowledgement),
        (AuthBusDeliveryState::Leased, None)
    );
    deliver(&fixture.state, &host, &accepting_queue(), delivery)
        .await
        .unwrap();
    tokio::time::timeout(Duration::from_secs(2), wait)
        .await
        .unwrap()
        .unwrap();
}

#[tokio::test]
async fn original_ack_waiter_rechecks_exact_delivery_after_an_unrelated_wakeup() {
    let fixture = Fixture::new().await;
    let first = submit(&fixture.state, fixture.request(/*sequence*/ 1))
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let other = submit(&fixture.state, fixture.request(/*sequence*/ 2))
        .await
        .unwrap()
        .delivery_id
        .parse()
        .unwrap();
    let host = attached(&fixture.state).unwrap();
    let wait = host.wait_for_original_ack(first);
    tokio::pin!(wait);
    require_pending(wait.as_mut()).await;
    let delivery = fixture.claim(&host, other).await;
    deliver(&fixture.state, &host, &accepting_queue(), delivery)
        .await
        .unwrap();
    require_pending(wait.as_mut()).await;
    let before = host.evidence.authbus_delivery_status(first).await.unwrap();
    assert_eq!(
        (before.state, before.acknowledgement),
        (AuthBusDeliveryState::Queued, None)
    );
    let delivery = fixture.claim(&host, first).await;
    deliver(&fixture.state, &host, &accepting_queue(), delivery)
        .await
        .unwrap();
    tokio::time::timeout(Duration::from_secs(2), wait)
        .await
        .unwrap()
        .unwrap();
}
