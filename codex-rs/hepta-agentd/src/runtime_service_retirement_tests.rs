//! These are running service/owner-callback tests, not production Codex,
//! independent selection, durable writer handoff or cross-process qualification.
use std::future::pending;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::RuntimeTasks;
use crate::AgentdError;

type Request = (u64, oneshot::Sender<u64>);

fn host(grace: Duration) -> (RuntimeTasks, CancellationToken) {
    let cancellation = CancellationToken::new();
    let host = RuntimeTasks::new(cancellation.clone(), grace).expect("bounded host");
    (host, cancellation)
}

async fn service(
    mut requests: mpsc::Receiver<Request>,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    loop {
        tokio::select! {
            biased;
            () = cancellation.cancelled() => {
                // Stop admission, then finish the already accepted read-only work.
                requests.close();
                while let Some((input, reply)) = requests.recv().await {
                    let _ = reply.send(input.saturating_add(1));
                }
                return Ok(());
            }
            request = requests.recv() => {
                let Some((input, reply)) = request else {
                    return Err(AgentdError::Protocol("service input closed".to_string()));
                };
                let _ = reply.send(input.saturating_add(1));
            }
        }
    }
}

async fn ask(client: &mpsc::Sender<Request>, input: u64) -> u64 {
    let (reply, receive) = oneshot::channel();
    timeout(Duration::from_secs(2), async {
        client.send((input, reply)).await.expect("request admitted");
        receive.await.expect("actual service result")
    })
    .await
    .expect("bounded service response")
}

#[tokio::test]
async fn forty_first_running_service_retires_without_stopping_other_services() {
    let (mut host, cancellation) = host(Duration::from_secs(2));
    let mut clients = Vec::new();
    for index in 0..40 {
        let (send, receive) = mpsc::channel(2);
        host.spawn_required(
            &format!("required.{index}"),
            service(receive, cancellation.clone()),
        )
        .expect("required service");
        clients.push(send);
    }
    let (send, receive) = mpsc::channel(2);
    let retired = Arc::new(AtomicUsize::new(0));
    let published = Arc::clone(&retired);
    host.spawn_optional_service(
        "optional.forty-one",
        move |stop| service(receive, stop),
        || panic!("graceful retirement must not be mislabeled quarantine"),
        move || {
            published.fetch_add(1, Ordering::SeqCst);
            Ok(())
        },
    )
    .expect("public service registration");
    assert_eq!(host.active_count(), 41);
    assert_eq!(ask(&send, 41).await, 42);
    host.retire_optional("optional.forty-one")
        .await
        .expect("owner acknowledged retirement");
    host.retire_optional("optional.forty-one")
        .await
        .expect("idempotent acknowledgment");
    assert_eq!(retired.load(Ordering::SeqCst), 1);
    assert!(send.is_closed());
    assert_eq!(host.active_count(), 40);
    assert!(host.failures().is_empty());
    assert!(!cancellation.is_cancelled());
    for client in &clients {
        assert_eq!(ask(client, 99).await, 100);
    }
    assert!(
        host.spawn_required("optional.forty-one", pending())
            .is_err()
    );
    host.shutdown().await;
}

#[tokio::test]
async fn rejected_service_factory_is_never_invoked() {
    let (mut host, _) = host(Duration::from_millis(20));
    host.spawn_required("occupied", pending())
        .expect("required");
    let calls = Arc::new(AtomicUsize::new(0));
    for name in ["occupied", "", "invalid name"] {
        let called = Arc::clone(&calls);
        assert!(
            host.spawn_optional_service(
                name,
                move |_| {
                    called.fetch_add(1, Ordering::SeqCst);
                    async { Ok(()) }
                },
                || Ok(()),
                || Ok(()),
            )
            .is_err()
        );
    }
    tokio::task::yield_now().await;
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    host.shutdown().await;
}

#[tokio::test]
async fn retirement_cannot_stop_required_or_legacy_uncontracted_tasks() {
    let (mut host, cancellation) = host(Duration::from_millis(20));
    host.spawn_required("core", pending()).expect("required");
    host.spawn_optional("legacy", pending(), || Ok(()))
        .expect("legacy optional");
    for name in ["core", "legacy", "missing"] {
        assert!(host.retire_optional(name).await.is_err());
    }
    assert_eq!(host.active_count(), 2);
    assert!(!cancellation.is_cancelled());
    host.shutdown().await;
}

