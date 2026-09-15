use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use tokio::sync::oneshot;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::CompletedRuntimeTask;
use super::cleanup_runtime_tasks;
use super::supervise_optional_task;
use crate::AgentdError;

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
    assert!(!supervisor.is_finished());
    assert!(!cancellation.is_cancelled());
    cancellation.cancel();
    timeout(Duration::from_secs(2), &mut supervisor)
        .await
        .expect("bounded shutdown")
        .expect("supervisor should join")
        .expect("owner degradation succeeded");
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
    timeout(Duration::from_secs(2), &mut supervisor)
        .await
        .expect("bounded shutdown")
        .expect("supervisor should join")
        .expect("normal shutdown");
    assert!(!degraded.load(Ordering::SeqCst));
}

#[tokio::test]
async fn optional_panic_publishes_degradation_without_cancelling_the_host() {
    let cancellation = CancellationToken::new();
    let (degraded, observed) = oneshot::channel();
    let task = std::future::poll_fn(|_| -> std::task::Poll<()> {
        panic!("intentional optional task failure")
    });
    let mut supervisor = tokio::spawn(supervise_optional_task(
        cancellation.clone(),
        task,
        move || {
            let _ = degraded.send(());
            Ok(())
        },
    ));
    timeout(Duration::from_secs(1), observed)
        .await
        .expect("panic must be observed")
        .expect("owner hook must run");
    assert!(!supervisor.is_finished());
    assert!(!cancellation.is_cancelled());
    cancellation.cancel();
    timeout(Duration::from_secs(2), &mut supervisor)
        .await
        .expect("bounded shutdown")
        .expect("panic must not escape the supervisor")
        .expect("owner degradation succeeded");
}

#[tokio::test]
async fn owner_degradation_failure_is_returned_to_the_host() {
    let result = timeout(
        Duration::from_secs(1),
        supervise_optional_task(CancellationToken::new(), async {}, || {
            Err(AgentdError::Protocol("owner unavailable".to_string()))
        }),
    )
    .await
    .expect("failed owner boundary must not wait forever");
    assert!(matches!(result, Err(AgentdError::Protocol(message)) if message == "owner unavailable"));
}

struct DropSignal(Option<oneshot::Sender<()>>);

impl Drop for DropSignal {
    fn drop(&mut self) {
        if let Some(sender) = self.0.take() {
            let _ = sender.send(());
        }
    }
}

#[tokio::test]
async fn aborting_the_supervisor_does_not_detach_its_child() {
    let cancellation = CancellationToken::new();
    let (started, ready) = oneshot::channel();
    let (dropped, observed) = oneshot::channel();
    let supervisor = tokio::spawn(supervise_optional_task(
        cancellation,
        async move {
            let _guard = DropSignal(Some(dropped));
            let _ = started.send(());
            std::future::pending::<()>().await;
        },
        || Ok(()),
    ));
    timeout(Duration::from_secs(1), ready)
        .await
        .expect("task starts")
        .expect("start notification");
    supervisor.abort();
    assert!(supervisor.await.expect_err("parent aborted").is_cancelled());
    timeout(Duration::from_secs(1), observed)
        .await
        .expect("child must be aborted with its parent")
        .expect("child resources must be dropped");
}

#[tokio::test]
async fn cooperative_owner_drain_completes_before_supervisor_returns() {
    let cancellation = CancellationToken::new();
    let child = cancellation.clone();
    let (started, ready) = oneshot::channel();
    let drained = Arc::new(AtomicBool::new(false));
    let observed = Arc::clone(&drained);
    let supervisor = tokio::spawn(supervise_optional_task(
        cancellation.clone(),
        async move {
            let _ = started.send(());
            child.cancelled().await;
            observed.store(true, Ordering::SeqCst);
        },
        || Err(AgentdError::Protocol("unexpected degradation".to_string())),
    ));
    ready.await.expect("task starts");
    cancellation.cancel();
    timeout(Duration::from_secs(2), supervisor)
        .await
        .expect("bounded drain")
        .expect("join")
        .expect("normal cancellation must not degrade");
    assert!(drained.load(Ordering::SeqCst));
}

#[tokio::test]
async fn cancelled_admission_never_starts_new_optional_work() {
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let started = Arc::new(AtomicBool::new(false));
    let observed = Arc::clone(&started);
    supervise_optional_task(
        cancellation,
        async move { observed.store(true, Ordering::SeqCst) },
        || Err(AgentdError::Protocol("unexpected degradation".to_string())),
    )
    .await
    .expect("cancelled admission");
    assert!(!started.load(Ordering::SeqCst));
}

#[tokio::test]
async fn cleanup_does_not_repoll_a_consumed_optional_boundary_failure() {
    let mut optional = tokio::spawn(async {});
    (&mut optional).await.expect("selected optional boundary");
    let mut control = tokio::spawn(std::future::pending::<()>());
    let mut app = tokio::spawn(std::future::pending::<()>());
    let mut monitor = tokio::spawn(std::future::pending::<()>());
    cleanup_runtime_tasks(
        Some(CompletedRuntimeTask::OptionalBoundary),
        &mut control,
        &mut app,
        &mut monitor,
        &mut optional,
    )
    .await;
    assert!(control.is_finished() && app.is_finished() && monitor.is_finished());
}
