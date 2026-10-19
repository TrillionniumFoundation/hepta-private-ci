//! Read-only retirement observation for isolated, single-writer test fixtures.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::TryLockError;
use std::sync::atomic::Ordering;

use tokio::time::Instant;
use tokio::time::timeout_at;

use crate::CodexThread;
use crate::session::session::Session;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum TurnRetirementObservationError {
    #[error("thread shutdown started while observing turn retirement")]
    Shutdown,
    /// Active work/fences remain, or contention prevented a registry snapshot.
    #[error(
        "turn retirement observation is busy: active work, a new admission fence, or an unavailable registry snapshot"
    )]
    Busy,
    #[error("a newer turn was attached while observing turn retirement")]
    Stale,
    #[error("turn retirement observation deadline expired")]
    Deadline,
}

/// Observe the exact fences present after a fixture has consumed TurnComplete.
///
/// Use only outside the submission dispatcher in isolated, single-writer tests.
/// This neither reserves admission nor establishes successful persistence: a
/// failed terminal flush can still retire its fence. A later operation must use
/// ordinary admission and retain its own error assertions. Cancelling this
/// observer drops only its waits, never the task or terminalization owner.
/// The caller supplies its existing operation deadline; no phase renews it.
/// Async lock/handle waits are bounded and late success is rejected. Registry
/// reads use one-shot try_lock: even legitimate concurrent retirement may yield
/// Busy. That conservative outcome is never retried or treated as success.
pub async fn wait_for_turn_retirement(
    thread: &CodexThread,
    deadline: Instant,
) -> Result<(), TurnRetirementObservationError> {
    wait_for_session_turn_retirement(&thread.session, deadline).await
}

pub(crate) async fn wait_for_session_turn_retirement(
    session: &Session,
    deadline: Instant,
) -> Result<(), TurnRetirementObservationError> {
    timeout_at(deadline, async {
        let (epoch, completions) = {
            let active = session.active_turn.lock().await;
            if Instant::now() >= deadline {
                return Err(TurnRetirementObservationError::Deadline);
            }
            if session.shutdown_started() {
                return Err(TurnRetirementObservationError::Shutdown);
            }
            // Only a terminalizing slot may still exist after visible completion.
            // Never wait for a running/replacement task or a new reservation.
            if active.as_ref().is_some_and(|turn| {
                turn.task.is_some()
                    || turn.start_reservation.is_some()
                    || turn.start_transition.is_some()
                    || turn.task_terminalization.is_none()
            }) {
                return Err(TurnRetirementObservationError::Busy);
            }
            let epoch = session.turn_epoch.load(Ordering::Acquire);
            let mut completions: Vec<_> = try_registry_lock(
                &session.pending_start_transition_completions,
                "start transition",
            )?
            .iter()
            .map(|(_, completion, _)| Arc::clone(completion))
            .collect();
            completions.extend(
                try_registry_lock(
                    &session.pending_task_terminalization_completions,
                    "task terminalization",
                )?
                .iter()
                .map(|(_, completion, _, _, _, _)| Arc::clone(completion)),
            );
            (epoch, completions)
        };

        // All locks are dropped. These exact handles cannot become a wait on a
        // newer generation, and observation cannot cancel or drive their owner.
        for completion in completions {
            completion.wait().await;
        }

        let active = session.active_turn.lock().await;
        if Instant::now() >= deadline {
            return Err(TurnRetirementObservationError::Deadline);
        }
        if session.shutdown_started() {
            return Err(TurnRetirementObservationError::Shutdown);
        }
        if session.turn_epoch.load(Ordering::Acquire) != epoch {
            return Err(TurnRetirementObservationError::Stale);
        }
        let starts = try_registry_lock(
            &session.pending_start_transition_completions,
            "start transition",
        )?;
        let terminalizers = try_registry_lock(
            &session.pending_task_terminalization_completions,
            "task terminalization",
        )?;
        if active.is_some() || !starts.is_empty() || !terminalizers.is_empty() {
            return Err(TurnRetirementObservationError::Busy);
        }
        if Instant::now() >= deadline {
            return Err(TurnRetirementObservationError::Deadline);
        }
        Ok(())
    })
    .await
    .unwrap_or(Err(TurnRetirementObservationError::Deadline))
}

fn try_registry_lock<'a, T>(
    registry: &'a Mutex<T>,
    name: &str,
) -> Result<MutexGuard<'a, T>, TurnRetirementObservationError> {
    match registry.try_lock() {
        Ok(guard) => Ok(guard),
        Err(TryLockError::WouldBlock) => Err(TurnRetirementObservationError::Busy),
        Err(TryLockError::Poisoned(error)) => {
            panic!("{name} completion registry mutex poisoned: {error:?}")
        }
    }
}
