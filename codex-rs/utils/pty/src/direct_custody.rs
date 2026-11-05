use std::collections::BTreeMap;
use std::fmt;
use std::io;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use crate::ProcessCleanupCustody;
use crate::ProcessCleanupObservation;
use crate::ProcessSignal;
use crate::process::ChildTerminator;

/// Evidence available about the target-launch boundary of a failed spawn call.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TargetSpawnPhase {
    /// No target-launch API was called. This says nothing about preparatory I/O.
    BeforeLaunchAttempt,
    /// The selected backend established that a failed launch left no live target.
    /// Unlike `BeforeLaunchAttempt`, a native child may have been created and reaped.
    LaunchFailedClosed,
    /// A launch was attempted or an original child observation was lost.
    OutcomeUnknown,
}

/// A backend-issued classification; untyped errors must remain conservative.
pub struct ProcessSpawnError {
    phase: TargetSpawnPhase,
    source: anyhow::Error,
    custody: Option<Arc<dyn ProcessCleanupCustody>>,
}

impl ProcessSpawnError {
    pub fn phase(&self) -> TargetSpawnPhase {
        self.phase
    }

    /// Returns the original reservation's cleanup token, without a new launch or wait budget.
    /// A backend that failed without returning a child still has no native owner to query.
    pub fn cleanup_custody(&self) -> Option<Arc<dyn ProcessCleanupCustody>> {
        self.custody.clone()
    }
}

impl fmt::Debug for ProcessSpawnError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ProcessSpawnError")
            .field("phase", &self.phase)
            .field("source", &self.source)
            .field("has_cleanup_token", &self.custody.is_some())
            .finish()
    }
}

impl fmt::Display for ProcessSpawnError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(&self.source, f)
    }
}

impl std::error::Error for ProcessSpawnError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(self.source.as_ref())
    }
}

pub(crate) fn before_launch(error: impl Into<anyhow::Error>) -> anyhow::Error {
    ProcessSpawnError {
        phase: TargetSpawnPhase::BeforeLaunchAttempt,
        source: error.into(),
        custody: None,
    }
    .into()
}

/// Retains the original child independently from its exit-observer task.
pub(crate) trait RetainedChild: Send + Sync {
    /// Only an already retained kernel handle may establish a late terminal fact.
    fn observe_cleanup(&self) -> io::Result<ProcessCleanupObservation>;
}

#[derive(Default)]
pub(crate) struct DirectRegistry {
    state: Mutex<RegistryState>,
}

#[derive(Default)]
struct RegistryState {
    next_id: u64,
    poisoned: bool,
    entries: BTreeMap<u64, Arc<DirectCustody>>,
    unclassified: Vec<Arc<dyn RetainedChild>>,
}

#[derive(Clone, Copy)]
struct NativeExit {
    code: Option<i32>,
}

pub(crate) struct DirectCustody {
    id: u64,
    registry: Arc<DirectRegistry>,
    owner: OnceLock<Arc<dyn RetainedChild>>,
    unknown: AtomicBool,
    native_exit: OnceLock<NativeExit>,
}

pub(crate) struct DirectLaunch {
    custody: Arc<DirectCustody>,
    attempted: bool,
    finished: bool,
}

/// Owns the error channel and admission guard even before the waiter is first polled.
pub(crate) struct DirectWait {
    launch: DirectLaunch,
    exit_status: Arc<AtomicBool>,
    exit_code: Arc<Mutex<Option<i32>>>,
    exit_tx: Option<tokio::sync::oneshot::Sender<i32>>,
}

pub(crate) struct ObservedExit {
    pub(crate) legacy_code: i32,
    pub(crate) native_code: Option<i32>,
}

impl ObservedExit {
    pub(crate) fn from_status(status: std::process::ExitStatus) -> Self {
        Self {
            legacy_code: crate::process::exit_code_from_status(status),
            native_code: status.code(),
        }
    }

    pub(crate) fn from_portable(status: portable_pty::ExitStatus) -> Self {
        let code = status.exit_code() as i32;
        Self {
            legacy_code: code,
            native_code: Some(code),
        }
    }
}

pub(crate) fn reserve() -> io::Result<DirectLaunch> {
    static REGISTRY: OnceLock<Arc<DirectRegistry>> = OnceLock::new();
    REGISTRY
        .get_or_init(|| Arc::new(DirectRegistry::default()))
        .reserve()
}

