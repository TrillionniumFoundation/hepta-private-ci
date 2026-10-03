//! Renderer-neutral ownership of the existing three native worker lanes.
//!
//! A renderer supplies worker completion wakes and consumes joined outcomes.
//! Runtime/recovery calls, readiness witnesses and their authority remain with
//! the retained owners; this controller never synthesizes their success.

use super::shutdown::Shutdown;
use super::task::SupervisedTask;
use super::task::TaskAdmission;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum TaskLane {
    Runtime,
    History,
    Picker,
}

pub(crate) struct PendingTask<K, T> {
    pub(crate) kind: K,
    pub(crate) worker: SupervisedTask<T>,
}

impl<K, T: Send + 'static> PendingTask<K, T> {
    pub(crate) fn spawn<F, W>(kind: K, name: &str, wake: W, work: F) -> std::io::Result<Self>
    where
        F: FnOnce(TaskAdmission) -> T + Send + 'static,
        W: FnOnce() + Send + 'static,
    {
        Ok(Self {
            kind,
            worker: SupervisedTask::spawn(name, wake, work)?,
        })
    }
}

pub(crate) type JoinedTask<T> = Result<T, &'static str>;
type CompletedTask<K, T> = Option<(K, JoinedTask<T>)>;

pub(crate) struct TaskController<K, T> {
    runtime: Option<PendingTask<K, T>>,
    history: Option<PendingTask<K, T>>,
    picker: Option<PendingTask<K, T>>,
}

impl<K, T> Default for TaskController<K, T> {
    fn default() -> Self {
        Self {
            runtime: None,
            history: None,
            picker: None,
        }
    }
}

impl<K: Copy, T: Send + 'static> TaskController<K, T> {
    pub(crate) fn pending(&self, lane: TaskLane) -> Option<&PendingTask<K, T>> {
        match lane {
            TaskLane::Runtime => self.runtime.as_ref(),
            TaskLane::History => self.history.as_ref(),
            TaskLane::Picker => self.picker.as_ref(),
        }
    }

    pub(crate) fn runtime_busy(&self, shutdown: &Shutdown) -> bool {
        self.runtime.is_some() || self.history.is_some() || shutdown.requested()
    }

    pub(crate) fn picker_busy(&self, shutdown: &Shutdown) -> bool {
        self.picker.is_some() || shutdown.requested()
    }

    pub(crate) fn any_active(&self) -> bool {
        self.runtime.is_some() || self.history.is_some() || self.picker.is_some()
    }

    /// Check the lane before invoking the factory: a rejected request starts no
    /// thread and cannot replace an owned worker, even after it has finished.
    pub(crate) fn start(
        &mut self,
        lane: TaskLane,
        shutdown: &Shutdown,
        spawn: impl FnOnce() -> std::io::Result<PendingTask<K, T>>,
    ) -> std::io::Result<()> {
        let busy = match lane {
            TaskLane::Runtime | TaskLane::History => self.runtime_busy(shutdown),
            TaskLane::Picker => self.picker_busy(shutdown),
        };
        if busy {
            return Err(std::io::Error::new(
                std::io::ErrorKind::WouldBlock,
                "native task lane is unavailable",
            ));
        }
        let pending = spawn()?;
        match lane {
            TaskLane::Runtime => self.runtime = Some(pending),
            TaskLane::History => self.history = Some(pending),
            TaskLane::Picker => self.picker = Some(pending),
        }
        Ok(())
    }

    /// Closing is the sole mutation allowed after a shutdown request, and only
    /// after every prior worker has been joined. The caller retains the close
    /// receipt, retry policy and update-activation decision.
    pub(crate) fn start_close(
        &mut self,
        shutdown: &Shutdown,
        spawn: impl FnOnce() -> std::io::Result<PendingTask<K, T>>,
    ) -> std::io::Result<()> {
        if !shutdown.requested()
            || self.any_active()
            || shutdown.close_started
            || shutdown.runtime_closed
        {
            return Err(std::io::Error::new(
                std::io::ErrorKind::WouldBlock,
                "native close must wait for the owned workers",
            ));
        }
        self.runtime = Some(spawn()?);
        Ok(())
    }

    pub(crate) fn cancel_waiting(&self) {
        for task in [
            self.runtime.as_ref(),
            self.history.as_ref(),
            self.picker.as_ref(),
        ]
        .into_iter()
        .flatten()
        {
            task.worker.cancel_before_admission();
        }
    }

    /// Preserve runtime/history/picker order and clear completed slots before
    /// the renderer applies any outcomes. Unfinished workers remain owned.
    pub(crate) fn poll(&mut self) -> [CompletedTask<K, T>; 3] {
        fn poll_slot<K: Copy, T: Send + 'static>(
            slot: &mut Option<PendingTask<K, T>>,
        ) -> CompletedTask<K, T> {
            let task = slot.as_mut()?;
            let kind = task.kind;
            let outcome = task.worker.poll()?;
            *slot = None;
            Some((kind, outcome))
        }
        [
            poll_slot(&mut self.runtime),
            poll_slot(&mut self.history),
            poll_slot(&mut self.picker),
        ]
    }
}

#[cfg(test)]
#[path = "controller_tests.rs"]
mod tests;
