use std::collections::HashMap;
use std::collections::hash_map::Entry;
use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::OnceLock;

use codex_app_server_protocol::JSONRPCErrorError;
use codex_utils_pty::ProcessHandle;
use tokio::sync::mpsc;

use super::manager::ProcessControlRequest;
use crate::error_code::internal_error;
use crate::error_code::invalid_request;
use crate::outgoing_message::ConnectionId;

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub(super) struct ConnectionProcessHandle {
    pub(super) connection_id: ConnectionId,
    pub(super) process_handle: String,
}

/// The original process object stays owned here until a real exit is observed.
/// Connection closure and lost control/exit channels are not exit evidence.
pub(super) struct ProcessRegistration {
    pub(super) key: ConnectionProcessHandle,
    pub(super) control_tx: mpsc::Sender<ProcessControlRequest>,
    pub(super) owner: OnceLock<Arc<ProcessHandle>>,
}

struct ProcessEntry {
    registration: Arc<ProcessRegistration>,
    indeterminate: bool,
    cleanup_requested: bool,
}

#[derive(Default)]
struct RegistryState {
    // This fence covers this server instance, including future connections.
    // It has no implicit reset and is not a durable cross-restart fence.
    spawn_fenced: bool,
    entries: HashMap<ConnectionProcessHandle, ProcessEntry>,
}

#[derive(Default)]
pub(super) struct ProcessRegistry {
    // All critical sections are synchronous and contain no await or owner callbacks.
    state: Mutex<RegistryState>,
}

enum RegistrationObservation {
    Pending,
    Unknown,
    ExitObserved,
}

/// Covers admission, native spawn, response delivery, and the original worker.
/// Dropping a pending future cannot silently abandon its reservation or owner.
pub(super) struct ProcessRegistrationGuard {
    registry: Arc<ProcessRegistry>,
    registration: Arc<ProcessRegistration>,
    observation: RegistrationObservation,
}

impl ProcessRegistrationGuard {
    pub(super) fn registration(&self) -> &Arc<ProcessRegistration> {
        &self.registration
    }

    pub(super) fn observed_exit(&mut self) {
        self.observation = RegistrationObservation::ExitObserved;
    }

    pub(super) fn observation_lost(&mut self) {
        self.registry.observation_lost(&self.registration);
        self.observation = RegistrationObservation::Unknown;
    }
}

impl Drop for ProcessRegistrationGuard {
    fn drop(&mut self) {
        match self.observation {
            RegistrationObservation::Pending => {
                self.registry.observation_lost(&self.registration);
            }
            RegistrationObservation::Unknown => {}
            RegistrationObservation::ExitObserved => {
                self.registry.observed_exit(&self.registration);
            }
        }
    }
}

impl ProcessRegistry {
    fn lock_state(&self) -> MutexGuard<'_, RegistryState> {
        match self.state.lock() {
            Ok(state) => state,
            Err(poisoned) => {
                // Recover custody, never permission to spawn/control. Do not discard
                // the map or an owner because a prior critical section panicked.
                let mut state = poisoned.into_inner();
                state.spawn_fenced = true;
                for entry in state.entries.values_mut() {
                    entry.indeterminate = true;
                }
                state
            }
        }
    }

    pub(super) fn admit(
        self: &Arc<Self>,
        key: ConnectionProcessHandle,
        control_tx: mpsc::Sender<ProcessControlRequest>,
    ) -> Result<ProcessRegistrationGuard, JSONRPCErrorError> {
        let mut state = self.lock_state();
        if state.spawn_fenced {
            return Err(internal_error(
                "process/spawn is fenced: a process exit observation was lost; the original owner requires reconciliation",
            ));
        }
        match state.entries.entry(key.clone()) {
            Entry::Occupied(_) => Err(invalid_request(format!(
                "duplicate active process handle: {:?}",
                key.process_handle,
            ))),
            Entry::Vacant(entry) => {
                let registration = Arc::new(ProcessRegistration {
                    key,
                    control_tx,
                    owner: OnceLock::new(),
                });
                entry.insert(ProcessEntry {
                    registration: Arc::clone(&registration),
                    indeterminate: false,
                    cleanup_requested: false,
                });
                Ok(ProcessRegistrationGuard {
                    registry: Arc::clone(self),
                    registration,
                    observation: RegistrationObservation::Pending,
                })
            }
        }
    }

    fn observed_exit(&self, registration: &Arc<ProcessRegistration>) {
        let mut state = self.lock_state();
        if state
            .entries
            .get(&registration.key)
            .is_some_and(|entry| Arc::ptr_eq(&entry.registration, registration))
        {
            state.entries.remove(&registration.key);
        }
    }

    pub(super) fn observation_lost(&self, registration: &Arc<ProcessRegistration>) {
        let request_cleanup = {
            let mut state = self.lock_state();
            if let Some(entry) = state.entries.get_mut(&registration.key)
                && Arc::ptr_eq(&entry.registration, registration)
            {
                let request_cleanup =
                    !entry.cleanup_requested && registration.owner.get().is_some();
                entry.cleanup_requested |= request_cleanup;
                entry.indeterminate = true;
                state.spawn_fenced = true;
                request_cleanup
            } else {
                false
            }
        };
        if request_cleanup && let Some(owner) = registration.owner.get() {
            // Request cleanup on the same retained object; this is not proof of
            // delivery or exit. A callback panic must not unwind a Drop guard.
            if std::panic::catch_unwind(AssertUnwindSafe(|| owner.request_terminate())).is_err() {
                tracing::error!(
                    "process cleanup callback panicked; original owner remains unknown"
                );
            }
        }
    }

    pub(super) fn active(
        &self,
        key: &ConnectionProcessHandle,
    ) -> Result<Arc<ProcessRegistration>, JSONRPCErrorError> {
        let state = self.lock_state();
        let entry = state.entries.get(key).ok_or_else(|| {
            invalid_request(format!(
                "no active process for process handle {:?}",
                key.process_handle,
            ))
        })?;
        if entry.indeterminate {
            return Err(observation_lost_error(&key.process_handle));
        }
        Ok(Arc::clone(&entry.registration))
    }

    pub(super) fn connection_closed(
        &self,
        connection_id: ConnectionId,
    ) -> Vec<Arc<ProcessRegistration>> {
        // Keep all owners, including unknown owners, in the original registry.
        // A live worker may still observe exit after its connection is gone.
        self.lock_state()
            .entries
            .values()
            .filter(|entry| {
                entry.registration.key.connection_id == connection_id && !entry.indeterminate
            })
            .map(|entry| Arc::clone(&entry.registration))
            .collect()
    }
}

pub(super) fn observation_lost_error(process_handle: &str) -> JSONRPCErrorError {
    internal_error(format!(
        "process {process_handle:?} exit/control observation was lost; the original owner requires reconciliation",
    ))
}

#[cfg(test)]
#[path = "process_exec_registry_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "process_exec_guard_tests.rs"]
mod guard_tests;
