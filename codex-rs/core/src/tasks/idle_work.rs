use std::future::Future;
use std::sync::Arc;
use std::sync::Mutex;

use futures::FutureExt;
use futures::future::BoxFuture;
use futures::future::Shared;
use tokio::sync::Semaphore;
use tokio::sync::oneshot;

use crate::CodexThread;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;

/// Orders queued user input ahead of automatic work observing the same fence.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IdleWorkPriority {
    QueuedInput,
    AutomaticContinuation,
}

type IdleWorkCompletion = Shared<BoxFuture<'static, ()>>;

#[derive(Default)]
struct IdleWorkTails {
    queued_input: Option<IdleWorkCompletion>,
    automatic_continuation: Option<IdleWorkCompletion>,
}

struct DeferredIdleWork {
    tails: Arc<Mutex<IdleWorkTails>>,
    capacity: Arc<Semaphore>,
    automatic_capacity: Arc<Semaphore>,
}

impl Default for DeferredIdleWork {
    fn default() -> Self {
        Self {
            tails: Arc::default(),
            capacity: Arc::new(Semaphore::new(/*permits*/ 32)),
            // Automatic work cannot consume the last slot needed by Queue.
            automatic_capacity: Arc::new(Semaphore::new(/*permits*/ 31)),
        }
    }
}

impl DeferredIdleWork {
    fn defer(
        &self,
        priority: IdleWorkPriority,
        completion: BoxFuture<'static, ()>,
        work: impl Future<Output = ()> + Send + 'static,
        terminated: impl Future<Output = ()> + Send + 'static,
    ) -> CodexResult<()> {
        let automatic_permit = match priority {
            IdleWorkPriority::QueuedInput => None,
            IdleWorkPriority::AutomaticContinuation => Some(
                Arc::clone(&self.automatic_capacity)
                    .try_acquire_owned()
                    .map_err(|_| {
                        CodexErr::InvalidRequest("too many deferred idle contributions".to_string())
                    })?,
            ),
        };
        let permit = Arc::clone(&self.capacity)
            .try_acquire_owned()
            .map_err(|_| {
                CodexErr::InvalidRequest("too many deferred idle contributions".to_string())
            })?;
        let (finished, next) = oneshot::channel::<()>();
        let next = async move {
            let _ = next.await;
        }
        .boxed()
        .shared();
        let tails = Arc::clone(&self.tails);
        let previous = {
            let mut tails = tails.lock().unwrap_or_else(|error| {
                panic!("idle contribution ordering mutex poisoned: {error}")
            });
            match priority {
                IdleWorkPriority::QueuedInput => tails.queued_input.replace(next),
                IdleWorkPriority::AutomaticContinuation => {
                    tails.automatic_continuation.replace(next)
                }
            }
        };
        tokio::spawn(async move {
            let _permit = permit;
            let _automatic_permit = automatic_permit;
            // Dropping the sender also releases followers after cancellation
            // or panic. Each follower still waits for the original fence and
            // must use normal admission; ordering never grants authority.
            let _finished = finished;
            let ordered_work = async {
                if let Some(previous) = previous {
                    previous.await;
                }
                completion.await;
                if priority == IdleWorkPriority::AutomaticContinuation {
                    // An older idle notification can reach Goal while a newer
                    // terminalizer has not reached Queue yet. Its fence cannot
                    // complete until all those callbacks have registered, so
                    // snapshot Queue only after the fence. Queue never waits
                    // for automatic work, including this earlier registration.
                    let queued_input = tails
                        .lock()
                        .unwrap_or_else(|error| {
                            panic!("idle contribution ordering mutex poisoned: {error}")
                        })
                        .queued_input
                        .clone();
                    if let Some(queued_input) = queued_input {
                        queued_input.await;
                    }
                }
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
    /// Each priority retains registration order, with at most 32 pending in
    /// total per thread. Automatic work also waits for all queued input already
    /// registered when its fence completes, even if that input registered
    /// later. This schedules callbacks only: normal authority, durability and
    /// atomic turn-admission checks remain mandatory.
    pub fn defer_idle_work(
        &self,
        priority: IdleWorkPriority,
        completion: BoxFuture<'static, ()>,
        work: impl Future<Output = ()> + Send + 'static,
    ) -> CodexResult<()> {
        self.session
            .services
            .thread_extension_data
            .get_or_init(DeferredIdleWork::default)
            .defer(
                priority,
                completion,
                work,
                self.io.session_loop_termination.clone(),
            )
    }
}

#[cfg(test)]
#[path = "idle_work_tests.rs"]
mod tests;
