use futures::future::BoxFuture;

use super::TERMINALIZER_WATCHDOG_TIMEOUT;
use crate::session::session::Session;

impl Session {
    pub(crate) fn pending_turn_terminalization(&self) -> Option<BoxFuture<'static, ()>> {
        let completions = self
            .pending_task_terminalization_completions_except(/*excluded_identity*/ None);
        if completions.is_empty() {
            return None;
        }
        Some(Box::pin(async move {
            // Observe only the current owners; never adopt, replay or release
            // them. The normal atomic admission checks still decide whether a
            // later submission may start, including after this bounded wait.
            let _ = tokio::time::timeout(TERMINALIZER_WATCHDOG_TIMEOUT, async move {
                for completion in completions {
                    completion.wait().await;
                }
            })
            .await;
        }))
    }
}
