use std::future::Future;
use std::sync::Arc;
use std::sync::Mutex;

use futures::future::BoxFuture;
use tokio::sync::Semaphore;
use tokio::sync::oneshot;

use crate::CodexThread;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;

struct DeferredIdleWork {
    tail: Mutex<Option<oneshot::Receiver<()>>>,
    capacity: Arc<Semaphore>,
}

impl Default for DeferredIdleWork {
    fn default() -> Self {
        Self {
            tail: Mutex::default(),
            capacity: Arc::new(Semaphore::new(/*permits*/ 32)),
        }
    }
}

impl DeferredIdleWork {
    fn defer(
        &self,
        completion: BoxFuture<'static, ()>,
        work: impl Future<Output = ()> + Send + 'static,
        terminated: impl Future<Output = ()> + Send + 'static,
    ) -> CodexResult<()> {
        let permit = Arc::clone(&self.capacity)
            .try_acquire_owned()
            .map_err(|_| {
                CodexErr::InvalidRequest("too many deferred idle contributions".to_string())
            })?;
        let (finished, next) = oneshot::channel();
        let previous = self
            .tail
            .lock()
            .unwrap_or_else(|error| panic!("idle contribution ordering mutex poisoned: {error}"))
            .replace(next);
        tokio::spawn(async move {
            let _permit = permit;
            // Dropping the sender also releases followers after cancellation
            // or panic. Each follower still waits for the original fence and
            // must use normal admission; ordering never grants authority.
            let _finished = finished;
            let ordered_work = async {
                if let Some(previous) = previous {
                    let _ = previous.await;
                }
                completion.await;
                work.await;
            };
            tokio::select! {
                biased;
                () = terminated => {}
                () = ordered_work => {}
            }
        });
        Ok(())
    }
}

impl CodexThread {
    /// Defers one idle contribution until its current terminalizer can finish.
    ///
    /// Contributions retain registration order (queued user input precedes
    /// automatic goal continuation), with at most 32 pending per thread. This
    /// schedules callbacks only: their normal authority, durability and atomic
    /// turn-admission checks remain mandatory.
    pub fn defer_idle_work(
        &self,
        completion: BoxFuture<'static, ()>,
        work: impl Future<Output = ()> + Send + 'static,
    ) -> CodexResult<()> {
        self.session
            .services
            .thread_extension_data
            .get_or_init(DeferredIdleWork::default)
            .defer(completion, work, self.io.session_loop_termination.clone())
    }
}

#[cfg(test)]
#[path = "idle_work_tests.rs"]
mod tests;
