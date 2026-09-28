use super::*;
use std::time::Duration;

#[tokio::test(flavor = "current_thread")]
async fn blocking_owner_work_does_not_block_async_executor() {
    let budget = Arc::new(BlockingBudget::new(1).unwrap());
    let other = budget.clone();
    let (entered_tx, entered_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let job = tokio::spawn(async move { other.run(move || {
        entered_tx.send(()).unwrap(); release_rx.recv_timeout(Duration::from_secs(5)).unwrap(); 17
    }).await });
    tokio::time::timeout(Duration::from_secs(2), entered_rx).await.unwrap().unwrap();
    assert!(matches!(budget.run(|| 18).await, Err(BaoWorkerError::NotAdmitted)));
    tokio::time::timeout(Duration::from_millis(500), tokio::task::yield_now()).await.unwrap();
    release_tx.send(()).unwrap();
    assert_eq!(job.await.unwrap().unwrap(), 17);
    budget.drain().await;
}

#[tokio::test(flavor = "current_thread")]
async fn cancelling_waiter_does_not_release_started_job_or_fabricate_drain() {
    let budget = Arc::new(BlockingBudget::new(1).unwrap());
    let other = budget.clone();
    let (entered_tx, entered_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let job = tokio::spawn(async move { other.run(move || {
        entered_tx.send(()).unwrap(); release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    }).await });
    entered_rx.await.unwrap();
    job.abort();
    let _ = job.await;
    assert_eq!(budget.slots.available_permits(), 0);
    assert!(tokio::time::timeout(Duration::from_millis(20), budget.drain()).await.is_err());
    release_tx.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(2), budget.drain()).await.unwrap();
    assert!(matches!(budget.run(|| ()).await, Err(BaoWorkerError::NotAdmitted)));
}