#[tokio::test]
async fn retirement_timeout_never_acknowledges_unfinished_drain() {
    let (mut host, cancellation) = host(Duration::from_millis(10));
    host.spawn_required("core", pending()).expect("required");
    let (release, released) = oneshot::channel();
    let retired = Arc::new(AtomicUsize::new(0));
    let publish = Arc::clone(&retired);
    host.spawn_optional_service(
        "slow",
        move |stop| async move {
            stop.cancelled().await;
            released.await.expect("owner drain release");
            Ok(())
        },
        || Ok(()),
        move || {
            publish.fetch_add(1, Ordering::SeqCst);
            Ok(())
        },
    )
    .expect("optional");
    assert!(host.retire_optional("slow").await.is_err());
    assert_eq!(retired.load(Ordering::SeqCst), 0);
    assert_eq!(host.active_count(), 2);
    assert!(!cancellation.is_cancelled());
    assert!(host.spawn_required("slow", pending()).is_err());
    release.send(()).expect("finish drain");
    timeout(Duration::from_secs(2), host.observe_next())
        .await
        .expect("bounded completion")
        .expect("late retirement completion");
    host.retire_optional("slow")
        .await
        .expect("now acknowledged");
    assert_eq!(retired.load(Ordering::SeqCst), 1);
    host.shutdown().await;
}

#[tokio::test]
async fn retirement_keeps_observing_unrelated_failures() {
    let (mut host, cancellation) = host(Duration::from_secs(2));
    host.spawn_required("core", pending()).expect("required");
    let (release, released) = oneshot::channel();
    host.spawn_optional(
        "other",
        async { Err(AgentdError::Protocol("injected failure".to_string())) },
        move || {
            let _ = release.send(());
            Ok(())
        },
    )
    .expect("other optional");
    host.spawn_optional_service(
        "target",
        move |stop| async move {
            stop.cancelled().await;
            released.await.expect("other completion was observed");
            Ok(())
        },
        || Ok(()),
        || Ok(()),
    )
    .expect("target");
    host.retire_optional("target").await.expect("retired");
    assert_eq!(host.failures().len(), 1);
    assert_eq!(host.failures()[0].name, "other");
    assert_eq!(host.active_count(), 1);
    assert!(!cancellation.is_cancelled());
    host.shutdown().await;
}

#[tokio::test]
async fn failed_drain_is_quarantine_not_retirement() {
    let (mut host, _) = host(Duration::from_secs(2));
    let quarantined = Arc::new(AtomicUsize::new(0));
    let count = Arc::clone(&quarantined);
    host.spawn_optional_service(
        "failed",
        |stop| async move {
            stop.cancelled().await;
            Err(AgentdError::Protocol("owner drain failed".to_string()))
        },
        move || {
            count.fetch_add(1, Ordering::SeqCst);
            Ok(())
        },
        || panic!("failed drain cannot retire"),
    )
    .expect("optional");
    assert!(host.retire_optional("failed").await.is_err());
    assert_eq!(quarantined.load(Ordering::SeqCst), 1);
    assert!(host.retire_optional("failed").await.is_err());
    assert!(host.spawn_required("failed", pending()).is_err());
    host.shutdown().await;
}

#[tokio::test]
async fn owner_retirement_rejection_or_panic_never_publishes_success() {
    for panic in [false, true] {
        let (mut host, _) = host(Duration::from_secs(2));
        host.spawn_optional_service(
            "rejected",
            |stop| async move {
                stop.cancelled().await;
                Ok(())
            },
            || Ok(()),
            move || {
                assert!(!panic, "injected owner panic");
                Err(AgentdError::Protocol("unresolved owner effect".to_string()))
            },
        )
        .expect("optional");
        assert!(host.retire_optional("rejected").await.is_err());
        assert!(host.retire_optional("rejected").await.is_err());
        assert!(host.spawn_required("rejected", pending()).is_err());
        host.shutdown().await;
    }
}

#[tokio::test]
async fn a_writer_fence_during_retirement_still_propagates() {
    let (mut host, _) = host(Duration::from_secs(2));
    host.spawn_optional_service(
        "fenced",
        |stop| async move {
            stop.cancelled().await;
            Err(AgentdError::GenerationFenced("changed writer".to_string()))
        },
        || panic!("shared fence must not become optional quarantine"),
        || panic!("shared fence cannot retire"),
    )
    .expect("optional");
    assert!(matches!(
        host.retire_optional("fenced").await,
        Err(AgentdError::GenerationFenced(_))
    ));
    assert!(host.retire_optional("fenced").await.is_err());
    host.shutdown().await;
}
