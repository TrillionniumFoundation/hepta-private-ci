//! Scheduling-only observation for the actual local S read. The hook accepts
//! no receipt, context, counter or deadline and returns no replacement result.
//! It pauses only after the concrete original owner read has really returned.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

use tokio::sync::Notify;

use super::OriginalCircuitSelectionLocalReadbackV1;

#[derive(Default)]
pub(super) struct State {
    next: Mutex<Option<Operation>>,
}

struct Signals {
    actual_read_returned: AtomicBool,
    operation_finished: AtomicBool,
    pause_expired: AtomicBool,
    changed: Notify,
    end: Instant,
}

pub(super) struct Operation {
    signals: Arc<Signals>,
    release: mpsc::Receiver<()>,
}

impl Drop for Operation {
    fn drop(&mut self) {
        // This runs at the actual blocking closure's exit, including an owner
        // error before the pause. No original owner I/O follows this point.
        self.signals
            .operation_finished
            .store(true, Ordering::Release);
        self.signals.changed.notify_one();
    }
}

pub(crate) struct OriginalSelectionReadGate {
    signals: Arc<Signals>,
    release: Option<mpsc::Sender<()>>,
}

impl OriginalSelectionReadGate {
    pub(crate) async fn wait_for_actual_read(&self) -> anyhow::Result<()> {
        loop {
            if self.signals.actual_read_returned.load(Ordering::Acquire) {
                return Ok(());
            }
            anyhow::ensure!(
                !self.signals.operation_finished.load(Ordering::Acquire),
                "the actual original S operation failed before its completion pause"
            );
            tokio::time::timeout_at(
                tokio::time::Instant::from_std(self.signals.end),
                self.signals.changed.notified(),
            )
            .await
            .map_err(|_| anyhow::anyhow!("actual S completion observation deadline"))?;
        }
    }

    pub(crate) fn release(&mut self) {
        if let Some(release) = self.release.take() {
            let _ = release.send(());
        }
    }

    pub(crate) async fn wait_for_operation_terminal(&self) -> anyhow::Result<()> {
        while !self.signals.operation_finished.load(Ordering::Acquire) {
            tokio::time::timeout_at(
                tokio::time::Instant::from_std(self.signals.end),
                self.signals.changed.notified(),
            )
            .await
            .map_err(|_| anyhow::anyhow!("actual S operation terminal was not observed"))?;
        }
        anyhow::ensure!(
            !self.signals.pause_expired.load(Ordering::Acquire),
            "the test did not release the original S operation within its fixed fixture window"
        );
        Ok(())
    }
}

impl Drop for OriginalSelectionReadGate {
    fn drop(&mut self) {
        self.release();
    }
}

impl OriginalCircuitSelectionLocalReadbackV1 {
    pub(crate) fn fixture_pause_next_original_selection_read(
        &self,
    ) -> anyhow::Result<OriginalSelectionReadGate> {
        let mut next = self
            .original
            .fixture
            .next
            .lock()
            .map_err(|_| anyhow::anyhow!("original S observation slot poisoned"))?;
        anyhow::ensure!(next.is_none(), "one armed original S observation");
        let (release, waiting) = mpsc::channel();
        let signals = Arc::new(Signals {
            actual_read_returned: AtomicBool::new(false),
            operation_finished: AtomicBool::new(false),
            pause_expired: AtomicBool::new(false),
            changed: Notify::new(),
            end: Instant::now()
                .checked_add(Duration::from_secs(5))
                .ok_or_else(|| anyhow::anyhow!("bounded original S observation"))?,
        });
        *next = Some(Operation {
            signals: Arc::clone(&signals),
            release: waiting,
        });
        Ok(OriginalSelectionReadGate {
            signals,
            release: Some(release),
        })
    }
}

pub(super) fn take_next(state: &State) -> Option<Operation> {
    // A poisoned test observation cannot produce a fake owner result. The
    // owning test will not observe a pause and must fail its bounded wait.
    state.next.lock().ok()?.take()
}

pub(super) fn after_actual_read(operation: &Option<Operation>, original_deadline: Instant) {
    let Some(operation) = operation else {
        return;
    };
    operation
        .signals
        .actual_read_returned
        .store(true, Ordering::Release);
    operation.signals.changed.notify_one();
    // The pause cannot run beyond this actual operation's original deadline.
    let remaining = original_deadline.saturating_duration_since(Instant::now());
    if operation.release.recv_timeout(remaining).is_err() {
        operation
            .signals
            .pause_expired
            .store(true, Ordering::Release);
    }
}
