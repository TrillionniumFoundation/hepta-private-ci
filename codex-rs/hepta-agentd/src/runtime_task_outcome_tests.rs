//! Failure outcomes survive owner-driven observation and subsequent cleanup.
//! These execute real Tokio tasks through the public host API. They do not
//! establish durable recovery, production selection or longitudinal efficacy.

use std::future::pending;
use std::time::Duration;

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
    tasks
        .spawn_required("core", pending())
        .expect("spawn core");
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
    tasks
        .spawn_required("core", pending())
        .expect("spawn core");
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
    tasks
        .spawn_required("core", pending())
        .expect("spawn core");
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
