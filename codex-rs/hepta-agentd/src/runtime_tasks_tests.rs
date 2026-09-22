use std::future::pending;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::MAX_TASKS;
use super::RuntimeTasks;
use crate::AgentdError;

fn host() -> (RuntimeTasks, CancellationToken) {
    let cancellation = CancellationToken::new();
    let host =
        RuntimeTasks::new(cancellation.clone(), Duration::from_millis(20)).expect("valid task host");
    (host, cancellation)
}

async fn observe(host: &mut RuntimeTasks) -> Result<(), AgentdError> {
    timeout(Duration::from_secs(2), host.observe_next())
        .await
        .expect("task must complete")
}

type Request = (String, oneshot::Sender<String>);

async fn echo(
    mut requests: mpsc::Receiver<Request>,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    loop {
        tokio::select! {
            () = cancellation.cancelled() => return Ok(()),
            request = requests.recv() => {
                let Some((input, reply)) = request else {
                    return Err(AgentdError::Protocol("request channel closed".to_string()));
                };
                let _ = reply.send(input.to_uppercase());
            }
        }
    }
}

async fn ask(sender: &mpsc::Sender<Request>, input: &str) -> String {
    let (reply, receive) = oneshot::channel();
    sender
        .send((input.to_string(), reply))
        .await
        .expect("request");
    timeout(Duration::from_secs(2), receive)
        .await
        .expect("service remains responsive")
        .expect("service replied")
}

#[tokio::test]
async fn forty_first_service_executes_and_failure_preserves_required_services() {
    let (mut host, cancellation) = host();
    let mut clients = Vec::new();
    for index in 0..40 {
        let (send, receive) = mpsc::channel(1);
        host.spawn_required(
            &format!("required.{index}"),
            echo(receive, cancellation.clone()),
        )
        .expect("register required service");
        clients.push(send);
    }
    let (send, mut receive) = mpsc::channel::<Request>(1);
    let quarantined = Arc::new(AtomicUsize::new(0));
    let count = Arc::clone(&quarantined);
    host.spawn_optional(
        "optional.forty-one",
        async move {
            let (input, reply) = receive.recv().await.expect("real request");
            let _ = reply.send(input.chars().rev().collect());
            Err(AgentdError::Protocol("injected optional failure".to_string()))
        },
        move || {
            count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        },
    )
    .expect("register the forty-first service through the same API");
    assert_eq!(host.active_count(), 41);
    assert_eq!(ask(&send, "hepta").await, "atpeh");
    observe(&mut host).await.expect("optional failure is isolated");
    assert_eq!(quarantined.load(Ordering::SeqCst), 1);
    assert_eq!(host.active_count(), 40);
    assert!(!cancellation.is_cancelled());
    for client in &clients {
        assert_eq!(ask(client, "still-serving").await, "STILL-SERVING");
    }
    assert_eq!(host.failures().len(), 1);
    assert_eq!(host.failures()[0].name, "optional.forty-one");
    assert!(host.spawn_required("optional.forty-one", pending()).is_err());
    host.shutdown().await;
    assert_eq!(host.active_count(), 0);
    assert!(cancellation.is_cancelled());
}

#[tokio::test]
async fn optional_panic_preserves_registered_identity_and_quarantines_once() {
    let (mut host, cancellation) = host();
    host.spawn_required("core", pending()).expect("core");
    let called = Arc::new(AtomicUsize::new(0));
    let count = Arc::clone(&called);
    host.spawn_optional(
        "optional.panic",
        async { panic!("injected task panic") },
        move || {
            count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        },
    )
    .expect("optional");
    observe(&mut host).await.expect("isolated panic");
    assert_eq!(called.load(Ordering::SeqCst), 1);
    assert_eq!(host.failures()[0].name, "optional.panic");
    assert!(!cancellation.is_cancelled());
    host.shutdown().await;
}

#[tokio::test]
async fn generation_fence_cannot_be_downgraded_to_optional_availability() {
    let (mut host, cancellation) = host();
    let quarantined = Arc::new(AtomicBool::new(false));
    let called = Arc::clone(&quarantined);
    host.spawn_required("core", pending()).expect("core");
    host.spawn_optional(
        "optional.fenced",
        async { Err(AgentdError::GenerationFenced("changed epoch".to_string())) },
        move || {
            called.store(true, Ordering::SeqCst);
            Ok(())
        },
    )
    .expect("optional");
    assert!(matches!(
        host.run_until(pending()).await,
        Err(AgentdError::GenerationFenced(_))
    ));
    assert!(!quarantined.load(Ordering::SeqCst));
    assert!(cancellation.is_cancelled());
    assert_eq!(host.active_count(), 0);
}

