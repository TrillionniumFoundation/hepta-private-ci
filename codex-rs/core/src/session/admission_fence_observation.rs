//! Bounded observation for external callers between visible turn completion
//! and retirement of its owner-controlled admission fences.

use super::session::Session;
use std::future::Future;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use tokio::time::Instant;

/// Why observing the current fences could not finish safely.
#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum AdmissionFenceObservationError {
    #[error("thread shutdown has started")]
    Shutdown,
    #[error("admission fence observation deadline expired")]
    Deadline,
    #[error("admission fence registry or active turn is busy")]
    Busy,
    #[error("a different turn was admitted during fence observation")]
    Stale,
}

pub(crate) async fn observe(
    session: &Session,
    terminated: impl Future<Output = ()>,
    deadline: Instant,
) -> Result<(), AdmissionFenceObservationError> {
    use AdmissionFenceObservationError as Error;

    // This observes owner-controlled completions only. Dropping or timing out
    // this future cannot retire a fence, cancel its owner, or submit input.
    let observation = async {
        let (epoch, completions) = {
            let _active_turn = session.active_turn.lock().await;
            if Instant::now() >= deadline {
                return Err(Error::Deadline);
            }
            if session.shutdown_started() {
                return Err(Error::Shutdown);
            }
            // A blocking std mutex acquisition would defeat the outer budget.
            // Contention and poison fail closed without changing either owner.
            let starts = session
                .pending_start_transition_completions
                .try_lock()
                .map_err(|_| Error::Busy)?;
            let terminalizers = session
                .pending_task_terminalization_completions
                .try_lock()
                .map_err(|_| Error::Busy)?;
            let completions: Vec<_> = starts
                .iter()
                .map(|(_, completion, _)| Arc::clone(completion))
                .chain(
                    terminalizers
                        .iter()
                        .map(|(_, completion, ..)| Arc::clone(completion)),
                )
                .collect();
            (session.turn_epoch.load(Ordering::Acquire), completions)
        };
        if completions.is_empty() {
            // A running turn without a fence must retain ordinary steering
            // semantics. Observation itself is never proof of idleness.
            return if Instant::now() >= deadline {
                Err(Error::Deadline)
            } else {
                Ok(())
            };
        }
        for completion in completions {
            completion.wait().await;
        }

        let active_turn = session.active_turn.lock().await;
        if Instant::now() >= deadline {
            return Err(Error::Deadline);
        }
        if session.shutdown_started() {
            return Err(Error::Shutdown);
        }
        if session.turn_epoch.load(Ordering::Acquire) != epoch {
            return Err(Error::Stale);
        }
        let starts = session
            .pending_start_transition_completions
            .try_lock()
            .map_err(|_| Error::Busy)?;
        let terminalizers = session
            .pending_task_terminalization_completions
            .try_lock()
            .map_err(|_| Error::Busy)?;
        if active_turn.is_some() || !starts.is_empty() || !terminalizers.is_empty() {
            return Err(Error::Busy);
        }
        if Instant::now() >= deadline {
            return Err(Error::Deadline);
        }
        Ok(())
    };
    tokio::select! {
        biased;
        () = terminated => Err(Error::Shutdown),
        result = tokio::time::timeout_at(deadline, observation) => {
            result.map_err(|_| Error::Deadline)?
        }
    }
}

#[cfg(test)]
#[path = "admission_fence_observation_tests.rs"]
mod tests;
