//! Failure outcomes survive owner-driven observation and subsequent cleanup.
//! These execute real Tokio tasks through the public host API. They do not
//! establish durable recovery, production selection or longitudinal efficacy.

use std::future::Future;
use std::future::pending;
use std::future::poll_fn;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::task::Poll;
use std::time::Duration;

use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use super::RuntimeTasks;
use crate::AgentdError;

fn host() -> RuntimeTasks {
    RuntimeTasks::new(CancellationToken::new(), Duration::from_millis(50)).expect("host")
}

#[tokio::test]
async fn observed_required_failure_cannot_become_cancelled_success() {
    let mut tasks = host();
    tasks
        .spawn_required("core", async {
            Err(AgentdError::GenerationFenced("lost generation".to_string()))
        })
        .expect("spawn core");
    assert!(tasks.observe_next().await.is_err());
    assert!(tasks.run_until(pending()).await.is_err());
    assert_eq!(tasks.active_count(), 0);
    // Even an already-ready successful shutdown signal cannot erase failure.
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
}

#[tokio::test]
async fn rejected_retirement_remains_failed_after_cleanup() {
    let mut tasks = host();
    tasks
        .spawn_optional_service(
            "feature.41",
            |stop| async move {
                stop.cancelled().await;
                Ok(())
            },
            || Ok(()),
            || Err(AgentdError::Protocol("unresolved owner effects".to_string())),
        )
        .expect("spawn service");
    assert!(tasks.retire_optional("feature.41").await.is_err());
    tasks.shutdown().await;
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
    assert!(tasks.retire_optional("feature.41").await.is_err());
}

#[tokio::test]
async fn rejected_quarantine_cannot_be_reclassified_as_normal_shutdown() {
    let mut tasks = host();
    tasks
        .spawn_optional(
            "feature.41",
            async { Err(AgentdError::Protocol("worker failed".to_string())) },
            || Err(AgentdError::Protocol("route fence failed".to_string())),
        )
        .expect("spawn service");
    assert!(tasks.observe_next().await.is_err());
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
}

#[tokio::test]
async fn shutdown_listener_failure_is_latched_across_reentry() {
    let mut tasks = host();
    tasks.spawn_required("core", pending()).expect("spawn core");
    assert!(
        tasks
            .run_until(async { Err(AgentdError::Protocol("listener failed".to_string())) })
            .await
            .is_err()
    );
    assert_eq!(tasks.active_count(), 0);
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
}

#[tokio::test]
async fn isolated_optional_failure_does_not_poison_healthy_host() {
    let mut tasks = host();
    tasks.spawn_required("core", pending()).expect("spawn core");
    tasks
        .spawn_optional(
            "feature.41",
            async { Err(AgentdError::Protocol("optional unavailable".to_string())) },
            || Ok(()),
        )
        .expect("spawn service");
    tasks.observe_next().await.expect("isolate optional failure");
    assert_eq!(tasks.active_count(), 1);
    assert_eq!(tasks.failures().len(), 1);
    tasks.run_until(async { Ok(()) }).await.expect("clean stop");
}

#[tokio::test]
async fn successful_optional_retirement_preserves_clean_host_outcome() {
    let mut tasks = host();
    tasks.spawn_required("core", pending()).expect("spawn core");
    tasks
        .spawn_optional_service(
            "feature.41",
            |stop| async move {
                stop.cancelled().await;
                Ok(())
            },
            || Ok(()),
            || Ok(()),
        )
        .expect("spawn service");
    tasks.retire_optional("feature.41").await.expect("retire");
    tasks.retire_optional("feature.41").await.expect("idempotent");
    assert_eq!(tasks.active_count(), 1);
    tasks.run_until(async { Ok(()) }).await.expect("clean stop");
}

