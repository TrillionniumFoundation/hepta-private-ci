//! Per-host bounded offload for read-only retrieval, including provider I/O.
//! Capacity belongs to the actual blocking closure, not the waiting future.
//! Timeout/cancellation cannot release a slot while its worker is still alive.

use std::future::Future;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_memory_retrieval::RecallWorkControlV1;
use codex_hepta_types::Digest32;
use tokio::sync::Semaphore;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RetrievalWorkClass {
    Delivery,
    Shadow,
}

pub(crate) struct RetrievalExecutor {
    delivery: Arc<Semaphore>,
    shadow: Arc<Semaphore>,
}

impl RetrievalExecutor {
    pub(crate) fn new() -> Self {
        Self {
            delivery: Arc::new(Semaphore::new(2)),
            shadow: Arc::new(Semaphore::new(1)),
        }
    }

    pub(crate) fn begin(&self, class: RetrievalWorkClass) -> RetrievalRequestWork {
        // Fixed source-versioned execution bounds, not numerical product SLOs.
        let duration = match class {
            RetrievalWorkClass::Delivery => Duration::from_millis(800),
            RetrievalWorkClass::Shadow => Duration::from_millis(40),
        };
        let deadline = Instant::now() + duration;
        RetrievalRequestWork {
            control: RecallWorkControlV1::bounded(deadline, 250_000),
            deadline,
            class,
        }
    }

    /// Shadow shares the request's absolute upper bound, not its cancellation
    /// state. An optional experiment must never cancel compatibility delivery.
    pub(crate) fn begin_shadow(&self, parent: &RetrievalRequestWork) -> RetrievalRequestWork {
        let mut shadow = self.begin(RetrievalWorkClass::Shadow);
        shadow.deadline = shadow.deadline.min(parent.deadline);
        shadow.control = RecallWorkControlV1::bounded(shadow.deadline, 250_000);
        if parent.checkpoint().is_err() {
            shadow.control.cancel();
        }
        shadow
    }

    pub(crate) fn profile_digest(&self) -> Digest32 {
        Digest32::of_bytes(
            b"hepta.retrieval.executor.v3:delivery=2,800ms;shadow=1,40ms,parent-bounded;work=250000;queue=0;async=owned-supervised;shadow-cancellation=independent",
        )
    }

    pub(crate) async fn run_async<T, F>(
        &self,
        request: &RetrievalRequestWork,
        operation: F,
    ) -> Result<T, String>
    where
        T: Send + 'static,
        F: Future<Output = T> + Send + 'static,
    {
        request.checkpoint()?;
        let slots = match request.class {
            RetrievalWorkClass::Delivery => &self.delivery,
            RetrievalWorkClass::Shadow => &self.shadow,
        };
        let permit = Arc::clone(slots)
            .try_acquire_owned()
            .map_err(|_| "retrieval execution capacity exhausted".to_string())?;
        let control = request.control.clone();
        let mut cancel_on_drop = CancelOnDrop {
            control: control.clone(),
            armed: true,
        };
        // The owner operation, not its waiter, retains the capacity charge.
        // In particular, dropping a SQLx future need not stop a queued SQLite
        // command. Keep the owned operation alive until it really returns.
        let mut worker = tokio::spawn(async move {
            let _permit = permit;
            control.checkpoint().map_err(|error| error.to_string())?;
            let value = operation.await;
            control.checkpoint().map_err(|error| error.to_string())?;
            Ok(value)
        });
        match tokio::time::timeout_at(
            tokio::time::Instant::from_std(request.deadline),
            &mut worker,
        )
        .await
        {
            Ok(result) => {
                cancel_on_drop.armed = false;
                result.map_err(|_| "retrieval async owner failed".to_string())?
            }
            Err(_) => {
                request.control.cancel();
                // Do not abort: capacity remains owned until the underlying
                // operation exits, and its final checkpoint rejects late success.
                Err("retrieval request deadline exceeded".to_string())
            }
        }
    }

    pub(crate) async fn run<T, F>(
        &self,
        request: &RetrievalRequestWork,
        operation: F,
    ) -> Result<T, String>
    where
        T: Send + 'static,
        F: FnOnce(RecallWorkControlV1) -> Result<T, String> + Send + 'static,
    {
        request
            .control
            .checkpoint()
            .map_err(|error| error.to_string())?;
        let slots = match request.class {
            RetrievalWorkClass::Delivery => &self.delivery,
            RetrievalWorkClass::Shadow => &self.shadow,
        };
        let permit = Arc::clone(slots)
            .try_acquire_owned()
            .map_err(|_| "retrieval execution capacity exhausted".to_string())?;
        let control = request.control.clone();
        let mut cancel_on_drop = CancelOnDrop {
            control: control.clone(),
            armed: true,
        };
        let mut worker = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            control.checkpoint().map_err(|error| error.to_string())?;
            let value = operation(control.clone())?;
            control.checkpoint().map_err(|error| error.to_string())?;
            Ok(value)
        });
        let observed = tokio::time::timeout_at(
            tokio::time::Instant::from_std(request.deadline),
            &mut worker,
        )
        .await;
        match observed {
            Ok(result) => {
                cancel_on_drop.armed = false;
                result.map_err(|_| "retrieval blocking worker failed".to_string())?
            }
            Err(_) => {
                request.control.cancel();
                // This only prevents a not-yet-started blocking task. A started
                // task retains its permit and must observe cooperative checks.
                worker.abort();
                Err("retrieval request deadline exceeded".to_string())
            }
        }
    }
}

pub(crate) struct RetrievalRequestWork {
    control: RecallWorkControlV1,
    deadline: Instant,
    class: RetrievalWorkClass,
}

impl RetrievalRequestWork {
    pub(crate) fn checkpoint(&self) -> Result<(), String> {
        if Instant::now() >= self.deadline {
            self.control.cancel();
            return Err("retrieval request deadline exceeded".to_string());
        }
        self.control.checkpoint().map_err(|error| error.to_string())
    }
}

impl Drop for RetrievalRequestWork {
    fn drop(&mut self) {
        self.control.cancel();
    }
}

struct CancelOnDrop {
    control: RecallWorkControlV1,
    armed: bool,
}

impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        if self.armed {
            self.control.cancel();
        }
    }
}

#[cfg(test)]
#[path = "retrieval_executor_tests.rs"]
mod tests;
