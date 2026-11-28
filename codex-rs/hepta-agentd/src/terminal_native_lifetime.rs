//! Lifetime of the existing single native compute permit. Cancellation closes
//! admission; a permit retained by real blocking work remains a drain blocker.
//! This does not interrupt an atomic fit which has already passed its entry gate.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;

use tokio::sync::OwnedSemaphorePermit;
use tokio::sync::Semaphore;
use tokio_util::sync::CancellationToken;

use crate::TerminalLearningErrorV1;

pub(crate) struct TerminalNativeLifetimeV1 {
    compute: Arc<Semaphore>,
    runtime_cancellation: OnceLock<CancellationToken>,
    entry: Mutex<NativeEntry>,
    #[cfg(test)]
    pub(crate) before_fit: std::sync::Mutex<Option<Box<dyn FnOnce() + Send>>>,
    #[cfg(test)]
    pub(crate) fit_calls: std::sync::atomic::AtomicUsize,
    #[cfg(test)]
    pub(crate) blocker_checks: std::sync::atomic::AtomicUsize,
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum NativePhase {
    Idle,
    Pending,
    Running,
}

struct NativeEntry {
    closed: bool,
    phase: NativePhase,
}

impl TerminalNativeLifetimeV1 {
    pub(super) fn new(compute: Arc<Semaphore>) -> Self {
        Self {
            compute,
            runtime_cancellation: OnceLock::new(),
            entry: Mutex::new(NativeEntry {
                closed: false,
                phase: NativePhase::Idle,
            }),
            #[cfg(test)]
            before_fit: std::sync::Mutex::new(/*t*/ None),
            #[cfg(test)]
            fit_calls: std::sync::atomic::AtomicUsize::new(/*v*/ 0),
            #[cfg(test)]
            blocker_checks: std::sync::atomic::AtomicUsize::new(/*v*/ 0),
        }
    }

    /// Called once by the original supervised bootstrap. An independent owner
    /// without this binding does not acquire a runtime shutdown acknowledgement.
    pub(crate) fn bind_terminal_native_runtime(
        self: &Arc<Self>,
        cancellation: CancellationToken,
    ) -> Result<TerminalNativeRuntimeGuardV1, TerminalLearningErrorV1> {
        self.runtime_cancellation
            .set(cancellation)
            .map_err(|_| TerminalLearningErrorV1::WrongScope)?;
        Ok(TerminalNativeRuntimeGuardV1(Arc::clone(self)))
    }

    pub(crate) fn close(&self) {
        // close and Pending -> Running are serialized. The entry lock never
        // covers the fit. Poison also closes the underlying admission boundary.
        if let Ok(mut entry) = self.entry.lock() {
            entry.closed = true;
        }
        self.compute.close();
    }

    pub(crate) fn blockers(&self) -> u32 {
        #[cfg(test)]
        self.blocker_checks
            .fetch_add(/*val*/ 1, std::sync::atomic::Ordering::SeqCst);
        u32::from(self.compute.available_permits() == 0)
    }

    pub(crate) fn require_fit_open(&self) -> Result<(), TerminalLearningErrorV1> {
        let entry = self
            .entry
            .lock()
            .map_err(|_| TerminalLearningErrorV1::CommitUncertain)?;
        if entry.closed
            || self.compute.is_closed()
            || self
                .runtime_cancellation
                .get()
                .is_some_and(CancellationToken::is_cancelled)
        {
            return Err(TerminalLearningErrorV1::CommitUncertain);
        }
        Ok(())
    }

    pub(super) fn claim_terminal_native_work(
        self: &Arc<Self>,
        permit: OwnedSemaphorePermit,
    ) -> Result<TerminalNativeWorkGuardV1, TerminalLearningErrorV1> {
        let mut entry = self
            .entry
            .lock()
            .map_err(|_| TerminalLearningErrorV1::CommitUncertain)?;
        if entry.closed || entry.phase != NativePhase::Idle {
            return Err(TerminalLearningErrorV1::CommitUncertain);
        }
        entry.phase = NativePhase::Pending;
        Ok(TerminalNativeWorkGuardV1 {
            lifetime: Arc::clone(self),
            _permit: permit,
        })
    }
}

/// Retains the exact original permit, not a second pool or an async-side count.
pub(super) struct TerminalNativeWorkGuardV1 {
    pub(super) lifetime: Arc<TerminalNativeLifetimeV1>,
    _permit: OwnedSemaphorePermit,
}

impl TerminalNativeWorkGuardV1 {
    pub(super) fn begin_terminal_native_fit(&self) -> Result<(), TerminalLearningErrorV1> {
        let mut entry = self
            .lifetime
            .entry
            .lock()
            .map_err(|_| TerminalLearningErrorV1::CommitUncertain)?;
        if entry.closed
            || entry.phase != NativePhase::Pending
            || self
                .lifetime
                .runtime_cancellation
                .get()
                .is_some_and(CancellationToken::is_cancelled)
        {
            return Err(TerminalLearningErrorV1::CommitUncertain);
        }
        // This is the fit-entry linearization point. A later close cannot undo
        // this admitted atomic work; the real permit continues to block drain.
        entry.phase = NativePhase::Running;
        Ok(())
    }
}

impl Drop for TerminalNativeWorkGuardV1 {
    fn drop(&mut self) {
        if let Ok(mut entry) = self.lifetime.entry.lock() {
            entry.phase = NativePhase::Idle;
        }
        // Rust drops _permit after this method, after the real worker scope.
    }
}

pub(crate) struct TerminalNativeRuntimeGuardV1(Arc<TerminalNativeLifetimeV1>);

impl Drop for TerminalNativeRuntimeGuardV1 {
    fn drop(&mut self) {
        self.0.close();
    }
}
