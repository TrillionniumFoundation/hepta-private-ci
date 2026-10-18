//! Per-host bounded offload for read-only retrieval, including provider I/O.
//! Capacity belongs to the actual blocking closure, not the waiting future.
//! Timeout/cancellation cannot release a slot while its worker is still alive.

use std::future::Future;
use std::sync::Arc;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_agent_components::memory_retrieval::RecallWorkControlV1;
use codex_hepta_agent_components::types::Digest32;
use tokio::sync::Semaphore;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RetrievalWorkClass {
    Delivery,
    Shadow,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RetrievalBlockingKind {
    Core,
    Ranker,
    Ledger,
}

pub(crate) struct RetrievalExecutor {
    delivery: Arc<Semaphore>,
    shadow: Arc<Semaphore>,
    ranker: Arc<Semaphore>,
    ledger: Arc<Semaphore>,
    next_worker_id: AtomicU64,
}

impl RetrievalExecutor {
    pub(crate) fn new() -> Self {
        Self {
            delivery: Arc::new(Semaphore::new(2)),
            shadow: Arc::new(Semaphore::new(1)),
            ranker: Arc::new(Semaphore::new(1)),
            ledger: Arc::new(Semaphore::new(1)),
            next_worker_id: AtomicU64::new(1),
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
            b"hepta.retrieval.executor.v5:delivery=2,800ms;shadow=1,40ms,parent-bounded;work=250000;queue=0;ranker=1;ledger=1;auxiliary-permit=worker-owned;async=owned-supervised;shadow-cancellation=independent;provider-deadline=request-absolute;worker-exit=observed",
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
        let worker_id = self
            .next_worker_id
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                value.checked_add(1)
            })
            .map_err(|_| "retrieval worker identity exhausted".to_string())?;
        let activity = Arc::new(WorkerActivity {
            id: worker_id,
            class: request.class,
            started: Instant::now(),
            state: AtomicU8::new(0),
        });
        let worker_exit = WorkerExit(Arc::clone(&activity));
        let control = request.control.clone();
        let mut cancel_on_drop = CancelOnDrop {
            control: control.clone(),
            activity,
            armed: true,
        };
        // The owner operation, not its waiter, retains the capacity charge.
        // In particular, dropping a SQLx future need not stop a queued SQLite
        // command. Keep the owned operation alive until it really returns.
        let mut worker = tokio::spawn(async move {
            let _permit = permit;
            let _worker_exit = worker_exit;
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
        kind: RetrievalBlockingKind,
        operation: F,
    ) -> Result<T, String>
    where
        T: Send + 'static,
        F: FnOnce(RecallWorkControlV1) -> Result<T, String> + Send + 'static,
    {
        request.checkpoint()?;
        // Auxiliary owners cannot consume both delivery slots while blocked.
        // No wait queue: failure never starts an effect and never renews time.
        let auxiliary = match kind {
            RetrievalBlockingKind::Core => None,
            RetrievalBlockingKind::Ranker => Some(Arc::clone(&self.ranker)),
            RetrievalBlockingKind::Ledger => Some(Arc::clone(&self.ledger)),
        }
        .map(|pool| {
            pool.try_acquire_owned()
                .map_err(|_| "retrieval auxiliary capacity exhausted".to_string())
        })
        .transpose()?;

        let slots = match request.class {
            RetrievalWorkClass::Delivery => &self.delivery,
            RetrievalWorkClass::Shadow => &self.shadow,
        };
        let permit = Arc::clone(slots)
            .try_acquire_owned()
            .map_err(|_| "retrieval execution capacity exhausted".to_string())?;
        let worker_id = self
            .next_worker_id
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                value.checked_add(1)
            })
            .map_err(|_| "retrieval worker identity exhausted".to_string())?;
        let activity = Arc::new(WorkerActivity {
            id: worker_id,
            class: request.class,
            started: Instant::now(),
            state: AtomicU8::new(0),
        });
        let worker_exit = WorkerExit(Arc::clone(&activity));
        let control = request.control.clone();
        let mut cancel_on_drop = CancelOnDrop {
            control: control.clone(),
            activity,
            armed: true,
        };
        let mut worker = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let _auxiliary = auxiliary;
            let _worker_exit = worker_exit;
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
    pub(crate) fn deadline(&self) -> Instant {
        self.deadline
    }

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

struct WorkerActivity {
    id: u64,
    class: RetrievalWorkClass,
    started: Instant,
    // 0 = owned, 1 = abandoned waiter / still owned, 2 = actual exit.
    state: AtomicU8,
}

struct WorkerExit(Arc<WorkerActivity>);

impl Drop for WorkerExit {
    fn drop(&mut self) {
        let previous = self.0.state.swap(2, Ordering::AcqRel);
        if previous == 1 {
            tracing::warn!(worker_id = self.0.id, class = ?self.0.class,
                elapsed_ms = u64::try_from(self.0.started.elapsed().as_millis()).unwrap_or(u64::MAX),
                "abandoned retrieval worker actually exited");
        } else {
            tracing::debug!(worker_id = self.0.id, class = ?self.0.class,
                "retrieval worker actually exited");
        }
    }
}

struct CancelOnDrop {
    control: RecallWorkControlV1,
    activity: Arc<WorkerActivity>,
    armed: bool,
}

impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        if self.armed {
            self.control.cancel();
            if self
                .activity
                .state
                .compare_exchange(0, 1, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                tracing::warn!(worker_id = self.activity.id, class = ?self.activity.class,
                    "retrieval waiter abandoned; worker retains capacity until actual exit");
            }
        }
    }
}

#[cfg(test)]
#[path = "retrieval_executor_tests.rs"]
mod tests;
