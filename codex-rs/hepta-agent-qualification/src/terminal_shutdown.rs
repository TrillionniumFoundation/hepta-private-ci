//! Shared marker/cap shutdown boundary. Settlement is not a successful ACK.
use crate::evidence::ExactBodyObserver;
use codex_hepta_agent_loop::ManagedResponsesTerminalCompletion;
use codex_state::StateRuntime;
use std::future::Future;
use std::time::Duration;

pub(crate) struct TerminalShutdown {
    writes_settled: bool,
    encoded_recorded: bool,
}

impl TerminalShutdown {
    pub(crate) async fn wait(
        completion: &mut ManagedResponsesTerminalCompletion,
        observer: &ExactBodyObserver,
        grace: Duration,
    ) -> Self {
        Self::observe(completion.wait(), observer.terminal_recorded(), grace).await
    }

    // Private future seam exercises the exact grace/close code without a model,
    // transport, fabricated public completion handle, or replacement owner.
    async fn observe(
        settlement: impl Future<Output = codex_hepta_agent_loop::Result<()>>,
        encoded: impl Future<Output = ()>,
        grace: Duration,
    ) -> Self {
        let (settled, encoded) = tokio::join!(
            tokio::time::timeout(grace, settlement),
            tokio::time::timeout(grace, encoded),
        );
        Self {
            writes_settled: matches!(settled, Ok(Ok(()))),
            encoded_recorded: encoded.is_ok(),
        }
    }

    pub(crate) fn writes_settled(&self) -> bool {
        self.writes_settled
    }

    pub(crate) fn encoded_recorded(&self) -> bool {
        self.encoded_recorded
    }

    pub(crate) async fn close_if_settled(&self, state: &StateRuntime) {
        if self.writes_settled {
            state.close().await;
        }
    }
}

#[cfg(test)]
#[path = "terminal_shutdown_tests.rs"]
mod tests;
