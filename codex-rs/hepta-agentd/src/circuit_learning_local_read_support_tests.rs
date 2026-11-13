//! Test-only observation of an actual local owner response.
//! The gate cannot supply or change a response, counter, permit or deadline.
//! Release/Drop only stops the pause; callers still await the original worker
//! terminal observation and the original fixture peer joins.

use std::sync::Condvar;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use super::*;

pub(super) struct OriginalLocalReadProbeState {
    submitted: AtomicBool,
    started: AtomicBool,
    response_observed: AtomicBool,
    terminal: AtomicBool,
    released: Mutex<bool>,
    changed: Condvar,
    response_notify: tokio::sync::Notify,
    terminal_notify: tokio::sync::Notify,
}

pub(crate) struct OriginalLocalReadProbe {
    state: Arc<OriginalLocalReadProbeState>,
}

pub(super) struct OriginalLocalReadTerminal {
    state: Arc<OriginalLocalReadProbeState>,
}

impl OriginalLocalReadTerminal {
    pub(super) fn mark_original_started(&self) {
        self.state.started.store(true, Ordering::Release);
    }

    pub(super) fn pause_after_original_response(&self, deadline: Instant) -> Result<(), Error> {
        self.state.response_observed.store(true, Ordering::Release);
        self.state.response_notify.notify_one();
        let mut released = self.state.released.lock().map_err(|_| Error::Unavailable)?;
        while !*released {
            let remaining = deadline
                .checked_duration_since(Instant::now())
                .ok_or(Error::Unavailable)?;
            let (current, _) = self
                .state
                .changed
                .wait_timeout(released, remaining)
                .map_err(|_| Error::Unavailable)?;
            released = current;
        }
        if Instant::now() >= deadline {
            return Err(Error::Unavailable);
        }
        Ok(())
    }
}

impl Drop for OriginalLocalReadTerminal {
    fn drop(&mut self) {
        self.state.terminal.store(true, Ordering::Release);
        self.state.terminal_notify.notify_one();
    }
}

impl OriginalLocalReadProbe {
    pub(crate) async fn wait_after_original_response(&self) {
        loop {
            let notified = self.state.response_notify.notified();
            if self.state.response_observed.load(Ordering::Acquire) {
                return;
            }
            notified.await;
        }
    }

    pub(crate) async fn wait_original_terminal(&self) {
        loop {
            let notified = self.state.terminal_notify.notified();
            if self.state.terminal.load(Ordering::Acquire) {
                return;
            }
            notified.await;
        }
    }

    pub(crate) fn original_submitted(&self) -> bool {
        self.state.submitted.load(Ordering::Acquire)
    }

    pub(crate) fn original_started(&self) -> bool {
        self.state.started.load(Ordering::Acquire)
    }

    pub(crate) fn original_response_observed(&self) -> bool {
        self.state.response_observed.load(Ordering::Acquire)
    }

    pub(crate) fn release(&self) {
        if let Ok(mut released) = self.state.released.lock() {
            *released = true;
            self.state.changed.notify_all();
        }
    }
}

impl Drop for OriginalLocalReadProbe {
    fn drop(&mut self) {
        self.release();
    }
}

impl OriginalLocalReadState {
    pub(super) fn fixture_original_read_submitted(
        &self,
    ) -> Result<Option<OriginalLocalReadTerminal>, Error> {
        let probe = self
            .probe
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .clone();
        Ok(probe.map(|state| {
            state.submitted.store(true, Ordering::Release);
            OriginalLocalReadTerminal { state }
        }))
    }
}

impl OriginalCircuitPublishedLocalReadV1 {
    pub(crate) fn fixture_pause_after_original_response(
        &self,
    ) -> Result<OriginalLocalReadProbe, Error> {
        let slot = self
            .original
            .slot
            .try_lock()
            .map_err(|_| Error::Unavailable)?;
        if slot.as_ref().map(|slot| slot.next_request_id) != Some(1) {
            return Err(Error::Binding(
                "install probe before the first actual local read",
            ));
        }
        let mut probe = self
            .original
            .probe
            .try_lock()
            .map_err(|_| Error::Unavailable)?;
        if probe.is_some() {
            return Err(Error::Unavailable);
        }
        let state = Arc::new(OriginalLocalReadProbeState {
            submitted: AtomicBool::new(false),
            started: AtomicBool::new(false),
            response_observed: AtomicBool::new(false),
            terminal: AtomicBool::new(false),
            released: Mutex::new(false),
            changed: Condvar::new(),
            response_notify: tokio::sync::Notify::new(),
            terminal_notify: tokio::sync::Notify::new(),
        });
        *probe = Some(Arc::clone(&state));
        Ok(OriginalLocalReadProbe { state })
    }

    pub(crate) fn fixture_next_request_id(&self) -> Result<Option<u64>, Error> {
        Ok(self
            .original
            .slot
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .as_ref()
            .map(|slot| slot.next_request_id))
    }

    pub(crate) fn fixture_shares_budget(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.original, &other.original)
    }
}
