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
            IdleWorkPriority::QueuedInput,
            Box::pin(async { fence_rx.await.expect("terminalizer should finish") }),
            async move {
                started_tx.send(()).expect("first observer");
                release_rx.await.expect("first dispatch should settle");
            },
            std::future::pending(),
        )
        .expect("first contributor");
    queue
        .defer(
            IdleWorkPriority::QueuedInput,
            Box::pin(async {}),
            async move {
                second_tx.send(()).expect("second observer");
            },
            std::future::pending(),
        )
        .expect("second contributor");
    tokio::task::yield_now().await;
    assert_eq!(
        started_rx.try_recv(),
        Err(oneshot::error::TryRecvError::Empty)
    );
    assert_eq!(
        second_rx.try_recv(),
        Err(oneshot::error::TryRecvError::Empty)
    );
    fence_tx.send(()).expect("release exact fence");
    started_rx.await.expect("first contributor should start");
    assert_eq!(
        second_rx.try_recv(),
        Err(oneshot::error::TryRecvError::Empty)
    );
    release_tx.send(()).expect("settle first dispatch");
    second_rx.await.expect("second contributor should run");
}

#[tokio::test]
async fn deferred_idle_work_rejects_capacity_overflow() {
    let queue = DeferredIdleWork::default();
    for _ in 0..32 {
        queue
            .defer(
                IdleWorkPriority::QueuedInput,
                Box::pin(std::future::pending()),
                async {},
                std::future::pending(),
            )
            .expect("bounded pending contributor");
    }
    assert!(
        queue
            .defer(
                IdleWorkPriority::AutomaticContinuation,
                Box::pin(async {}),
                async {},
                std::future::pending()
            )
            .is_err()
    );
}

#[tokio::test]
async fn later_queued_input_precedes_automatic_work_observing_the_same_fence() {
    let queue = DeferredIdleWork::default();
    let (fence_tx, fence_rx) = oneshot::channel();
    let fence = async move { fence_rx.await.expect("terminalizer should finish") }
        .boxed()
        .shared();
    let order = Arc::new(Mutex::new(Vec::new()));
    let (queued_tx, queued_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    let (finished_tx, finished_rx) = oneshot::channel();
    let automatic_order = Arc::clone(&order);
    queue
        .defer(
            IdleWorkPriority::AutomaticContinuation,
            Box::pin(fence.clone()),
            async move { automatic_order.lock().unwrap().push("automatic-1") },
            std::future::pending(),
        )
        .expect("an older notification registers automatic work first");
    let queued_order = Arc::clone(&order);
    queue
        .defer(
            IdleWorkPriority::QueuedInput,
            Box::pin(fence.clone()),
            async move {
                queued_order.lock().unwrap().push("queued-1");
                queued_tx.send(()).expect("queued observer");
                release_rx.await.expect("queued admission should settle");
            },
            std::future::pending(),
        )
        .expect("the terminalizer registers queued input later");
    let automatic_order = Arc::clone(&order);
    queue
        .defer(
            IdleWorkPriority::AutomaticContinuation,
            Box::pin(fence.clone()),
            async move {
                automatic_order.lock().unwrap().push("automatic-2");
                finished_tx.send(()).expect("automatic observer");
            },
            std::future::pending(),
        )
        .expect("automatic registration order is retained");
    let queued_order = Arc::clone(&order);
    queue
        .defer(
            IdleWorkPriority::QueuedInput,
            Box::pin(fence),
            async move { queued_order.lock().unwrap().push("queued-2") },
            std::future::pending(),
        )
        .expect("queued registration order is retained");

    fence_tx.send(()).expect("all idle callbacks have returned");
    tokio::time::timeout(std::time::Duration::from_secs(5), queued_rx)
        .await
        .expect("queue must not wait for earlier automatic work")
        .expect("queue should start");
    assert_eq!(*order.lock().unwrap(), vec!["queued-1"]);
    release_tx.send(()).expect("settle queued admission");
    tokio::time::timeout(std::time::Duration::from_secs(5), finished_rx)
        .await
        .expect("automatic work should follow queued input")
        .expect("automatic work should finish");
    assert_eq!(
        *order.lock().unwrap(),
        vec!["queued-1", "queued-2", "automatic-1", "automatic-2"]
    );
}

#[tokio::test]
async fn thread_termination_cancels_waiting_idle_work_without_running_it() {
    let queue = DeferredIdleWork::default();
    let (terminated_tx, terminated_rx) = oneshot::channel();
    let terminated = async move { terminated_rx.await.expect("termination observer") }
        .boxed()
        .shared();
    let mut observers = Vec::new();
    for index in 0..32 {
        let (ran_tx, ran_rx) = oneshot::channel();
        observers.push(ran_rx);
        let priority = if index % 2 == 0 {
            IdleWorkPriority::AutomaticContinuation
        } else {
            IdleWorkPriority::QueuedInput
        };
        queue
            .defer(
                priority,
                Box::pin(std::future::pending()),
                async move { ran_tx.send(()).expect("work observer") },
                terminated.clone(),
            )
            .expect("defer pending work in both priority chains");
    }
    terminated_tx.send(()).expect("terminate thread");
    for observer in observers {
        assert!(observer.await.is_err());
    }
    assert_eq!(queue.capacity.available_permits(), 32);
}
