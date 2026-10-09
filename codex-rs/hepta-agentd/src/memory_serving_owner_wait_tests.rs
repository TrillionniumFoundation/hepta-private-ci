use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use tokio::sync::Mutex;
use tokio::sync::oneshot;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::OWNER_READ_LIMIT;
use super::read_owner_phase;
use crate::AgentdError;
use crate::RuntimeTasks;
use crate::SharedMemoryTrainingError;

#[tokio::test]
async fn already_cancelled_read_does_not_poll_even_a_ready_owner() {
    let stop = CancellationToken::new();
    stop.cancel();
    let polled = AtomicBool::new(false);
    let result = read_owner_phase(&stop, OWNER_READ_LIMIT, async {
        polled.store(true, Ordering::SeqCst);
        Ok(())
    })
    .await;
    assert!(matches!(
        result,
        Err(SharedMemoryTrainingError::Invalid(
            "memory owner read cancelled"
        ))
    ));
    assert!(!polled.load(Ordering::SeqCst));
}

#[tokio::test]
async fn cancellation_releases_an_earlier_owner_while_a_later_owner_is_locked() {
    let first = Arc::new(Mutex::new(()));
    let second = Arc::new(Mutex::new(()));
    let second_guard = second.lock().await;
    let stop = CancellationToken::new();
    let (entered, observed) = oneshot::channel();
    let worker_first = Arc::clone(&first);
    let worker_second = Arc::clone(&second);
    let worker_stop = stop.clone();
    let worker = tokio::spawn(async move {
        read_owner_phase(&worker_stop, OWNER_READ_LIMIT, async {
            let _first = worker_first.lock().await;
            let _ = entered.send(());
            let _second = worker_second.lock().await;
            Ok(())
        })
        .await
    });
    observed.await.expect("first owner acquired");
    assert!(first.try_lock().is_err());
    stop.cancel();
    let result = timeout(Duration::from_secs(1), worker)
        .await
        .expect("bounded cancellation")
        .expect("read task joined");
    assert!(result.is_err());
    assert!(first.try_lock().is_ok());
    drop(second_guard);
}

#[tokio::test]
async fn owner_timeout_drops_all_borrowed_guards_without_running_the_consumer() {
    let owner = Mutex::new(());
    let consumer_called = AtomicBool::new(false);
    let stop = CancellationToken::new();
    let result: Result<(), _> = read_owner_phase(&stop, Duration::from_millis(5), async {
        let _guard = owner.lock().await;
        std::future::pending::<()>().await;
        consumer_called.store(true, Ordering::SeqCst);
        Ok(())
    })
    .await;
    assert!(matches!(
        result,
        Err(SharedMemoryTrainingError::Invalid(
            "memory owner read timed out"
        ))
    ));
    assert!(owner.try_lock().is_ok());
    assert!(!consumer_called.load(Ordering::SeqCst));
}

#[tokio::test]
async fn owner_denial_is_preserved_and_cannot_become_an_empty_fresh_view() {
    let stop = CancellationToken::new();
    let result: Result<(), _> = read_owner_phase(&stop, OWNER_READ_LIMIT, async {
        Err(SharedMemoryTrainingError::Invalid("source withdrawn"))
    })
    .await;
    assert!(matches!(
        result,
        Err(SharedMemoryTrainingError::Invalid("source withdrawn"))
    ));
    let value = read_owner_phase(&stop, OWNER_READ_LIMIT, async { Ok(vec![3, 5, 8]) })
        .await
        .expect("actual owner result");
    assert_eq!(value, vec![3, 5, 8]);
}

#[tokio::test]
async fn actual_host_retirement_cancels_a_blocked_read_before_acknowledgement() {
    let shutdown = CancellationToken::new();
    let mut tasks = RuntimeTasks::new(shutdown.clone(), Duration::from_secs(1)).expect("task host");
    let lock = Arc::new(Mutex::new(()));
    let retirement_lock = Arc::clone(&lock);
    let retired = Arc::new(AtomicBool::new(false));
    let retired_callback = Arc::clone(&retired);
    let quarantined = Arc::new(AtomicBool::new(false));
    let quarantined_callback = Arc::clone(&quarantined);
    let (entered, observed) = oneshot::channel();
    tasks
        .spawn_optional_service(
            "memory.owner.read",
            move |stop| async move {
                let result: Result<(), _> = read_owner_phase(&stop, OWNER_READ_LIMIT, async {
                    let _guard = lock.lock().await;
                    let _ = entered.send(());
                    std::future::pending().await
                })
                .await;
                if stop.is_cancelled() {
                    Ok(())
                } else {
                    result.map_err(|error| AgentdError::Protocol(error.to_string()))
                }
            },
            move || {
                quarantined_callback.store(true, Ordering::SeqCst);
                Ok(())
            },
            move || {
                assert!(
                    retirement_lock.try_lock().is_ok(),
                    "owner guard must be dropped before retirement acknowledgement"
                );
                retired_callback.store(true, Ordering::SeqCst);
                Ok(())
            },
        )
        .expect("admitted read-only service");
    observed.await.expect("read in flight");
    tasks
        .retire_optional("memory.owner.read")
        .await
        .expect("read is not an unknown effect");
    assert!(retired.load(Ordering::SeqCst));
    assert!(!quarantined.load(Ordering::SeqCst));
    assert!(!shutdown.is_cancelled());
}
