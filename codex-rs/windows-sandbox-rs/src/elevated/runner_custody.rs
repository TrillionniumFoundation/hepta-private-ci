use codex_utils_pty::ProcessCleanupCustody;
use codex_utils_pty::ProcessCleanupObservation;
use std::collections::BTreeMap;
use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::OwnedHandle;
use std::sync::Arc;
use std::sync::LazyLock;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::Weak;
use std::time::Instant;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

static REGISTRY: LazyLock<Arc<RunnerCustodyRegistry>> =
    LazyLock::new(|| Arc::new(RunnerCustodyRegistry::default()));

#[derive(Default)]
pub(super) struct RunnerCustodyRegistry {
    state: Mutex<RegistryState>,
}

#[derive(Default)]
struct RegistryState {
    next_id: u64,
    poisoned: bool,
    slots: BTreeMap<u64, Slot>,
    unclassified: Vec<Arc<RunnerCustody>>,
}

enum Slot {
    Reserved,
    Retained {
        custody: Arc<RunnerCustody>,
        unknown: bool,
    },
}

pub(crate) struct RunnerAdmission {
    registry: Arc<RunnerCustodyRegistry>,
    id: u64,
    attached: bool,
}

#[derive(Clone, Default)]
struct CleanupFacts {
    original_deadline: Option<Instant>,
    first_observation_end: Option<Instant>,
    original_failed: bool,
    cleanup_observation_lost: bool,
    native_exit: Option<u32>,
    observed_late: Option<bool>,
}

/// This process-local registry preserves custody through server/session teardown.
/// It is not a durable ledger and cannot establish custody across process restart.
pub(crate) struct RunnerCustody {
    id: u64,
    handle: Arc<OwnedHandle>,
    registry: Weak<RunnerCustodyRegistry>,
    facts: Mutex<CleanupFacts>,
}

/// Cleanup of an earlier command does not change that command's failure result.
#[derive(Debug)]
pub struct RunnerCleanupReconciliation {
    pub reservation_id: u64,
    pub observation: io::Result<ProcessCleanupObservation>,
    pub original_failed: bool,
    pub cleanup_observation_lost: bool,
    pub observed_after_deadline: Option<bool>,
}

impl RunnerCustodyRegistry {
    fn locked(&self) -> MutexGuard<'_, RegistryState> {
        match self.state.lock() {
            Ok(state) => state,
            Err(poisoned) => {
                let mut state = poisoned.into_inner();
                state.poisoned = true;
                state
            }
        }
    }

    pub(super) fn reserve(self: &Arc<Self>) -> io::Result<RunnerAdmission> {
        let mut state = self.locked();
        if state.poisoned
            || state
                .slots
                .values()
                .any(|slot| matches!(slot, Slot::Retained { unknown: true, .. }))
        {
            return Err(io::Error::other(
                "runner cleanup custody is unresolved; new launch refused",
            ));
        }
        let id = state
            .next_id
            .checked_add(1)
            .ok_or_else(|| io::Error::other("runner custody reservation exhausted"))?;
        state.next_id = id;
        state.slots.insert(id, Slot::Reserved);
        Ok(RunnerAdmission {
            registry: Arc::clone(self),
            id,
            attached: false,
        })
    }

    fn update(&self, custody: &RunnerCustody, terminal: bool) {
        let mut state = self.locked();
        let same = matches!(state.slots.get(&custody.id), Some(Slot::Retained { custody: retained, .. })
            if std::ptr::eq(Arc::as_ref(retained), custody));
        if !same {
            return;
        }
        if terminal {
            state.slots.remove(&custody.id);
        } else if let Some(Slot::Retained { unknown, .. }) = state.slots.get_mut(&custody.id) {
            *unknown = true;
        }
    }

    fn unknown(&self) -> io::Result<Vec<Arc<RunnerCustody>>> {
        let state = self.locked();
        if state.poisoned {
            return Err(io::Error::other("runner custody registry poisoned"));
        }
        Ok(state
            .slots
            .values()
            .filter_map(|slot| match slot {
                Slot::Retained {
                    custody,
                    unknown: true,
                } => Some(Arc::clone(custody)),
                _ => None,
            })
            .collect())
    }

    pub(super) fn reconcile(&self) -> io::Result<Vec<RunnerCleanupReconciliation>> {
        Ok(self
            .unknown()?
            .into_iter()
            .map(|custody| {
                let observation = custody.observe_cleanup();
                let facts = custody.cleanup_facts();
                RunnerCleanupReconciliation {
                    reservation_id: custody.id,
                    observation,
                    original_failed: facts.as_ref().map_or(true, |facts| facts.original_failed),
                    cleanup_observation_lost: facts
                        .as_ref()
                        .map_or(true, |facts| facts.cleanup_observation_lost),
                    observed_after_deadline: facts.ok().and_then(|facts| facts.observed_late),
                }
            })
            .collect())
    }

    #[cfg(test)]
    pub(super) fn retained_count(&self) -> usize {
        let state = self.locked();
        state.slots.len() + state.unclassified.len()
    }
}

