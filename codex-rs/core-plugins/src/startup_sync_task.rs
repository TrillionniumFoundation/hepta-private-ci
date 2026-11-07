//! Retains the actual startup thread until its owner cancels and joins it.

use codex_git_utils::GitCommandCancellation;
use std::io;
use std::sync::Condvar;
use std::sync::Mutex;
use std::thread::JoinHandle;
use std::thread::ThreadId;

struct Running {
    cancellation: GitCommandCancellation,
    thread: JoinHandle<()>,
}

#[derive(Default)]
struct State {
    closed: bool,
    running: Option<Running>,
    joining: Option<ThreadId>,
    terminal: Option<Result<(), String>>,
}

#[derive(Default)]
pub(crate) struct StartupSyncTask {
    state: Mutex<State>,
    joined: Condvar,
}

impl StartupSyncTask {
    pub(crate) fn start(
        &self,
        run: impl FnOnce(GitCommandCancellation) + Send + 'static,
    ) -> io::Result<()> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.closed || state.joining.is_some() {
            return Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "plugin startup owner has closed",
            ));
        }
        if state
            .running
            .as_ref()
            .is_some_and(|running| !running.thread.is_finished())
        {
            return Err(io::Error::new(
                io::ErrorKind::AlreadyExists,
                "plugin startup thread is already owned",
            ));
        }
        if let Some(previous) = state.running.take() {
            // is_finished above guarantees that no callback can wait on this lock.
            previous
                .thread
                .join()
                .map_err(|_| io::Error::other("previous plugin startup thread panicked"))?;
        }
        let cancellation = GitCommandCancellation::default();
        let worker_cancellation = cancellation.clone();
        let thread = std::thread::Builder::new()
            .name("plugins-curated-repo-sync".to_string())
            .spawn(move || run(worker_cancellation))?;
        state.running = Some(Running {
            cancellation,
            thread,
        });
        state.terminal = None;
        Ok(())
    }

    pub(crate) fn cancel(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.closed = true;
        if let Some(running) = &state.running {
            running.cancellation.cancel();
        }
    }

    /// A completed join only attests thread completion, not a successful plugin
    /// sync. Concurrent shutdown callers wait for the same retained join result.
    pub(crate) fn shutdown(&self) -> Result<(), String> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.closed = true;
        loop {
            if let Some(worker_id) = state.joining {
                if worker_id == std::thread::current().id() {
                    return Err("plugin startup worker cannot join itself".to_string());
                }
                state = self
                    .joined
                    .wait(state)
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                continue;
            }
            let Some(running) = state.running.take() else {
                return state.terminal.clone().unwrap_or(Ok(()));
            };
            running.cancellation.cancel();
            let worker_id = running.thread.thread().id();
            state.joining = Some(worker_id);
            drop(state);
            let result = if worker_id == std::thread::current().id() {
                // This can only occur if the worker's short final cache callback
                // held the last manager Arc. It has already left the sync run;
                // do not deadlock or call this an observed successful join.
                drop(running.thread);
                Err("plugin startup owner dropped on its own worker; join unavailable".to_string())
            } else {
                running
                    .thread
                    .join()
                    .map_err(|_| "plugin startup thread panicked".to_string())
            };
            state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.joining = None;
            state.terminal = Some(result.clone());
            self.joined.notify_all();
            return result;
        }
    }
}

impl Drop for StartupSyncTask {
    fn drop(&mut self) {
        if let Err(error) = self.shutdown() {
            tracing::warn!("plugin startup shutdown did not complete a join: {error}");
        }
    }
}

#[cfg(test)]
#[path = "startup_sync_task_tests.rs"]
mod tests;
