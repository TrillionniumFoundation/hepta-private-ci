//! Bounded task ownership on the existing Agentd Tokio runtime.
//!
//! Dropping a response receiver cancels waiting, not the owned effect task.
//! Finished handles are joined before admission recovers capacity. This table
//! is not another effect ledger: crash recovery belongs to AutomationStore.

use std::future::Future;
use std::sync::Mutex;

use tokio::runtime::Handle;
use tokio::sync::oneshot;
use tokio::task::JoinSet;

pub(super) struct EffectTasks {
    tasks: Mutex<JoinSet<()>>,
    capacity: usize,
}

impl EffectTasks {
    pub(super) fn new(capacity: usize) -> Self {
        Self {
            tasks: Mutex::new(JoinSet::new()),
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
        let mut tasks = self.tasks.lock().map_err(|_| "effect task owner is poisoned")?;
        while tasks.try_join_next().is_some() {}
        if tasks.len() >= self.capacity {
            return Err("effect task capacity exhausted; no new effect was admitted");
        }
        let (sender, receiver) = oneshot::channel();
        let future = make();
        tasks.spawn_on(
            async move {
                let result = future.await;
                // A cancelled client does not cancel owner persistence/reconciliation.
                let _ = sender.send(result);
            },
            &runtime,
        );
        Ok(receiver)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
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
        assert!(reused, "finished task was not joined within the bounded probe");
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
        let result = tasks.submit::<(), _>(|| async { panic!("qualification panic") }).unwrap();
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
        assert!(reused, "finished task was not joined within the bounded probe");
    }
}
