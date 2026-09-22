//! Host-local failure-latch regressions. These do not certify production writers.
use std::future::pending;
use std::time::Duration;

use tokio_util::sync::CancellationToken;

use super::RuntimeTasks;
use crate::AgentdError;

fn host() -> (RuntimeTasks, CancellationToken) {
    let cancellation = CancellationToken::new();
    let tasks =
        RuntimeTasks::new(cancellation.clone(), Duration::from_millis(20)).expect("bounded host");
    (tasks, cancellation)
}

#[tokio::test]
async fn observed_required_failure_latches_stop_even_when_caller_handles_error() {
    let (mut tasks, cancellation) = host();
    tasks
        .spawn_required("required", async {
            Err(AgentdError::Protocol("required service lost".to_string()))
        })
        .expect("required service");
    assert!(tasks.observe_next().await.is_err());
    assert!(cancellation.is_cancelled());
    assert!(tasks.spawn_required("replacement", pending()).is_err());
    tasks.shutdown().await;
}

#[tokio::test]
async fn retirement_writer_fence_cancels_siblings_and_blocks_fresh_names() {
    let (mut tasks, cancellation) = host();
    let sibling = cancellation.child_token();
    tasks
        .spawn_optional_service(
            "writer",
            |stop| async move {
                stop.cancelled().await;
                Err(AgentdError::GenerationFenced("writer changed".to_string()))
            },
            || panic!("a shared fence cannot become optional quarantine"),
            || panic!("a shared fence cannot acknowledge retirement"),
        )
        .expect("service");
    assert!(matches!(
        tasks.retire_optional("writer").await,
        Err(AgentdError::GenerationFenced(_))
    ));
    assert!(cancellation.is_cancelled());
    assert!(sibling.is_cancelled());
    assert!(tasks
        .spawn_required("unrelated-new-service", pending())
        .is_err());
    tasks.shutdown().await;
}

#[tokio::test]
async fn rejected_or_panicking_retirement_callback_latches_host_failure() {
    for panic in [false, true] {
        let (mut tasks, cancellation) = host();
        tasks
            .spawn_optional_service(
                "retiring",
                |stop| async move {
                    stop.cancelled().await;
                    Ok(())
                },
                || Ok(()),
                move || {
                    assert!(!panic, "owner callback panic");
                    Err(AgentdError::Protocol("unresolved owner effect".to_string()))
                },
            )
            .expect("service");
        assert!(tasks.retire_optional("retiring").await.is_err());
        assert!(cancellation.is_cancelled());
        assert!(tasks
            .spawn_required("unrelated-new-service", pending())
            .is_err());
        assert!(tasks.retire_optional("retiring").await.is_err());
        tasks.shutdown().await;
    }
}

#[tokio::test]
async fn successful_optional_quarantine_does_not_latch_host_failure() {
    let (mut tasks, cancellation) = host();
    tasks.spawn_required("core", pending()).expect("core");
    tasks
        .spawn_optional(
            "optional",
            async { Err(AgentdError::Protocol("optional lost".to_string())) },
            || Ok(()),
        )
        .expect("optional");
    tasks.observe_next().await.expect("isolated optional failure");
    assert!(!cancellation.is_cancelled());
    assert_eq!(tasks.failures().len(), 1);
    tasks
        .spawn_required("new-service", pending())
        .expect("host remains usable");
    tasks.shutdown().await;
}

#[tokio::test]
async fn retirement_timeout_does_not_masquerade_as_a_shared_fence() {
    let (mut tasks, cancellation) = host();
    tasks
        .spawn_optional_service("slow", |_| pending(), || Ok(()), || Ok(()))
        .expect("slow service");
    assert!(tasks.retire_optional("slow").await.is_err());
    assert!(!cancellation.is_cancelled());
    assert!(tasks.spawn_required("slow", pending()).is_err());
    tasks
        .spawn_required("core", pending())
        .expect("host still admitted");
    tasks.shutdown().await;
}
