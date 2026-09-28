use std::sync::mpsc;
use std::time::Duration;

use super::*;

#[tokio::test]
async fn cancelled_wait_keeps_the_actual_shadow_worker_charged() {
    let executor = Arc::new(RetrievalExecutor::new());
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let running = Arc::clone(&executor);
    let task = tokio::spawn(async move {
        let request = running.begin(RetrievalWorkClass::Shadow);
        running
            .run(&request, RetrievalBlockingKind::Core, move |control| {
                entered_tx.send(()).unwrap();
                release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                control.checkpoint().map_err(|error| error.to_string())
            })
            .await
    });
    tokio::task::spawn_blocking(move || entered_rx.recv_timeout(Duration::from_secs(5)))
        .await
        .unwrap()
        .unwrap();
    task.abort();
    let _ = task.await;
    assert_eq!(executor.shadow.available_permits(), 0);
    let request = executor.begin(RetrievalWorkClass::Shadow);
    assert!(executor.run(&request, RetrievalBlockingKind::Core, |_| Ok(())).await.is_err());
    // The delivery lane is independent of a blocked shadow worker.
    let delivery = executor.begin(RetrievalWorkClass::Delivery);
    assert_eq!(executor.run(&delivery, RetrievalBlockingKind::Core, |_| Ok(17)).await.unwrap(), 17);
    release_tx.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if executor.shadow.available_permits() == 1 {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn timeout_cannot_return_late_success_or_extend_the_request_budget() {
    let executor = RetrievalExecutor::new();
    let request = executor.begin(RetrievalWorkClass::Shadow);
    let result = executor
        .run(&request, RetrievalBlockingKind::Core, |control| {
            loop {
                match control.checkpoint() {
                    Ok(()) => std::thread::sleep(Duration::from_millis(1)),
                    Err(error) => return Err::<(), String>(error.to_string()),
                }
            }
        })
        .await;
    assert!(result.is_err());
    assert!(executor.run(&request, RetrievalBlockingKind::Core, |_| Ok(())).await.is_err());
}

#[tokio::test]
async fn cancelled_shadow_preserves_baseline_delivery() {
    let executor = RetrievalExecutor::new();
    let delivery = executor.begin(RetrievalWorkClass::Delivery);
    let shadow = executor.begin_shadow(&delivery);
    shadow.control.cancel();
    assert!(executor.run_async(&shadow, async { 1 }).await.is_err());
    assert_eq!(executor.run(&delivery, RetrievalBlockingKind::Core, |_| Ok(2)).await.unwrap(), 2);
    assert_eq!(executor.run_async(&delivery, async { 3 }).await.unwrap(), 3);
}

#[tokio::test]
async fn shadow_cannot_renew_an_expired_parent_deadline() {
    let executor = RetrievalExecutor::new();
    let mut parent = executor.begin(RetrievalWorkClass::Delivery);
    parent.deadline = Instant::now();
    let child = executor.begin_shadow(&parent);
    assert!(child.deadline <= parent.deadline);
    assert!(executor.run_async(&child, async { 1 }).await.is_err());
}

#[tokio::test]
async fn async_timeout_retains_capacity_until_owner_exits() {
    let executor = RetrievalExecutor::new();
    let request = executor.begin(RetrievalWorkClass::Shadow);
    let (release_tx, release_rx) = tokio::sync::oneshot::channel::<()>();
    assert!(
        executor
            .run_async(&request, async move {
                let _ = release_rx.await;
                17
            })
            .await
            .is_err()
    );
    assert_eq!(executor.shadow.available_permits(), 0);
    let other = executor.begin(RetrievalWorkClass::Shadow);
    assert!(executor.run_async(&other, async { 18 }).await.is_err());
    let delivery = executor.begin(RetrievalWorkClass::Delivery);
    assert_eq!(
        executor.run_async(&delivery, async { 19 }).await.unwrap(),
        19
    );
    release_tx.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(5), async {
        while executor.shadow.available_permits() != 1 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert!(executor.run_async(&request, async { 20 }).await.is_err());
}

#[tokio::test]
async fn cancelled_async_wait_keeps_the_owner_operation_charged() {
    let executor = Arc::new(RetrievalExecutor::new());
    let (entered_tx, entered_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = tokio::sync::oneshot::channel::<()>();
    let running = Arc::clone(&executor);
    let waiter = tokio::spawn(async move {
        let request = running.begin(RetrievalWorkClass::Delivery);
        running
            .run_async(&request, async move {
                let _ = entered_tx.send(());
                let _ = release_rx.await;
                1
            })
            .await
    });
    entered_rx.await.unwrap();
    waiter.abort();
    let _ = waiter.await;
    assert_eq!(executor.delivery.available_permits(), 1);
    release_tx.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(5), async {
        while executor.delivery.available_permits() != 2 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
}

#[test]
fn actual_worker_exit_and_abandonment_are_monotonic_observations() {
    let activity = Arc::new(WorkerActivity {
        id: 1,
        class: RetrievalWorkClass::Delivery,
        started: Instant::now(),
        state: AtomicU8::new(0),
    });
    let exit = WorkerExit(Arc::clone(&activity));
    let control = RecallWorkControlV1::bounded(Instant::now() + Duration::from_secs(1), 10);
    drop(CancelOnDrop {
        control,
        activity: Arc::clone(&activity),
        armed: true,
    });
    assert_eq!(activity.state.load(Ordering::Acquire), 1);
    drop(exit);
    assert_eq!(activity.state.load(Ordering::Acquire), 2);
    let control = RecallWorkControlV1::bounded(Instant::now() + Duration::from_secs(1), 10);
    drop(CancelOnDrop {
        control,
        activity: Arc::clone(&activity),
        armed: true,
    });
    assert_eq!(activity.state.load(Ordering::Acquire), 2);
}

#[tokio::test]
async fn abandoned_auxiliary_worker_retains_its_pool_but_not_all_delivery_slots() {
    let executor = Arc::new(RetrievalExecutor::new());
    for kind in [RetrievalBlockingKind::Ranker, RetrievalBlockingKind::Ledger] {
        let (entered_tx, entered_rx) = tokio::sync::oneshot::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let running = Arc::clone(&executor);
        let waiter = tokio::spawn(async move {
            let request = running.begin(RetrievalWorkClass::Delivery);
            running.run(&request, kind, move |_| {
                let _ = entered_tx.send(());
                release_rx.recv_timeout(Duration::from_secs(5)).map_err(|error| error.to_string())?;
                Ok(1)
            }).await
        });
        entered_rx.await.unwrap();
        waiter.abort();
        let _ = waiter.await;
        let other = executor.begin(RetrievalWorkClass::Delivery);
        assert!(executor.run(&other, kind, |_| Ok(2)).await.is_err());
        assert_eq!(executor.run(&other, RetrievalBlockingKind::Core, |_| Ok(3)).await.unwrap(), 3);
        release_tx.send(()).unwrap();
        tokio::time::timeout(Duration::from_secs(5), async {
            while executor.delivery.available_permits() != 2 {
                tokio::task::yield_now().await;
            }
        }).await.unwrap();
        let fresh = executor.begin(RetrievalWorkClass::Delivery);
        assert_eq!(executor.run(&fresh, kind, |_| Ok(4)).await.unwrap(), 4);
    }
}