impl DirectRegistry {
    pub(crate) fn reserve(self: &Arc<Self>) -> io::Result<DirectLaunch> {
        let mut state = self.state.lock().map_err(|mut poisoned| {
            poisoned.get_mut().poisoned = true;
            io::Error::other("direct process custody registry is poisoned")
        })?;
        if state.poisoned || state.entries.values().any(|entry| entry.is_unknown()) {
            return Err(io::Error::other(
                "an original direct process outcome is unknown; new admission is fenced",
            ));
        }
        let id = state
            .next_id
            .checked_add(1)
            .ok_or_else(|| io::Error::other("direct process identity space exhausted"))?;
        state.next_id = id;
        let custody = Arc::new(DirectCustody {
            id,
            registry: Arc::clone(self),
            owner: OnceLock::new(),
            unknown: AtomicBool::new(false),
            native_exit: OnceLock::new(),
        });
        state.entries.insert(id, Arc::clone(&custody));
        Ok(DirectLaunch {
            custody,
            attempted: false,
            finished: false,
        })
    }
}

impl DirectLaunch {
    pub(crate) fn begin_attempt(&mut self) {
        // This precedes the launch call without an intervening await. A backend
        // error is conservatively unknown, including errors inside that backend.
        self.attempted = true;
    }

    pub(crate) fn attach_owner(&self, owner: Arc<dyn RetainedChild>) -> io::Result<()> {
        if let Err(owner) = self.custody.owner.set(owner) {
            let mut state = match self.custody.registry.state.lock() {
                Ok(state) => state,
                Err(error) => error.into_inner(),
            };
            state.poisoned = true;
            state.unclassified.push(owner);
            drop(state);
            self.custody.mark_unknown();
            return Err(io::Error::other(
                "direct process owner was already attached",
            ));
        }
        if !self.attempted {
            self.custody.mark_unknown();
            return Err(io::Error::other(
                "direct process owner was attached before its launch reservation",
            ));
        }
        Ok(())
    }

    pub(crate) fn custody(&self) -> Arc<DirectCustody> {
        Arc::clone(&self.custody)
    }

    pub(crate) fn spawn_error(&self, error: impl Into<anyhow::Error>) -> anyhow::Error {
        self.custody.spawn_error(error)
    }

    #[cfg(unix)]
    pub(crate) fn reaped_std_spawn_error(&mut self, error: io::Error) -> anyhow::Error {
        // This issuer is only used by the existing StdCommand + pre_exec route.
        // The pinned Rust 1.96 fork/exec error channel waits for the original
        // child before returning Err; a wait failure panics instead. Tokio's
        // fallible post-spawn I/O conversion does not have this contract.
        if !self.attempted || self.custody.owner.get().is_some() {
            return self.spawn_error(error);
        }
        self.custody.release_exact_slot();
        self.finished = true;
        ProcessSpawnError {
            phase: TargetSpawnPhase::LaunchFailedClosed,
            source: error.into(),
            custody: None,
        }
        .into()
    }

    fn confirm_native_exit(&mut self, code: Option<i32>) -> io::Result<()> {
        self.custody.record_native_exit(code)?;
        self.finished = true;
        Ok(())
    }
}

impl DirectWait {
    pub(crate) fn new(
        launch: DirectLaunch,
        exit_status: Arc<AtomicBool>,
        exit_code: Arc<Mutex<Option<i32>>>,
        exit_tx: tokio::sync::oneshot::Sender<i32>,
    ) -> Self {
        Self {
            launch,
            exit_status,
            exit_code,
            exit_tx: Some(exit_tx),
        }
    }

    pub(crate) fn finish(mut self, result: io::Result<ObservedExit>) {
        let exit = match result {
            Ok(exit) => exit,
            Err(_error) => {
                // Publish the fence before the error channel becomes visible.
                self.launch.custody.mark_unknown();
                return;
            }
        };
        // Retain the native fact before releasing admission or publishing it.
        if self.launch.confirm_native_exit(exit.native_code).is_err() {
            return;
        }
        let Ok(mut guard) = self.exit_code.lock() else {
            return;
        };
        *guard = Some(exit.legacy_code);
        drop(guard);
        self.exit_status.store(true, Ordering::SeqCst);
        if let Some(exit_tx) = self.exit_tx.take() {
            let _ = exit_tx.send(exit.legacy_code);
        }
    }
}

impl Drop for DirectWait {
    fn drop(&mut self) {
        if !self.launch.finished {
            // This also runs when the task is dropped before its first poll.
            // The Drop body precedes exit_tx's field drop and receiver wakeup.
            self.launch.custody.mark_unknown();
        }
    }
}

impl Drop for DirectLaunch {
    fn drop(&mut self) {
        if self.finished {
            return;
        }
        if self.attempted || self.custody.owner.get().is_some() {
            self.custody.mark_unknown();
        } else {
            self.custody.release_exact_slot();
        }
    }
}

