//! Bounded task ownership on the existing Agentd Tokio runtime.
//!
//! Dropping a response receiver cancels waiting, not the owned effect task.
//! Admission and shutdown share one lock. Draining never takes the JoinSet out
//! of its owner and never aborts it: timeout/cancellation retains all unjoined
//! tasks and the same durable AutomationStore attempt identities.

use std::future::Future;
use std::sync::Mutex;
use std::time::Duration;

use tokio::runtime::Handle;
use tokio::sync::oneshot;
use tokio::task::JoinSet;
use tokio::time::Instant;

struct State {
    tasks: JoinSet<()>,
    closed: bool,
    failed_joins: usize,
}

impl State {
    fn reap(&mut self) {
        while let Some(result) = self.tasks.try_join_next() {
            if result.is_err() {
                self.failed_joins = self.failed_joins.saturating_add(1);
            }
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct EffectTaskSnapshot {
    pub(super) remaining: usize,
    pub(super) failed_joins: usize,
}

pub(super) struct EffectTasks {
    state: Mutex<State>,
    capacity: usize,
}

impl EffectTasks {
    pub(super) fn new(capacity: usize) -> Self {
        Self {
            state: Mutex::new(State {
                tasks: JoinSet::new(),
                closed: false,
                failed_joins: 0,
            }),
            capacity,
        }
    }

    pub(super) fn submit<T, F>(
        &self,
        make: impl FnOnce() -> F,
    ) -> Result<oneshot::Receiver<T>, &'static str>
    where
        T: Send + 'static,
        F: Future<Output = T> + Send + 'static,
    {
        let runtime = Handle::try_current().map_err(|_| "effect runtime is unavailable")?;
        let mut state = self
            .state
            .lock()
            .map_err(|_| "effect task owner is poisoned")?;
        state.reap();
        if state.closed {
            return Err("effect task admission is closed for shutdown");
        }
        if state.tasks.len() >= self.capacity {
            return Err("effect task capacity exhausted; no new effect was admitted");
        }
        let (sender, receiver) = oneshot::channel();
        let future = make();
        state.tasks.spawn_on(
            async move {
                let result = future.await;
                // A cancelled client does not cancel owner persistence/reconciliation.
                let _ = sender.send(result);
            },
            &runtime,
        );
        Ok(receiver)
    }

    // This synchronous cut closes all clones before a caller begins awaiting.
    // Closing does not revoke authority, reset history, or imply provider absence.
    pub(super) fn close(&self) -> Result<EffectTaskSnapshot, &'static str> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| "effect task owner is poisoned")?;
        state.closed = true;
        state.reap();
        Ok(EffectTaskSnapshot {
            remaining: state.tasks.len(),
            failed_joins: state.failed_joins,
        })
    }

    // Every suspension leaves all handles inside self. Multiple drain callers
    // only observe/join the same owner; none receives the ability to abort work.
    async fn drain_until(&self, deadline: Instant) -> Result<EffectTaskSnapshot, &'static str> {
        loop {
            let snapshot = self.close()?;
            if snapshot.remaining == 0 || Instant::now() >= deadline {
                return Ok(snapshot);
            }
            let next_poll = std::cmp::min(deadline, Instant::now() + Duration::from_millis(10));
            tokio::time::sleep_until(next_poll).await;
        }
    }
}

// These methods extend the existing host, not a second execution owner. This
// child module can access the parent's private task table without exposing it.
impl super::AgentdAutomationEffectHost {
    pub(crate) fn begin_effect_shutdown(&self) -> Result<(), crate::AgentdError> {
        self.effect_tasks.close().map(|_| ()).map_err(|error| {
            crate::AgentdError::Protocol(format!("close effect admission: {error}"))
        })
    }

