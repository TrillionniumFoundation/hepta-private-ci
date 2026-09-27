//! Per-host bounded offload and one absolute request deadline for retrieval.
//!
//! Capacity belongs to the actual blocking closure, not the waiting future.
//! Timeout/cancellation cannot release a slot while its worker is still alive.
//! Ranker and ledger work have independent bounded pools but consume the same
//! request deadline as SQLite observation, owner adaptation and final use.

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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RetrievalBlockingPool {
    Primary(RetrievalWorkClass),
    Ranker,
    Ledger,
}

pub(crate) struct RetrievalExecutor {
    delivery: Arc<Semaphore>,
    shadow: Arc<Semaphore>,
    ranker: Arc<Semaphore>,
    ledger: Arc<Semaphore>,
}

impl RetrievalExecutor {
    pub(crate) fn new() -> Self {
        Self {
            delivery: Arc::new(Semaphore::new(2)),
            shadow: Arc::new(Semaphore::new(1)),
            ranker: Arc::new(Semaphore::new(1)),
            ledger: Arc::new(Semaphore::new(1)),
        }
    }

    pub(crate) fn begin(&self, class: RetrievalWorkClass) -> RetrievalRequestWork {
        // Fixed source-versioned execution bounds, not numerical product SLOs.
        let duration = match class {
            RetrievalWorkClass::Delivery => Duration::from_millis(800),
            RetrievalWorkClass::Shadow => Duration::from_millis(40),
        };
        self.begin_with_duration(class, duration)
    }

    fn begin_with_duration(
        &self,
        class: RetrievalWorkClass,
        duration: Duration,
    ) -> RetrievalRequestWork {
        let deadline = Instant::now() + duration;
        RetrievalRequestWork {
            control: RecallWorkControlV1::bounded(deadline, 250_000),
            deadline,
            class,
        }
    }

    pub(crate) fn profile_digest(&self) -> Digest32 {
        Digest32::of_bytes(
            b"hepta.retrieval.executor.v2:delivery=2,800ms;shadow=1,40ms;ranker=1;ledger=1;work=250000;queue=0;absolute-deadline=all-stages",
        )
    }

    /// Bound an async stage by the same request deadline. Dropping the future
    /// is the cancellation boundary; blocking work must use one of the pools
    /// below so its permit remains held until the real worker exits.
    pub(crate) async fn wait<T, F>(
        &self,
        request: &RetrievalRequestWork,
        operation: F,
    ) -> Result<T, String>
    where
        F: Future<Output = T>,
    {
        request.checkpoint()?;
        let observed = tokio::time::timeout_at(
            tokio::time::Instant::from_std(request.deadline),
            operation,
        )
        .await;
        match observed {
            Ok(value) => {
                request.checkpoint()?;
                Ok(value)
            }
            Err(_) => {
                request.cancel();
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
        self.run_on(
            request,
            RetrievalBlockingPool::Primary(request.class),
            operation,
        )
        .await
    }

    pub(crate) async fn run_ranker<T, F>(
        &self,
        request: &RetrievalRequestWork,
        operation: F,
    ) -> Result<T, String>
    where
        T: Send + 'static,
        F: FnOnce(RecallWorkControlV1) -> Result<T, String> + Send + 'static,
    {
        self.run_on(request, RetrievalBlockingPool::Ranker, operation)
            .await
    }

    pub(crate) async fn run_ledger<T, F>(
        &self,
        request: &RetrievalRequestWork,
        operation: F,
    ) -> Result<T, String>
    where
        T: Send + 'static,
        F: FnOnce(RecallWorkControlV1) -> Result<T, String> + Send + 'static,
    {
        self.run_on(request, RetrievalBlockingPool::Ledger, operation)
            .await
    }

    async fn run_on<T, F>(
        &self,
        request: &RetrievalRequestWork,
        pool: RetrievalBlockingPool,
        operation: F,
    ) -> Result<T, String>
    where
        T: Send + 'static,
        F: FnOnce(RecallWorkControlV1) -> Result<T, String> + Send + 'static,
    {
        request.checkpoint()?;
        let permit = Arc::clone(self.slots(pool))
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
                request.cancel();
                // This only prevents a not-yet-started blocking task. A started
                // task retains its pool permit and must observe cooperative checks.
                worker.abort();
                Err("retrieval request deadline exceeded".to_string())
            }
        }
    }

    fn slots(&self, pool: RetrievalBlockingPool) -> &Arc<Semaphore> {
        match pool {
            RetrievalBlockingPool::Primary(RetrievalWorkClass::Delivery) => &self.delivery,
            RetrievalBlockingPool::Primary(RetrievalWorkClass::Shadow) => &self.shadow,
            RetrievalBlockingPool::Ranker => &self.ranker,
            RetrievalBlockingPool::Ledger => &self.ledger,
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
        self.control
            .checkpoint()
            .map_err(|error| error.to_string())
    }

    fn cancel(&self) {
        self.control.cancel();
    }
}

impl Drop for RetrievalRequestWork {
    fn drop(&mut self) {
        self.cancel();
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
