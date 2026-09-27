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
        running.run(&request, move |control| {
            entered_tx.send(()).unwrap();
            release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            control.checkpoint().map_err(|error| error.to_string())
        }).await
    });
    tokio::task::spawn_blocking(move || entered_rx.recv_timeout(Duration::from_secs(5)))
        .await.unwrap().unwrap();
    task.abort();
    let _ = task.await;
    assert_eq!(executor.shadow.available_permits(), 0);
    let request = executor.begin(RetrievalWorkClass::Shadow);
    assert!(executor.run(&request, |_| Ok(())).await.is_err());
    // The delivery lane is independent of a blocked shadow worker.
    let delivery = executor.begin(RetrievalWorkClass::Delivery);
    assert_eq!(executor.run(&delivery, |_| Ok(17)).await.unwrap(), 17);
    release_tx.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if executor.shadow.available_permits() == 1 { break; }
            tokio::task::yield_now().await;
        }
    }).await.unwrap();
}

#[tokio::test]
async fn timeout_cannot_return_late_success_or_extend_the_request_budget() {
    let executor = RetrievalExecutor::new();
    let request = executor.begin(RetrievalWorkClass::Shadow);
    let result = executor.run(&request, |control| {
        loop {
            match control.checkpoint() {
                Ok(()) => std::thread::sleep(Duration::from_millis(1)),
                Err(error) => return Err::<(), String>(error.to_string()),
            }
        }
    }).await;
    assert!(result.is_err());
    assert!(executor.run(&request, |_| Ok(())).await.is_err());
}