impl RunnerAdmission {
    pub(super) fn attach(mut self, handle: Arc<OwnedHandle>) -> Arc<RunnerCustody> {
        let custody = Arc::new(RunnerCustody {
            id: self.id,
            handle,
            registry: Arc::downgrade(&self.registry),
            facts: Mutex::new(CleanupFacts::default()),
        });
        let mut state = self.registry.locked();
        // Only this linear reservation may replace its own Reserved entry.
        if !matches!(state.slots.get(&self.id), Some(Slot::Reserved)) {
            state.poisoned = true;
            // An invariant failure must retain both the previous object and
            // this newly created native handle, never overwrite either one.
            state.unclassified.push(Arc::clone(&custody));
        } else {
            let unknown = state.poisoned;
            state.slots.insert(
                self.id,
                Slot::Retained {
                    custody: Arc::clone(&custody),
                    unknown,
                },
            );
        }
        self.attached = true;
        custody
    }
}

impl Drop for RunnerAdmission {
    fn drop(&mut self) {
        if self.attached {
            return;
        }
        let mut state = self.registry.locked();
        if matches!(state.slots.get(&self.id), Some(Slot::Reserved)) {
            state.slots.remove(&self.id);
        }
    }
}

impl RunnerCustody {
    pub(super) fn publish_owner_facts(
        &self,
        deadline: Option<Instant>,
        observation_end: Option<Instant>,
        native_exit: Option<u32>,
        failed: bool,
    ) {
        let mut facts = match self.facts.lock() {
            Ok(facts) => facts,
            Err(_) => {
                if let Some(registry) = self.registry.upgrade() {
                    registry.update(self, false);
                }
                return;
            }
        };
        if facts.original_deadline.is_none() {
            facts.original_deadline = deadline;
        }
        if facts.first_observation_end.is_none() {
            facts.first_observation_end = observation_end;
        }
        facts.original_failed |= failed;
        if facts.native_exit.is_none() {
            facts.native_exit = native_exit;
            if native_exit.is_some() {
                facts.observed_late = Some(false);
            }
        }
        let terminal = facts.native_exit.is_some();
        let unknown = facts.original_failed || facts.cleanup_observation_lost;
        drop(facts);
        if let Some(registry) = self.registry.upgrade()
            && (terminal || unknown)
        {
            registry.update(self, terminal);
        }
    }

    fn cleanup_facts(&self) -> io::Result<CleanupFacts> {
        self.facts
            .lock()
            .map(|facts| facts.clone())
            .map_err(|_| io::Error::other("runner cleanup facts poisoned"))
    }

    fn mark_cleanup_observation_lost(&self) {
        if let Ok(mut facts) = self.facts.lock() {
            facts.cleanup_observation_lost = true;
        }
        if let Some(registry) = self.registry.upgrade() {
            registry.update(self, false);
        }
    }

    fn observe_native_cleanup(&self) -> io::Result<ProcessCleanupObservation> {
        let old = self.cleanup_facts()?;
        if let Some(code) = old.native_exit {
            return Ok(ProcessCleanupObservation::OwnerTerminated {
                owner_exit_code: Some(code as i32),
            });
        }
        let handle = self.handle.as_raw_handle() as HANDLE;
        match unsafe { WaitForSingleObject(handle, 0) } {
            WAIT_TIMEOUT => return Ok(ProcessCleanupObservation::NoTerminalObservation),
            WAIT_OBJECT_0 => {}
            _ => return Err(io::Error::last_os_error()),
        }
        let mut code = 0_u32;
        if unsafe { GetExitCodeProcess(handle, &mut code) } == 0 {
            return Err(io::Error::last_os_error());
        }
        // This zero-wait query may observe late cleanup. It neither resets an
        // original deadline nor changes the original command failure result.
        let mut facts = self
            .facts
            .lock()
            .map_err(|_| io::Error::other("runner cleanup facts poisoned"))?;
        if facts.native_exit.is_none() {
            facts.native_exit = Some(code);
            facts.observed_late = facts
                .first_observation_end
                .or(facts.original_deadline)
                .map(|deadline| Instant::now() >= deadline);
        }
        drop(facts);
        if let Some(registry) = self.registry.upgrade() {
            registry.update(self, true);
        }
        Ok(ProcessCleanupObservation::OwnerTerminated {
            owner_exit_code: Some(code as i32),
        })
    }
}

impl ProcessCleanupCustody for RunnerCustody {
    fn observe_cleanup(&self) -> io::Result<ProcessCleanupObservation> {
        let result = self.observe_native_cleanup();
        if result.is_err() {
            self.mark_cleanup_observation_lost();
        }
        result
    }
}

pub(crate) fn admit_runner() -> io::Result<RunnerAdmission> {
    REGISTRY.reserve()
}

/// Explicit same-HANDLE cleanup only; it does not restart or reclassify work.
pub fn reconcile_runner_cleanup() -> io::Result<Vec<RunnerCleanupReconciliation>> {
    REGISTRY.reconcile()
}
