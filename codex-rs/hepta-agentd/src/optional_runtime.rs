//! Lifecycle supervision for trusted cooperative optional planes.
//!
//! A task result or unwind degrades only its owner. An inability to publish
//! that degradation is a host-boundary error, not a silently detached failure.
//! This is not isolation for untrusted code, blocking work or panic=abort.

use std::future::Future;
use std::time::Duration;

use tokio::task::JoinSet;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;

pub(super) const OPTIONAL_DRAIN_TIMEOUT: Duration = Duration::from_millis(250);
pub(super) const OPTIONAL_JOIN_TIMEOUT: Duration = Duration::from_secs(1);

/// Own one optional task through completion, cancellation and unwinding.
/// The caller must observe this supervisor's result: failure of the owner hook
/// means the host cannot guarantee that callers see the unavailable boundary.
/// A JoinSet owns the child so dropping this future cannot detach live work.
pub(super) async fn supervise_optional_task<Task, Output, Degrade>(
    cancellation: CancellationToken,
    task: Task,
    degrade: Degrade,
) -> Result<(), AgentdError>
where
    Task: Future<Output = Output> + Send + 'static,
    Output: Send + 'static,
    Degrade: FnOnce() -> Result<(), AgentdError> + Send,
{
    if cancellation.is_cancelled() {
        return Ok(());
    }
    let mut tasks = JoinSet::new();
    tasks.spawn(task);
    tokio::select! {
        biased;
        _ = cancellation.cancelled() => {
            // Let cooperative owners finish their cancellation path before
            // aborting. Durable unresolved effects still require reconciliation.
            if timeout(OPTIONAL_DRAIN_TIMEOUT, tasks.join_next()).await.is_err() {
                tasks.shutdown().await;
            }
            Ok(())
        }
        _ = tasks.join_next() => {
            if cancellation.is_cancelled() {
                return Ok(());
            }
            // Includes successful early exits, returned errors and JoinError
            // (panic/cancellation). No raw task error crosses the owner boundary.
            degrade()?;
            cancellation.cancelled().await;
            Ok(())
        }
    }
}
