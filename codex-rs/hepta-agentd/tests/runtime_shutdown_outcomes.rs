#![allow(clippy::expect_used)]
//! Exercise the real task host's shutdown/retirement races through its public API.
//! These tests grant no selection, writer or deployment authority.

use std::future::pending;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::RuntimeTasks;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

fn host(cancellation: CancellationToken) -> RuntimeTasks {
    RuntimeTasks::new(cancellation, Duration::from_millis(50)).expect("host")
}

#[tokio::test]
async fn already_ready_shutdown_cannot_hide_unobserved_required_failure() {
    let mut tasks = host(CancellationToken::new());
    let (finished, done) = oneshot::channel();
    tasks
        .spawn_required("runtime.core", async move {
            finished.send(()).expect("completion receiver");
            Err(AgentdError::GenerationFenced("generation lost".to_string()))
        })
        .expect("spawn");
    done.await.expect("task ran");
    // run_until deliberately prioritizes this ready signal. Its cleanup must
    // nevertheless observe the queued task result, not drop it through join_next.
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
    assert_eq!(tasks.active_count(), 0);
    assert_eq!(
        tasks.failures().back().expect("diagnostic").name,
        "runtime.core"
    );
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
}

#[tokio::test]
async fn owner_failure_after_cancellation_is_not_a_successful_shutdown() {
    let cancellation = CancellationToken::new();
    let worker_stop = cancellation.clone();
    let mut tasks = host(cancellation);
    tasks
        .spawn_required("runtime.core", async move {
            worker_stop.cancelled().await;
            Err(AgentdError::GenerationFenced(
                "drain fence lost".to_string(),
            ))
        })
        .expect("spawn");
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
    assert_eq!(tasks.active_count(), 0);
}

#[tokio::test]
async fn optional_shared_fence_during_shutdown_still_stops_the_host() {
    let cancellation = CancellationToken::new();
    let worker_stop = cancellation.clone();
    let quarantines = Arc::new(AtomicUsize::new(0));
    let callback_count = Arc::clone(&quarantines);
    let mut tasks = host(cancellation);
    tasks
        .spawn_optional(
            "feature.41",
            async move {
                worker_stop.cancelled().await;
                Err(AgentdError::GenerationFenced(
                    "owner fence lost".to_string(),
                ))
            },
            move || {
                callback_count.fetch_add(1, Ordering::SeqCst);
                Ok(())
            },
        )
        .expect("spawn");
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
    assert_eq!(quarantines.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn optional_failure_during_shutdown_is_quarantined_exactly_once() {
    let cancellation = CancellationToken::new();
    let worker_stop = cancellation.clone();
    let quarantines = Arc::new(AtomicUsize::new(0));
    let callback_count = Arc::clone(&quarantines);
    let mut tasks = host(cancellation);
    tasks
        .spawn_optional(
            "feature.41",
            async move {
                worker_stop.cancelled().await;
                Err(AgentdError::Protocol(
                    "optional worker unavailable".to_string(),
                ))
            },
            move || {
                callback_count.fetch_add(1, Ordering::SeqCst);
                Ok(())
            },
        )
        .expect("spawn");
    tasks
        .run_until(async { Ok(()) })
        .await
        .expect("isolated stop");
    tasks.shutdown().await;
    assert_eq!(quarantines.load(Ordering::SeqCst), 1);
    assert_eq!(tasks.failures().len(), 1);
}

#[tokio::test]
async fn quarantine_rejection_during_shutdown_is_latched() {
    let cancellation = CancellationToken::new();
    let worker_stop = cancellation.clone();
    let mut tasks = host(cancellation);
    tasks
        .spawn_optional(
            "feature.41",
            async move {
                worker_stop.cancelled().await;
                Err(AgentdError::Protocol("worker unavailable".to_string()))
            },
            || Err(AgentdError::Protocol("route fencing failed".to_string())),
        )
        .expect("spawn");
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
}

#[tokio::test]
async fn required_panic_during_cleanup_is_not_discarded() {
    let cancellation = CancellationToken::new();
    let worker_stop = cancellation.clone();
    let mut tasks = host(cancellation);
    tasks
        .spawn_required("runtime.core", async move {
            worker_stop.cancelled().await;
            panic!("injected owner cleanup panic");
        })
        .expect("spawn");
    assert!(tasks.run_until(async { Ok(()) }).await.is_err());
    assert_eq!(tasks.active_count(), 0);
}

#[tokio::test]
async fn unfinished_retirement_callback_is_checked_during_final_cleanup() {
    for panic_on_retire in [false, true] {
        let mut tasks = host(CancellationToken::new());
        let (release, released) = oneshot::channel();
        let callbacks = Arc::new(AtomicUsize::new(0));
        let retirement_count = Arc::clone(&callbacks);
        tasks
            .spawn_optional_service(
                "feature.41",
                |stop| async move {
                    stop.cancelled().await;
                    released.await.expect("release drain");
                    Ok(())
                },
                || Ok(()),
                move || {
                    retirement_count.fetch_add(1, Ordering::SeqCst);
                    assert!(!panic_on_retire, "injected retirement panic");
                    Err(AgentdError::Protocol("unreconciled effects".to_string()))
                },
            )
            .expect("spawn");
        assert!(tasks.retire_optional("feature.41").await.is_err());
        assert_eq!(callbacks.load(Ordering::SeqCst), 0);
        release.send(()).expect("release service");
        assert!(tasks.run_until(async { Ok(()) }).await.is_err());
        assert_eq!(callbacks.load(Ordering::SeqCst), 1);
        assert!(tasks.retire_optional("feature.41").await.is_err());
        tasks.shutdown().await;
        assert_eq!(callbacks.load(Ordering::SeqCst), 1);
    }
}

#[tokio::test]
async fn normal_host_stop_is_not_permanent_module_retirement() {
    let mut tasks = host(CancellationToken::new());
    let callbacks = Arc::new(AtomicUsize::new(0));
    let retirement_count = Arc::clone(&callbacks);
    tasks
        .spawn_optional_service(
            "feature.41",
            |stop| async move {
                stop.cancelled().await;
                Ok(())
            },
            || Ok(()),
            move || {
                retirement_count.fetch_add(1, Ordering::SeqCst);
                Ok(())
            },
        )
        .expect("spawn");
    tasks.run_until(async { Ok(()) }).await.expect("clean stop");
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    assert!(tasks.retire_optional("feature.41").await.is_err());
}

#[tokio::test]
async fn forced_abort_never_publishes_retirement_acknowledgement() {
    let mut tasks = host(CancellationToken::new());
    let callbacks = Arc::new(AtomicUsize::new(0));
    let retirement_count = Arc::clone(&callbacks);
    tasks
        .spawn_optional_service(
            "feature.41",
            |_| pending(),
            || Ok(()),
            move || {
                retirement_count.fetch_add(1, Ordering::SeqCst);
                Ok(())
            },
        )
        .expect("spawn");
    assert!(tasks.retire_optional("feature.41").await.is_err());
    assert!(
        tasks.run_until(async { Ok(()) }).await.is_err(),
        "bounded cleanup must retain the failed forced-abort outcome"
    );
    assert_eq!(tasks.active_count(), 0);
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    assert!(tasks.retire_optional("feature.41").await.is_err());
}
