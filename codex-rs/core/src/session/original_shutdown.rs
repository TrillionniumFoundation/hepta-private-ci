//! Observe the original submission-loop handle without changing the default
//! unit completion future. Strict cleanup keeps its real JoinError separately.

use super::SessionIo;
use super::SessionLoopTermination;
use super::new_submission_id;
use async_channel::Sender;
use codex_otel::current_span_w3c_trace_context;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::Submission;
use futures::FutureExt;
use futures::future::BoxFuture;
use futures::future::Shared;
use std::fmt;
use std::sync::Arc;
use std::sync::OnceLock;
use tokio::task::JoinError;
use tokio::task::JoinHandle;

#[derive(Debug)]
pub(crate) enum OriginalCoreTaskFailure {
    Join(Arc<JoinError>),
    State(&'static str),
}

impl fmt::Display for OriginalCoreTaskFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Join(error) => write!(formatter, "original Core task join failed: {error}"),
            Self::State(message) => formatter.write_str(message),
        }
    }
}

impl std::error::Error for OriginalCoreTaskFailure {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Join(error) => Some(error.as_ref()),
            Self::State(_) => None,
        }
    }
}

pub(crate) struct OriginalSessionLoopOutcome {
    result: OnceLock<Result<(), Arc<JoinError>>>,
}

/// This is the SAME actual handle and the same unit-valued Shared future
/// exposed to ordinary SessionIo callers. No second task observes the handle.
pub(super) fn observe_original_session_loop(
    handle: JoinHandle<()>,
) -> (SessionLoopTermination, Arc<OriginalSessionLoopOutcome>) {
    let outcome = Arc::new(OriginalSessionLoopOutcome {
        result: OnceLock::new(),
    });
    let recorded = Arc::clone(&outcome);
    let termination = async move {
        let result = handle.await.map_err(Arc::new);
        // The only writer is this one shared future, after its actual join.
        let _ = recorded.result.set(result);
    }
    .boxed()
    .shared();
    (termination, outcome)
}

pub(crate) struct OriginalSessionLoopShutdown {
    completion: Shared<BoxFuture<'static, Result<(), Arc<OriginalCoreTaskFailure>>>>,
}

impl SessionIo {
    pub(crate) fn retain_original_loop_shutdown(&self) -> Arc<OriginalSessionLoopShutdown> {
        Arc::new(OriginalSessionLoopShutdown::new(
            self.tx_sub.clone(),
            self.session_loop_termination.clone(),
            self.original_loop_outcome.as_ref().map(Arc::clone),
        ))
    }
}

impl OriginalSessionLoopShutdown {
    fn new(
        sender: Sender<Submission>,
        termination: SessionLoopTermination,
        outcome: Option<Arc<OriginalSessionLoopOutcome>>,
    ) -> Self {
        let completion = async move {
            if outcome
                .as_ref()
                .is_none_or(|outcome| outcome.result.get().is_none())
            {
                // A closed submission channel has the same cleanup meaning as
                // ordinary SessionIo::shutdown_and_wait's InternalAgentDied.
                // It never substitutes for the actual loop join below.
                let _ = sender
                    .send(Submission {
                        id: new_submission_id(),
                        op: Op::Shutdown,
                        trace: current_span_w3c_trace_context(),
                        parent_turn_id: None,
                        root_turn_id: None,
                    })
                    .await;
            }
            drop(sender);
            termination.await;
            match outcome.as_ref().and_then(|outcome| outcome.result.get()) {
                Some(Ok(())) => Ok(()),
                Some(Err(error)) => Err(Arc::new(OriginalCoreTaskFailure::Join(Arc::clone(error)))),
                None => Err(Arc::new(OriginalCoreTaskFailure::State(
                    "the original Session loop completed without its real outcome",
                ))),
            }
        }
        .boxed()
        .shared();
        Self { completion }
    }

    /// A cancelled waiter drops only this Shared clone. The registry retains
    /// the actual shutdown/join future; another waiter does not submit again.
    pub(crate) async fn join_original_loop(&self) -> Result<(), Arc<OriginalCoreTaskFailure>> {
        self.completion.clone().await
    }
}

#[cfg(test)]
pub(crate) fn original_loop_io_for_test(
    sender: Sender<Submission>,
    handle: JoinHandle<()>,
) -> SessionIo {
    let (_events, rx_event) = async_channel::unbounded();
    let (_status, agent_status) =
        tokio::sync::watch::channel(crate::agent::AgentStatus::PendingInit);
    let (session_loop_termination, outcome) = observe_original_session_loop(handle);
    SessionIo {
        tx_sub: sender,
        rx_event,
        agent_status,
        session_loop_termination,
        original_loop_outcome: Some(outcome),
    }
}

#[cfg(test)]
#[path = "original_shutdown_tests.rs"]
mod tests;
