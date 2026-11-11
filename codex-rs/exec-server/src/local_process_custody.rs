use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_exec_server_protocol::JSONRPCErrorError;
use codex_utils_pty::ExecCommandSession;
use tokio::sync::Notify;
use tokio::sync::watch;

use super::Inner;
use crate::ExecProcessEvent;
use crate::process::ExecProcessEventLog;
use crate::rpc::internal_error;

pub(super) const UNKNOWN_OUTCOME: &str = "process exit observation lost";

/// Shared by every session of one server, including detached and expired sessions.
/// An unknown process is retained in place; a new connection cannot clear the fence.
#[derive(Default)]
pub(crate) struct ProcessCustodyRegistry {
    state: Mutex<RegistryState>,
}

#[derive(Default)]
struct RegistryState {
    next_id: u64,
    poisoned: bool,
    entries: BTreeMap<u64, RegistryEntry>,
    unclassified: Vec<Arc<ExecCommandSession>>,
}

struct RegistryEntry {
    custody: Arc<ProcessCustody>,
    unknown: bool,
}

pub(super) struct ProcessCustody {
    id: u64,
    // Retain the original process map and output state across session expiration.
    // The cycle is released only after an actual exit observation.
    inner: Arc<Inner>,
    owner: OnceLock<Arc<ExecCommandSession>>,
    observed_native_exit: OnceLock<i32>,
    unknown_outcome: AtomicBool,
    observation: OnceLock<ObservationWake>,
}

struct ObservationWake {
    wake_tx: watch::Sender<u64>,
    output_notify: Arc<Notify>,
    events: ExecProcessEventLog,
    published: AtomicBool,
}

pub(super) struct ProcessLaunch {
    custody: Arc<ProcessCustody>,
    effect_started: bool,
    handed_off: bool,
}

impl ProcessCustodyRegistry {
    pub(super) fn reserve(
        self: &Arc<Self>,
        inner: Arc<Inner>,
    ) -> Result<ProcessLaunch, JSONRPCErrorError> {
        let mut state = match self.state.lock() {
            Ok(state) => state,
            Err(mut poisoned) => {
                poisoned.get_mut().poisoned = true;
                return Err(internal_error(
                    "process custody registry is poisoned".to_string(),
                ));
            }
        };
        if state.poisoned || state.entries.values().any(|entry| entry.unknown) {
            return Err(internal_error(
                "a prior process outcome is unknown; new process admission is fenced".to_string(),
            ));
        }
        let id = state.next_id.checked_add(1).ok_or_else(|| {
            internal_error("process custody identity space exhausted".to_string())
        })?;
        state.next_id = id;
        let custody = Arc::new(ProcessCustody {
            id,
            inner,
            owner: OnceLock::new(),
            observed_native_exit: OnceLock::new(),
            unknown_outcome: AtomicBool::new(false),
            observation: OnceLock::new(),
        });
        state.entries.insert(
            id,
            RegistryEntry {
                custody: Arc::clone(&custody),
                unknown: false,
            },
        );
        Ok(ProcessLaunch {
            custody,
            effect_started: false,
            handed_off: false,
        })
    }
}

impl ProcessCustody {
    pub(super) fn attach_observation(
        self: &Arc<Self>,
        wake_tx: watch::Sender<u64>,
        output_notify: Arc<Notify>,
        events: ExecProcessEventLog,
    ) -> Result<(), JSONRPCErrorError> {
        if self
            .observation
            .set(ObservationWake {
                wake_tx,
                output_notify,
                events,
                published: AtomicBool::new(false),
            })
            .is_err()
        {
            self.mark_unknown();
            return Err(internal_error(
                "process observation was already attached".to_string(),
            ));
        }
        self.wake_unknown();
        Ok(())
    }

    pub(super) fn outcome_is_unknown(&self) -> bool {
        self.unknown_outcome.load(Ordering::SeqCst)
    }

    pub(super) fn observed_exit_code(&self) -> Option<i32> {
        self.observed_native_exit.get().copied()
    }