#[tokio::test]
async fn quarantine_rejection_is_fatal_and_reaps_other_tasks() {
    let (mut host, cancellation) = host();
    host.spawn_required("core", pending()).expect("core");
    host.spawn_optional(
        "optional",
        async { Ok(()) },
        || {
            Err(AgentdError::Protocol(
                "dependent route cannot retire".to_string(),
            ))
        },
    )
    .expect("optional");
    assert!(host.run_until(pending()).await.is_err());
    assert!(cancellation.is_cancelled());
    assert_eq!(host.active_count(), 0);
}

#[tokio::test]
async fn quarantine_panic_is_fatal_and_still_drains() {
    let (mut host, cancellation) = host();
    host.spawn_required("core", pending()).expect("core");
    host.spawn_optional("optional", async { Ok(()) }, || panic!("quarantine panic"))
        .expect("optional");
    assert!(host.run_until(pending()).await.is_err());
    assert!(cancellation.is_cancelled());
    assert_eq!(host.active_count(), 0);
}

#[tokio::test]
async fn required_clean_exit_is_not_misreported_as_success() {
    let (mut host, _) = host();
    host.spawn_required("core", async { Ok(()) }).expect("core");
    assert!(host.run_until(pending()).await.is_err());
    assert_eq!(host.active_count(), 0);
}

#[tokio::test]
async fn cancelled_observation_keeps_completion_identity() {
    let (mut host, _) = host();
    let (send, receive) = oneshot::channel();
    host.spawn_optional(
        "optional.delayed",
        async move {
            receive.await.expect("release");
            Ok(())
        },
        || Ok(()),
    )
    .expect("optional");
    assert!(
        timeout(Duration::from_millis(1), host.observe_next())
            .await
            .is_err()
    );
    assert_eq!(host.active_count(), 1);
    send.send(()).expect("release task");
    observe(&mut host).await.expect("identity retained");
    assert_eq!(host.failures()[0].name, "optional.delayed");
    host.shutdown().await;
}

struct Dropped(Arc<AtomicBool>);

impl Drop for Dropped {
    fn drop(&mut self) {
        self.0.store(true, Ordering::SeqCst);
    }
}

#[tokio::test]
async fn shutdown_listener_error_does_not_detach_live_tasks() {
    let (mut host, cancellation) = host();
    let dropped = Arc::new(AtomicBool::new(false));
    let guard = Dropped(Arc::clone(&dropped));
    let (started, ready) = oneshot::channel();
    host.spawn_required("core", async move {
        let _guard = guard;
        let _ = started.send(());
        pending().await
    })
    .expect("core");
    ready.await.expect("task started");
    assert!(
        host.run_until(async {
            Err(AgentdError::Protocol("signal listener failed".to_string()))
        })
        .await
        .is_err()
    );
    assert!(dropped.load(Ordering::SeqCst));
    assert!(cancellation.is_cancelled());
    assert_eq!(host.active_count(), 0);
}

#[tokio::test]
async fn cooperative_shutdown_precedes_forced_abort() {
    let (mut host, cancellation) = host();
    let drained = Arc::new(AtomicBool::new(false));
    let observed = Arc::clone(&drained);
    let token = cancellation.clone();
    host.spawn_required("core", async move {
        token.cancelled().await;
        observed.store(true, Ordering::SeqCst);
        Ok(())
    })
    .expect("core");
    host.run_until(async { Ok(()) }).await.expect("shutdown");
    assert!(drained.load(Ordering::SeqCst));
    assert!(host.spawn_required("late", pending()).is_err());
}

#[tokio::test]
async fn admission_is_bounded_and_rejects_duplicate_or_invalid_names() {
    let (mut host, _) = host();
    for name in ["", "bad name", "bad\nname"] {
        assert!(host.spawn_required(name, pending()).is_err());
    }
    for index in 0..MAX_TASKS {
        host.spawn_required(&format!("component.{index}"), pending())
            .expect("bounded registration");
    }
    assert!(host.spawn_required("component.0", pending()).is_err());
    assert!(host.spawn_required("overflow", pending()).is_err());
    assert_eq!(host.active_count(), MAX_TASKS);
    host.shutdown().await;
}

#[test]
fn shutdown_grace_cannot_be_zero_or_unbounded() {
    assert!(RuntimeTasks::new(CancellationToken::new(), Duration::ZERO).is_err());
    assert!(RuntimeTasks::new(CancellationToken::new(), Duration::from_secs(31)).is_err());
}
