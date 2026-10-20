use pretty_assertions::assert_eq;

use super::*;

#[tokio::test]
async fn deferred_idle_contributors_wait_for_fence_and_preserve_registration_order() {
    let queue = DeferredIdleWork::default();
    let (fence_tx, fence_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    let (started_tx, mut started_rx) = oneshot::channel();
    let (second_tx, mut second_rx) = oneshot::channel();
    queue
        .defer(
            Box::pin(async { fence_rx.await.expect("terminalizer should finish") }),
            async move {
                started_tx.send(()).expect("first observer");
                release_rx.await.expect("first dispatch should settle");
            },
        )
        .expect("first contributor");
    queue
        .defer(Box::pin(async {}), async move {
            second_tx.send(()).expect("second observer");
        })
        .expect("second contributor");
    tokio::task::yield_now().await;
    assert_eq!(started_rx.try_recv(), Err(oneshot::error::TryRecvError::Empty));
    assert_eq!(second_rx.try_recv(), Err(oneshot::error::TryRecvError::Empty));
    fence_tx.send(()).expect("release exact fence");
    started_rx.await.expect("first contributor should start");
    assert_eq!(second_rx.try_recv(), Err(oneshot::error::TryRecvError::Empty));
    release_tx.send(()).expect("settle first dispatch");
    second_rx.await.expect("second contributor should run");
}

#[tokio::test]
async fn deferred_idle_work_rejects_capacity_overflow() {
    let queue = DeferredIdleWork::default();
    for _ in 0..32 {
        queue
            .defer(Box::pin(std::future::pending()), async {})
            .expect("bounded pending contributor");
    }
    assert!(queue.defer(Box::pin(async {}), async {}).is_err());
}
