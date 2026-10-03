//! One owned UI worker and a linearized, local cancellation boundary.
//!
//! This admission is NOT a final-use grant. A task becomes non-cancellable just
//! before calling its runtime owner. Once admitted it must finish the owner's
//! durable protocol; a shutdown timeout never detaches or replays that task.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::TryLockError;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;
use std::time::Duration;
use std::time::Instant;

const WAITING: u8 = 0;
const ADMITTED: u8 = 1;
const CANCELLED: u8 = 2;

#[derive(Clone)]
pub(crate) struct TaskAdmission(Arc<AtomicU8>);

impl TaskAdmission {
    /// Linearization point between cancellation and entry into a runtime owner.
    pub(crate) fn begin(&self) -> Result<(), &'static str> {
        match self
            .0
            .compare_exchange(WAITING, ADMITTED, Ordering::AcqRel, Ordering::Acquire)
        {
            Ok(_) => Ok(()),
            Err(CANCELLED) => Err("native task cancelled before runtime admission"),
            Err(_) => Err("native task admission may only be consumed once"),
        }
    }

    /// Taking the mutex is not admission: the caller must still consume begin().
    /// A cancelled or timed-out waiter never enters the runtime owner.
    pub(crate) fn wait_lock<'a, T>(
        &self,
        mutex: &'a Mutex<T>,
        maximum: Duration,
    ) -> Result<MutexGuard<'a, T>, &'static str> {
        let started = Instant::now();
        loop {
            match self.0.load(Ordering::Acquire) {
                WAITING => {}
                CANCELLED => return Err("native task cancelled before runtime admission"),
                _ => return Err("cannot wait for an owner after runtime admission"),
            }
            if started.elapsed() >= maximum {
                return Err("native runtime lock deadline exceeded before admission");
            }
            match mutex.try_lock() {
                Ok(guard) => return Ok(guard),
                Err(TryLockError::Poisoned(_)) => {
                    return Err("native runtime worker lock is poisoned");
                }
                Err(TryLockError::WouldBlock) => {
                    std::thread::sleep(
                        Duration::from_millis(2).min(maximum.saturating_sub(started.elapsed())),
                    );
                }
            }
        }
    }

    fn cancel(&self) -> bool {
        // An admitted operation is deliberately not interrupted.
        self.0
            .compare_exchange(WAITING, CANCELLED, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
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

    /// Returns true only when this call wins before the runtime admission point.
    pub(crate) fn cancel_before_admission(&self) -> bool {
        self.admission.cancel()
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
#[path = "task_tests.rs"]
mod tests;