    fn wake_unknown(&self) {
        if !self.outcome_is_unknown() {
            return;
        }
        if let Some(observation) = self.observation.get()
            && !observation.published.swap(true, Ordering::SeqCst)
        {
            observation
                .events
                .publish(ExecProcessEvent::Failed(UNKNOWN_OUTCOME.to_string()));
            observation
                .wake_tx
                .send_modify(|value| *value = value.saturating_add(1));
            observation.output_notify.notify_waiters();
        }
    }

    pub(super) fn attach_owner(
        self: &Arc<Self>,
        owner: Arc<ExecCommandSession>,
    ) -> Result<(), JSONRPCErrorError> {
        if let Err(owner) = self.owner.set(owner) {
            // Do not drop an unexpected second native owner on an invariant error.
            let registry = &self.inner.custody;
            let mut state = registry
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.poisoned = true;
            state.unclassified.push(owner);
            return Err(internal_error(
                "process cleanup owner was already attached".to_string(),
            ));
        }
        Ok(())
    }

    pub(super) fn mark_unknown(self: &Arc<Self>) {
        let registry = &self.inner.custody;
        let mut state = match registry.state.lock() {
            Ok(state) => state,
            Err(error) => {
                let mut state = error.into_inner();
                state.poisoned = true;
                state
            }
        };
        if self.observed_exit_code().is_some() {
            return;
        }
        match state.entries.get_mut(&self.id) {
            Some(entry) if Arc::ptr_eq(&entry.custody, self) => entry.unknown = true,
            _ => state.poisoned = true,
        }
        self.unknown_outcome.store(true, Ordering::SeqCst);
        drop(state);
        // This also covers a watcher cancelled before its first poll. Reading
        // the same process must report unknown without relying on that task.
        self.wake_unknown();
    }

    pub(super) fn observe_native_exit(self: &Arc<Self>, exit_code: i32) {
        let registry = &self.inner.custody;
        let mut state = match registry.state.lock() {
            Ok(state) => state,
            Err(error) => {
                let mut state = error.into_inner();
                state.poisoned = true;
                state
            }
        };
        if self.observed_native_exit.set(exit_code).is_err()
            && self.observed_exit_code() != Some(exit_code)
        {
            state.poisoned = true;
            return;
        }
        // Preserve the actual observation before releasing custody or crossing
        // any asynchronous publication/map lock. A cancelled publisher cannot
        // turn this same process back into an unobserved running process.
        if state
            .entries
            .get(&self.id)
            .is_some_and(|entry| Arc::ptr_eq(&entry.custody, self))
        {
            state.entries.remove(&self.id);
        }
        drop(state);
        if let Some(observation) = self.observation.get() {
            observation
                .wake_tx
                .send_modify(|value| *value = value.saturating_add(1));
            observation.output_notify.notify_waiters();
        }
    }

    fn release_exact_slot(self: &Arc<Self>) {
        let registry = &self.inner.custody;
        let mut state = match registry.state.lock() {
            Ok(state) => state,
            Err(error) => {
                let mut state = error.into_inner();
                state.poisoned = true;
                state
            }
        };
        if state
            .entries
            .get(&self.id)
            .is_some_and(|entry| Arc::ptr_eq(&entry.custody, self))
        {
            state.entries.remove(&self.id);
        }
    }

    pub(super) fn request_cleanup(&self) {
        if self.observed_exit_code().is_none()
            && let Some(owner) = self.owner.get()
        {
            owner.request_terminate();
        }
    }
}

impl ProcessLaunch {
    pub(super) fn custody(&self) -> Arc<ProcessCustody> {
        Arc::clone(&self.custody)
    }

    pub(super) fn begin_effect(&mut self) {
        self.effect_started = true;
    }

    pub(super) fn confirm_native_exit(mut self, exit_code: i32) {
        self.custody.observe_native_exit(exit_code);
        self.handed_off = true;
    }
}

impl Drop for ProcessLaunch {
    fn drop(&mut self) {
        if self.handed_off {
            return;
        }
        if self.effect_started {
            // This covers cancellation/panic while awaiting a backend or map lock.
            // A bare backend error is not evidence that no child was created.
            self.custody.mark_unknown();
            self.custody.request_cleanup();
        } else {
            self.custody.release_exact_slot();
        }
    }
}
