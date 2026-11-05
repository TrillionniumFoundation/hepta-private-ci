use std::future::Future;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;

use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::ThreadBackgroundTerminalsTerminateObservedResponse as Response;
use codex_app_server_protocol::ThreadBackgroundTerminalsTerminateObservedStatus as Status;
use tokio::sync::oneshot;
use tokio::time::Duration;
use tokio::time::Instant;
use tokio::time::sleep_until;
use tokio_util::sync::CancellationToken;

use crate::error_code::invalid_params;

type Outcome = Result<Response, JSONRPCErrorError>;

pub(crate) fn not_confirmed() -> Response {
    Response {
        status: Status::NotConfirmed,
    }
}

enum Phase {
    Queued,
    Running,
    Completed,
    Expired,
}

struct State {
    phase: Phase,
    reply: Option<oneshot::Sender<Outcome>>,
}

struct Shared {
    end: Instant,
    state: Mutex<State>,
    cancelled: CancellationToken,
}

impl Shared {
    fn state(&self) -> MutexGuard<'_, State> {
        match self.state.lock() {
            Ok(state) => state,
            Err(poisoned) => {
                let mut state = poisoned.into_inner();
                state.phase = Phase::Expired;
                if let Some(reply) = state.reply.take() {
                    let _ = reply.send(Ok(not_confirmed()));
                }
                self.cancelled.cancel();
                state
            }
        }
    }

    fn expire(&self) {
        let mut state = self.state();
        if matches!(state.phase, Phase::Queued | Phase::Running) {
            state.phase = Phase::Expired;
            if let Some(reply) = state.reply.take() {
                let _ = reply.send(Ok(not_confirmed()));
            }
            self.cancelled.cancel();
        }
    }

    fn start(&self) -> bool {
        let mut state = self.state();
        if !matches!(state.phase, Phase::Queued) || Instant::now() >= self.end {
            drop(state);
            self.expire();
            return false;
        }
        state.phase = Phase::Running;
        true
    }

    fn finish(&self, outcome: Outcome) {
        let mut state = self.state();
        if !matches!(state.phase, Phase::Running) {
            return;
        }
        let outcome = if Instant::now() >= self.end {
            state.phase = Phase::Expired;
            Ok(not_confirmed())
        } else {
            state.phase = Phase::Completed;
            outcome
        };
        if let Some(reply) = state.reply.take() {
            let _ = reply.send(outcome);
        }
    }
}

/// Lives in the original serialized queue, even before its future is first polled.
pub(crate) struct QueuedTermination {
    shared: Arc<Shared>,
}

/// The only response owner. Its timer runs independently of a blocked queue.
pub(crate) struct TerminationReply {
    shared: Arc<Shared>,
    receiver: oneshot::Receiver<Outcome>,
}

pub(crate) fn admit(
    admitted_at: Instant,
    observation_timeout_ms: u32,
) -> Result<(QueuedTermination, TerminationReply), JSONRPCErrorError> {
    if observation_timeout_ms == 0 {
        return Err(invalid_params("observationTimeoutMs must be positive"));
    }
    let end = admitted_at
        .checked_add(Duration::from_millis(u64::from(observation_timeout_ms)))
        .ok_or_else(|| invalid_params("observationTimeoutMs exceeds the local clock range"))?;
    let (sender, receiver) = oneshot::channel();
    let shared = Arc::new(Shared {
        end,
        state: Mutex::new(State {
            phase: Phase::Queued,
            reply: Some(sender),
        }),
        cancelled: CancellationToken::new(),
    });
    Ok((
        QueuedTermination {
            shared: Arc::clone(&shared),
        },
        TerminationReply { shared, receiver },
    ))
}

impl QueuedTermination {
    pub(crate) fn end(&self) -> Instant {
        self.shared.end
    }

    pub(crate) async fn run<F, Fut>(self, operation: F)
    where
        F: FnOnce(Instant) -> Fut,
        Fut: Future<Output = Outcome>,
    {
        if !self.shared.start() {
            return;
        }
        let end = self.shared.end;
        let outcome = tokio::select! {
            biased;
            () = self.shared.cancelled.cancelled() => Ok(not_confirmed()),
            () = sleep_until(end) => Ok(not_confirmed()),
            outcome = operation(end) => outcome,
        };
        self.shared.finish(outcome);
    }
}

impl Drop for QueuedTermination {
    fn drop(&mut self) {
        // Includes gate rejection, an unpolled queue entry, panic, and cancellation.
        // If execution began, dropping its future leaves Core's original owner guard active.
        self.shared.expire();
    }
}

impl TerminationReply {
    pub(crate) async fn wait(mut self) -> Outcome {
        tokio::select! {
            biased;
            outcome = &mut self.receiver => outcome.unwrap_or_else(|_| Ok(not_confirmed())),
            () = sleep_until(self.shared.end) => {
                self.shared.expire();
                // A result recorded before expiry remains valid even if outbound delivery
                // is delayed. No wait or additional grace is introduced here.
                self.receiver.try_recv().unwrap_or_else(|_| Ok(not_confirmed()))
            }
        }
    }
}

impl Drop for TerminationReply {
    fn drop(&mut self) {
        // Losing the sole response owner fences queued effects and cancels running work.
        self.shared.expire();
    }
}

#[cfg(test)]
#[path = "termination_observation_tests.rs"]
mod tests;
