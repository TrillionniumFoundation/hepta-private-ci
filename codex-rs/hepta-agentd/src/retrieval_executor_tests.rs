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
            .run(&request, move |control| {
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
    assert!(executor.run(&request, |_| Ok(())).await.is_err());
    // The delivery lane is independent of a blocked shadow worker.
    let delivery = executor.begin(RetrievalWorkClass::Delivery);
    assert_eq!(executor.run(&delivery, |_| Ok(17)).await.unwrap(), 17);
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
        .run(&request, |control| {
            loop {
                match control.checkpoint() {
                    Ok(()) => std::thread::sleep(Duration::from_millis(1)),
                    Err(error) => return Err::<(), String>(error.to_string()),
                }
            }
        })
        .await;
    assert!(result.is_err());
    assert!(executor.run(&request, |_| Ok(())).await.is_err());
}

#[tokio::test]
async fn async_stage_and_later_worker_share_one_absolute_deadline() {
    let executor = RetrievalExecutor::new();
    let request = executor.begin_with_duration(
        RetrievalWorkClass::Delivery,
        Duration::from_millis(25),
    );
    executor
        .wait(&request, tokio::time::sleep(Duration::from_millis(15)))
        .await
        .unwrap();
    let result = executor
        .run_ranker(&request, |control| loop {
            match control.checkpoint() {
                Ok(()) => std::thread::sleep(Duration::from_millis(1)),
                Err(error) => return Err::<(), String>(error.to_string()),
            }
        })
        .await;
    assert!(result.is_err());
    assert!(request.checkpoint().is_err());
}

#[tokio::test]
async fn cancelled_ranker_wait_keeps_the_actual_ranker_worker_charged() {
    let executor = Arc::new(RetrievalExecutor::new());
    let request = executor.begin_with_duration(
        RetrievalWorkClass::Delivery,
        Duration::from_secs(1),
    );
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let running = Arc::clone(&executor);
    let task = tokio::spawn(async move {
        running
            .run_ranker(&request, move |control| {
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
    assert_eq!(executor.ranker.available_permits(), 0);
    release_tx.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if executor.ranker.available_permits() == 1 {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
}
