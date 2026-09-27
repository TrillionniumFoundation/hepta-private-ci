//! One owned UI worker and a linearized, local cancellation boundary.
//!
//! This admission is NOT a final-use grant. A task becomes non-cancellable just
//! before calling its runtime owner. Once admitted it must finish the owner's
//! durable protocol; a shutdown timeout never detaches or replays that task.

use std::sync::Arc;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;

const WAITING: u8 = 0;
const ADMITTED: u8 = 1;
const CANCELLED: u8 = 2;

#[derive(Clone)]
pub(crate) struct TaskAdmission(Arc<AtomicU8>);

impl TaskAdmission {
    /// Linearization point between cancellation and entry into a runtime owner.
    pub(crate) fn begin(&self) -> Result<(), &'static str> {
        match self.0.compare_exchange(
            WAITING,
            ADMITTED,
            Ordering::AcqRel,
            Ordering::Acquire,
        ) {
            Ok(_) => Ok(()),
            Err(CANCELLED) => Err("native task cancelled before runtime admission"),
            Err(_) => Err("native task admission may only be consumed once"),
        }
    }

    fn cancel(&self) {
        // An admitted operation is deliberately not interrupted.
        let _ = self.0.compare_exchange(
            WAITING,
            CANCELLED,
            Ordering::AcqRel,
            Ordering::Acquire,
        );
    }
}

pub(crate) struct SupervisedTask<T> {
    handle: Option<JoinHandle<T>>,
    admission: TaskAdmission,
}

impl<T: Send + 'static> SupervisedTask<T> {
    pub(crate) fn spawn<F, W>(name: &str, wake: W, work: F) -> std::io::Result<Self>
    where
        F: FnOnce(TaskAdmission) -> T + Send + 'static,
        W: FnOnce() + Send + 'static,
    {
        let admission = TaskAdmission(Arc::new(AtomicU8::new(WAITING)));
        let worker_admission = admission.clone();
        let handle = std::thread::Builder::new()
            .name(name.to_owned())
            .spawn(move || {
                // Wake on both return and unwind. UI polling additionally keeps a
                // slow watchdog because the wake can precede thread termination.
                struct WakeOnDrop<W: FnOnce()>(Option<W>);
                impl<W: FnOnce()> Drop for WakeOnDrop<W> {
                    fn drop(&mut self) {
                        if let Some(wake) = self.0.take() {
                            wake();
                        }
                    }
                }
                let _wake = WakeOnDrop(Some(wake));
                work(worker_admission)
            })?;
        Ok(Self {
            handle: Some(handle),
            admission,
        })
    }

    pub(crate) fn cancel_before_admission(&self) {
        self.admission.cancel();
    }

    /// Never blocks on an unfinished thread. A completed thread is joined once.
    pub(crate) fn poll(&mut self) -> Option<Result<T, &'static str>> {
        if !self.handle.as_ref()?.is_finished() {
            return None;
        }
        self.handle.take().map(|handle| {
            handle
                .join()
                .map_err(|_| "native worker panicked; completion is not established")
        })
    }
}

#[cfg(test)]
#[path = "task_supervisor_tests.rs"]
mod tests;
