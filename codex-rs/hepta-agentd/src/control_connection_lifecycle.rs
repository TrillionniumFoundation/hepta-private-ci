//! Bounded transport drain. This never retries or declares a runtime effect absent.
use std::time::Duration;

use tokio::task::JoinError;
use tokio::task::JoinSet;
use tokio::time::timeout;

use crate::AgentdError;

type ConnectionResult = Result<Result<(), AgentdError>, JoinError>;

pub(super) fn observe(result: ConnectionResult) -> Result<(), AgentdError> {
    match result {
        Ok(Ok(())) => Ok(()),
        Ok(Err(_)) => {
            // Client protocol/transport errors are not daemon failures. Do not
            // log arbitrary client bytes or sensitive request payloads.
            eprintln!("agentd control connection ended with a protocol or transport error");
            Ok(())
        }
        Err(error) => {
            let reason = if error.is_panic() {
                "panicked"
            } else {
                "was unexpectedly cancelled"
            };
            Err(AgentdError::Protocol(format!(
                "agentd control connection task {reason}; reconcile original operation identities"
            )))
        }
    }
}

pub(super) async fn drain(
    connections: &mut JoinSet<Result<(), AgentdError>>,
    budget: Duration,
) -> Result<(), AgentdError> {
    let mut task_failure = None;
    let drained = timeout(budget, async {
        while let Some(result) = connections.join_next().await {
            if let Err(error) = observe(result) {
                task_failure.get_or_insert(error);
            }
        }
    })
    .await;
    if drained.is_err() {
        let unfinished = connections.len();
        // shutdown aborts and joins every remaining task, releasing its permit.
        connections.shutdown().await;
        return Err(AgentdError::Protocol(format!(
            "agentd control drain timed out with {unfinished} unfinished tasks; \
             transport tasks aborted and joined; reconcile original operation identities before retrying"
        )));
    }
    match task_failure {
        Some(error) => Err(error),
        None => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::sync::atomic::AtomicBool;
    use std::sync::atomic::Ordering;
    use tokio::sync::Semaphore;
    use tokio::sync::oneshot;

    #[tokio::test]
    async fn empty_drain_succeeds() {
        let mut tasks = JoinSet::new();
        assert!(drain(&mut tasks, Duration::from_secs(1)).await.is_ok());
        assert!(tasks.is_empty());
    }

    #[tokio::test]
    async fn drain_waits_for_accepted_task() {
        let mut tasks = JoinSet::new();
        let completed = Arc::new(AtomicBool::new(false));
        let task_completed = Arc::clone(&completed);
        let (release, wait) = oneshot::channel();
        tasks.spawn(async move {
            let _ = wait.await;
            task_completed.store(true, Ordering::SeqCst);
            Ok(())
        });
        let _ = release.send(());
        assert!(drain(&mut tasks, Duration::from_secs(1)).await.is_ok());
        assert!(completed.load(Ordering::SeqCst));
        assert!(tasks.is_empty());
    }

    #[tokio::test]
    async fn client_error_does_not_poison_owner() {
        let mut tasks = JoinSet::new();
        tasks.spawn(async { Err(AgentdError::Protocol("invalid client frame".to_string())) });
        assert!(drain(&mut tasks, Duration::from_secs(1)).await.is_ok());
        assert!(tasks.is_empty());
    }

    #[tokio::test]
    async fn timeout_is_failure_and_releases_permits() -> Result<(), AgentdError> {
        let permits = Arc::new(Semaphore::new(1));
        let permit = Arc::clone(&permits)
            .acquire_owned()
            .await
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        let mut tasks = JoinSet::new();
        tasks.spawn(async move {
            let _permit = permit;
            std::future::pending::<Result<(), AgentdError>>().await
        });
        assert!(drain(&mut tasks, Duration::from_millis(5)).await.is_err());
        assert!(tasks.is_empty());
        assert_eq!(permits.available_permits(), 1);
        Ok(())
    }

    #[tokio::test]
    #[allow(clippy::panic)] // Deliberate task-failure injection.
    async fn task_panic_is_not_successful_drain() {
        let mut tasks = JoinSet::new();
        tasks.spawn(async { panic!("injected connection panic") });
        assert!(drain(&mut tasks, Duration::from_secs(1)).await.is_err());
        assert!(tasks.is_empty());
    }

    #[tokio::test]
    async fn premature_task_abort_is_not_successful_drain() {
        let mut tasks = JoinSet::new();
        tasks.spawn(std::future::pending::<Result<(), AgentdError>>());
        tasks.abort_all();
        assert!(drain(&mut tasks, Duration::from_secs(1)).await.is_err());
        assert!(tasks.is_empty());
    }
}