impl DirectCustody {
    pub(crate) fn spawn_error(self: &Arc<Self>, error: impl Into<anyhow::Error>) -> anyhow::Error {
        self.mark_unknown();
        ProcessSpawnError {
            phase: TargetSpawnPhase::OutcomeUnknown,
            source: error.into(),
            custody: Some(self.clone()),
        }
        .into()
    }

    pub(crate) fn is_unknown(&self) -> bool {
        self.unknown.load(Ordering::SeqCst)
    }

    pub(crate) fn mark_unknown(&self) {
        let mut state = match self.registry.state.lock() {
            Ok(state) => state,
            Err(error) => {
                let mut state = error.into_inner();
                state.poisoned = true;
                state
            }
        };
        if self.native_exit.get().is_some() {
            return;
        }
        self.unknown.store(true, Ordering::SeqCst);
        if !state
            .entries
            .get(&self.id)
            .is_some_and(|entry| std::ptr::eq(entry.as_ref(), self))
        {
            state.poisoned = true;
        }
    }

    fn release_exact_slot(&self) {
        let mut state = match self.registry.state.lock() {
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
            .is_some_and(|entry| std::ptr::eq(entry.as_ref(), self))
        {
            state.entries.remove(&self.id);
        }
    }

    fn record_native_exit(&self, code: Option<i32>) -> io::Result<()> {
        let mut state = match self.registry.state.lock() {
            Ok(state) => state,
            Err(error) => {
                let mut state = error.into_inner();
                state.poisoned = true;
                state
            }
        };
        if self.native_exit.set(NativeExit { code }).is_err()
            && self
                .native_exit
                .get()
                .is_some_and(|observed| observed.code != code)
        {
            state.poisoned = true;
            return Err(io::Error::other(
                "original direct process exit facts disagree",
            ));
        }
        if state
            .entries
            .get(&self.id)
            .is_some_and(|entry| std::ptr::eq(entry.as_ref(), self))
        {
            state.entries.remove(&self.id);
        }
        Ok(())
    }

    pub(crate) fn guard_terminator(
        self: &Arc<Self>,
        inner: Box<dyn ChildTerminator>,
    ) -> Box<dyn ChildTerminator> {
        Box::new(GuardedTerminator {
            custody: Arc::clone(self),
            inner,
        })
    }

    fn invoke_terminator(&self, call: impl FnOnce() -> io::Result<()>) -> io::Result<()> {
        let mut state = self.registry.state.lock().map_err(|mut poisoned| {
            poisoned.get_mut().poisoned = true;
            io::Error::other("direct process custody registry is poisoned")
        })?;
        #[cfg(windows)]
        if self.native_exit.get().is_some() {
            return Ok(());
        }
        #[cfg(not(windows))]
        if self.is_unknown() && self.native_exit.get().is_none() {
            // A numeric PID/PGID cannot re-establish ownership after wait loss.
            return Err(io::Error::other(
                "cannot signal an unobserved direct process by numeric identity",
            ));
        }
        // An observed Unix root exit retains the existing process-group cleanup
        // policy. This guard does not introduce a new stable Unix group handle.
        let result = call();
        if result.is_err() && self.native_exit.get().is_none() {
            self.unknown.store(true, Ordering::SeqCst);
            if !state
                .entries
                .get(&self.id)
                .is_some_and(|entry| std::ptr::eq(entry.as_ref(), self))
            {
                state.poisoned = true;
            }
        }
        result
    }
}

impl ProcessCleanupCustody for DirectCustody {
    fn observe_cleanup(&self) -> io::Result<ProcessCleanupObservation> {
        if let Some(exit) = self.native_exit.get() {
            return Ok(ProcessCleanupObservation::OwnerTerminated {
                owner_exit_code: exit.code,
            });
        }
        let Some(owner) = self.owner.get() else {
            return Ok(ProcessCleanupObservation::NoTerminalObservation);
        };
        match owner.observe_cleanup() {
            Ok(observation @ ProcessCleanupObservation::OwnerTerminated { owner_exit_code }) => {
                self.record_native_exit(owner_exit_code)?;
                Ok(observation)
            }
            Ok(observation) => Ok(observation),
            Err(error) => {
                self.mark_unknown();
                Err(error)
            }
        }
    }
}

struct GuardedTerminator {
    custody: Arc<DirectCustody>,
    inner: Box<dyn ChildTerminator>,
}

impl ChildTerminator for GuardedTerminator {
    fn signal(&mut self, signal: ProcessSignal) -> io::Result<()> {
        self.custody.invoke_terminator(|| self.inner.signal(signal))
    }

    fn kill(&mut self) -> io::Result<()> {
        self.custody.invoke_terminator(|| self.inner.kill())
    }
}

#[cfg(all(test, unix))]
#[path = "direct_custody_unix_tests.rs"]
mod tests;
