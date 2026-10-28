//! Read-only waits for the exact cleanup owners that exist at capture time.

use std::sync::Arc;
use std::sync::atomic::Ordering;

use futures::FutureExt;
use futures::future::BoxFuture;

use crate::codex_thread::CodexThread;
use crate::session::SessionLoopTermination;
use crate::session::session::Session;
use crate::state::StartTransitionCompletion;

impl Session {
    pub(crate) fn pending_cleanup_completions(&self) -> Vec<Arc<StartTransitionCompletion>> {
        let mut completions = self
            .pending_start_transition_completions
            .lock()
            .unwrap_or_else(|error| panic!("start transition registry mutex poisoned: {error:?}"))
            .iter()
            .map(|(_, completion, _)| Arc::clone(completion))
            .collect::<Vec<_>>();
        completions.extend(
            self.pending_task_terminalization_completions
                .lock()
                .unwrap_or_else(|error| {
                    panic!("task terminalization registry mutex poisoned: {error:?}")
                })
                .iter()
                .map(|(_, completion, _, _, _, _)| Arc::clone(completion)),
        );
        completions.retain(|completion| !completion.is_complete());
        completions
    }
}

impl Session {
    pub(crate) fn pending_cleanup_snapshot(
        self: &Arc<Self>,
        stopped: SessionLoopTermination,
    ) -> Option<(u64, BoxFuture<'static, bool>)> {
        let generation = self.turn_epoch.load(Ordering::Acquire);
        let completions = self.pending_cleanup_completions();
        if completions.is_empty() {
            return None;
        }
        let session = Arc::downgrade(self);
        Some((
            generation,
            async move {
                for completion in completions {
                    tokio::select! {
                        () = completion.wait() => {},
                        () = stopped.clone() => return false,
                    }
                }
                session.upgrade().is_some_and(|session| {
                    !session.shutdown_started()
                        && session.turn_epoch.load(Ordering::Acquire) == generation
                })
            }
            .boxed(),
        ))
    }
}

impl CodexThread {
    /// Captures existing cleanup owners without granting turn-start authority.
    ///
    /// The returned generation identifies this observation for wake-up deduplication.
    /// The owned future returns true only if those exact owners completed and the
    /// same task generation is still current without shutdown. Callers must still
    /// recheck the loaded thread and use the normal atomic admission path.
    pub fn pending_turn_cleanup(&self) -> Option<(u64, BoxFuture<'static, bool>)> {
        self.session
            .pending_cleanup_snapshot(self.io.session_loop_termination.clone())
    }
}

#[cfg(test)]
#[path = "cleanup_tests.rs"]
mod tests;
