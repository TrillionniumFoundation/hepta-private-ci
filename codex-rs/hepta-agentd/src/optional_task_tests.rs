use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::supervise_optional_task;

#[tokio::test]
async fn optional_task_exit_degrades_without_completing_the_supervisor() {
    let cancellation = CancellationToken::new();
    let degraded = Arc::new(AtomicBool::new(false));
    let observed = Arc::clone(&degraded);
    let mut supervisor = tokio::spawn(supervise_optional_task(
        cancellation.clone(),
        async {},
        move || {
            observed.store(true, Ordering::SeqCst);
            Ok(())
        },
    ));

    timeout(Duration::from_secs(1), async {
        while !degraded.load(Ordering::SeqCst) {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("optional failure should publish degradation");
    assert!(
        !supervisor.is_finished(),
        "optional exit must not become a process-level completion signal"
    );

    cancellation.cancel();
    timeout(Duration::from_secs(1), &mut supervisor)
        .await
        .expect("supervisor should finish after cancellation")
        .expect("supervisor task should join")
        .expect("degradation hook should succeed");
}

#[tokio::test]
async fn normal_cancellation_does_not_publish_optional_degradation() {
    let cancellation = CancellationToken::new();
    let degraded = Arc::new(AtomicBool::new(false));
    let observed = Arc::clone(&degraded);
    let mut supervisor = tokio::spawn(supervise_optional_task(
        cancellation.clone(),
        std::future::pending::<()>(),
        move || {
            observed.store(true, Ordering::SeqCst);
            Ok(())
        },
    ));

    cancellation.cancel();
    timeout(Duration::from_secs(1), &mut supervisor)
        .await
        .expect("supervisor should finish after cancellation")
        .expect("supervisor task should join")
        .expect("shutdown should remain successful");
    assert!(!degraded.load(Ordering::SeqCst));
}