#[tokio::test]
async fn timed_out_retirement_aborted_by_shutdown_remains_failed() {
    let mut tasks = host();
    let acknowledgements = Arc::new(AtomicUsize::default());
    let observed = Arc::clone(&acknowledgements);
    tasks
        .spawn_optional_service(
            "feature.41",
            |_stop| pending(),
            || Ok(()),
            move || {
                observed.fetch_add(/*val*/ 1, Ordering::SeqCst);
                Ok(())
            },
        )
        .expect("spawn service");
    assert!(tasks.retire_optional("feature.41").await.is_err());
    assert_eq!(tasks.active_count(), 1);
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
    assert_eq!(tasks.active_count(), 0);
    assert_eq!(acknowledgements.load(Ordering::SeqCst), 0);
    assert_eq!(tasks.failures().len(), 1);
    assert!(tasks.retire_optional("feature.41").await.is_err());
    // Cleanup and a new ready shutdown signal cannot turn the abort into success.
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
    assert_eq!(tasks.failures().len(), 1);
}

#[tokio::test]
async fn late_owner_acknowledgement_after_timeout_preserves_clean_shutdown() {
    let mut tasks = host();
    let acknowledgements = Arc::new(AtomicUsize::default());
    let observed = Arc::clone(&acknowledgements);
    let (complete, completed) = oneshot::channel::<()>();
    tasks
        .spawn_optional_service(
            "feature.41",
            |stop| async move {
                stop.cancelled().await;
                completed.await.map_err(|_| {
                    AgentdError::Protocol("owner completion dropped".to_string())
                })?;
                Ok(())
            },
            || Ok(()),
            move || {
                observed.fetch_add(/*val*/ 1, Ordering::SeqCst);
                Ok(())
            },
        )
        .expect("spawn service");
    assert!(tasks.retire_optional("feature.41").await.is_err());
    assert_eq!(acknowledgements.load(Ordering::SeqCst), 0);
    complete.send(()).expect("complete owner work");
    tasks
        .run_until(async { Ok(()) })
        .await
        .expect("acknowledged retirement during shutdown");
    assert_eq!(acknowledgements.load(Ordering::SeqCst), 1);
    tasks
        .retire_optional("feature.41")
        .await
        .expect("retirement acknowledgement remains idempotent");
    assert_eq!(acknowledgements.load(Ordering::SeqCst), 1);
    assert!(tasks.failures().is_empty());
}

#[tokio::test]
async fn dropped_retirement_wait_does_not_erase_an_unacknowledged_abort() {
    let mut tasks = host();
    tasks
        .spawn_optional_service("feature.41", |_stop| pending(), || Ok(()), || Ok(()))
        .expect("spawn service");
    {
        let retirement = tasks.retire_optional("feature.41");
        tokio::pin!(retirement);
        // Poll once to request retirement, then cancel only the caller's wait.
        // The owner is deliberately pending; no wall-clock sleep is needed.
        poll_fn(|context| {
            assert!(retirement.as_mut().poll(context).is_pending());
            Poll::Ready(())
        })
        .await;
    }
    tasks.shutdown().await;
    assert_eq!(tasks.active_count(), 0);
    assert_eq!(tasks.failures().len(), 1);
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
    assert!(tasks.retire_optional("feature.41").await.is_err());
}

#[tokio::test]
async fn ordinary_host_abort_does_not_invent_a_retirement_request() {
    let mut tasks = host();
    let acknowledgements = Arc::new(AtomicUsize::default());
    let observed = Arc::clone(&acknowledgements);
    tasks
        .spawn_optional_service(
            "feature.41",
            |_stop| pending(),
            || Ok(()),
            move || {
                observed.fetch_add(/*val*/ 1, Ordering::SeqCst);
                Ok(())
            },
        )
        .expect("spawn service");
    tasks.run_until(async { Ok(()) }).await.expect("host stop");
    assert_eq!(tasks.active_count(), 0);
    assert_eq!(acknowledgements.load(Ordering::SeqCst), 0);
    assert!(tasks.failures().is_empty());
    assert!(tasks.retire_optional("feature.41").await.is_err());
}