    pub(crate) async fn drain_owned_effects(
        &self,
        deadline: Instant,
    ) -> Result<(), crate::AgentdError> {
        let snapshot = self
            .effect_tasks
            .drain_until(deadline)
            .await
            .map_err(|error| {
                crate::AgentdError::Protocol(format!("drain effect task owner: {error}"))
            })?;
        if snapshot.remaining != 0 || snapshot.failed_joins != 0 {
            return Err(crate::AgentdError::Protocol(format!(
                "effect shutdown: {} unjoined task(s), {} failed join(s); durable attempt recovery is required; no absence or retry authority granted",
                snapshot.remaining, snapshot.failed_joins,
            )));
        }
        // This is task ownership closure, not provider-terminal-success evidence.
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;
    use tokio::sync::Notify;

    #[tokio::test]
    async fn cancelled_waiter_does_not_release_inflight_capacity() {
        let tasks = EffectTasks::new(1);
        let finish = Arc::new(Notify::new());
        let worker_finish = Arc::clone(&finish);
        let (entered, started) = oneshot::channel();
        let receiver = tasks
            .submit(move || async move {
                let _ = entered.send(());
                worker_finish.notified().await;
                7
            })
            .unwrap();
        started.await.unwrap();
        drop(receiver);
        assert!(tasks.submit(|| async { 8 }).is_err());
        finish.notify_one();
        let mut reused = false;
        for _ in 0..1_000 {
            tokio::task::yield_now().await;
            if let Ok(receiver) = tasks.submit(|| async { 9 }) {
                assert_eq!(receiver.await.unwrap(), 9);
                reused = true;
                break;
            }
        }
        assert!(
            reused,
            "finished task was not joined within the bounded probe"
        );
    }

    #[tokio::test]
    async fn unrelated_runtime_task_progresses_while_effect_waits() {
        let tasks = EffectTasks::new(1);
        let finish = Arc::new(Notify::new());
        let worker_finish = Arc::clone(&finish);
        let receiver = tasks
            .submit(move || async move {
                worker_finish.notified().await;
                1
            })
            .unwrap();
        let progress = tokio::spawn(async { 42 });
        assert_eq!(progress.await.unwrap(), 42);
        finish.notify_one();
        assert_eq!(receiver.await.unwrap(), 1);
    }

    #[tokio::test]
    async fn worker_panic_is_joined_before_capacity_reuse() {
        let tasks = EffectTasks::new(1);
        let result = tasks
            .submit::<(), _>(|| async { panic!("qualification panic") })
            .unwrap();
        assert!(result.await.is_err());
        let mut reused = false;
        for _ in 0..1_000 {
            tokio::task::yield_now().await;
            if let Ok(receiver) = tasks.submit(|| async { 9 }) {
                assert_eq!(receiver.await.unwrap(), 9);
                reused = true;
                break;
            }
        }
        assert!(
            reused,
            "finished task was not joined within the bounded probe"
        );
        let snapshot = tasks
            .drain_until(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap();
        assert_eq!(snapshot.failed_joins, 1);
        assert_eq!(snapshot.remaining, 0);
    }

    #[tokio::test]
    async fn shutdown_rejects_before_constructing_new_effect_work() {
        let tasks = EffectTasks::new(1);
        assert_eq!(tasks.close().unwrap().remaining, 0);
        let calls = AtomicUsize::new(0);
        assert!(
            tasks
                .submit(|| {
                    calls.fetch_add(1, Ordering::SeqCst);
                    async { 1 }
                })
                .is_err()
        );
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn shutdown_timeout_keeps_unjoined_tasks_owned() {
        let tasks = EffectTasks::new(1);
        let finish = Arc::new(Notify::new());
        let worker_finish = Arc::clone(&finish);
        let (entered, started) = oneshot::channel();
        let result = tasks
            .submit(move || async move {
                entered.send(()).unwrap();
                worker_finish.notified().await;
                73
            })
            .unwrap();
        started.await.unwrap();
        let snapshot = tasks.drain_until(Instant::now()).await.unwrap();
        assert_eq!(snapshot.remaining, 1);
        assert!(tasks.submit(|| async { 8 }).is_err());
        finish.notify_one();
        assert_eq!(result.await.unwrap(), 73);
        let snapshot = tasks
            .drain_until(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap();
        assert_eq!(
            snapshot,
            EffectTaskSnapshot {
                remaining: 0,
                failed_joins: 0
            }
        );
        assert!(tasks.submit(|| async { 8 }).is_err());
    }

    #[tokio::test]
    async fn cancelling_drain_does_not_abort_or_detach_the_effect_owner() {
        let tasks = EffectTasks::new(1);
        let finish = Arc::new(Notify::new());
        let worker_finish = Arc::clone(&finish);
        let result = tasks
            .submit(move || async move {
                worker_finish.notified().await;
                91
            })
            .unwrap();
        assert!(
            tokio::time::timeout(
                Duration::from_millis(1),
                tasks.drain_until(Instant::now() + Duration::from_secs(60)),
            )
            .await
            .is_err()
        );
        assert_eq!(tasks.close().unwrap().remaining, 1);
        finish.notify_one();
        assert_eq!(result.await.unwrap(), 91);
        assert_eq!(
            tasks
                .drain_until(Instant::now() + Duration::from_secs(2))
                .await
                .unwrap()
                .remaining,
            0
        );
    }

    #[tokio::test]
    async fn racing_submit_and_close_never_admits_after_the_close_cut() {
        let tasks = Arc::new(EffectTasks::new(16));
        let closed = Arc::new(Notify::new());
        let owner = Arc::clone(&tasks);
        let closed_by_owner = Arc::clone(&closed);
        let closer = tokio::spawn(async move {
            owner.close().unwrap();
            closed_by_owner.notify_one();
        });
        closed.notified().await;
        for _ in 0..32 {
            assert!(tasks.submit(|| async { 1 }).is_err());
        }
        closer.await.unwrap();
    }
}
