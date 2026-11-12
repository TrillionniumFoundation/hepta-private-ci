//! Opt-in custody for actual ThreadManager startup owners and submission
//! loops. Removed threads keep their original loop evidence in this registry.
//! This does not claim that every unrelated Core background task is joined.

use super::ThreadManager;
use super::ThreadManagerState;
use super::ThreadRegistryState;
use crate::session::OriginalCoreTaskFailure;
use crate::session::OriginalSessionLoopShutdown;
use crate::session::SessionIo;
use crate::session::SessionSpawnArgs;
use crate::session::session::Session;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use futures::StreamExt;
use futures::stream::FuturesUnordered;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use tokio::task::JoinHandle;

#[derive(Default)]
pub(super) struct OriginalThreadShutdownCustody {
    state: Mutex<OriginalThreadShutdownState>,
    enabled: Arc<AtomicBool>,
}

#[derive(Default)]
struct OriginalThreadShutdownState {
    enabled: bool,
    ever_started: bool,
    sealed: bool,
    admission_poisoned: bool,
    startups: Vec<Arc<OriginalThreadStartupJob>>,
    loops: Vec<Arc<OriginalSessionLoopShutdown>>,
}

pub(super) struct OriginalThreadStartupAdmission<'a> {
    state: MutexGuard<'a, OriginalThreadShutdownState>,
    armed: bool,
}

struct OriginalThreadStartupJob {
    state: tokio::sync::Mutex<OriginalThreadStartupState>,
}

struct OriginalThreadStartupState {
    handle: Option<JoinHandle<()>>,
    result: Option<Result<(), Arc<OriginalCoreTaskFailure>>>,
}

struct OriginalThreadShutdownPlan {
    startups: Vec<Arc<OriginalThreadStartupJob>>,
    admission_poisoned: bool,
}

#[derive(Debug)]
struct OriginalThreadShutdownError {
    failures: Vec<Arc<OriginalCoreTaskFailure>>,
}

impl fmt::Display for OriginalThreadShutdownError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "original Core shutdown recorded {} failure(s)", self.failures.len())?;
        for failure in &self.failures {
            write!(formatter, "; {failure}")?;
        }
        Ok(())
    }
}

impl std::error::Error for OriginalThreadShutdownError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        self.failures.first().map(|failure| failure.as_ref() as _)
    }
}

fn refused(message: &'static str) -> CodexErr {
    CodexErr::Fatal(message.to_string())
}

impl OriginalThreadShutdownCustody {
    fn enable(&self, threads: &ThreadRegistryState) -> std::io::Result<()> {
        let mut state = self.state.lock().map_err(|_| {
            std::io::Error::other("original Core startup admission is poisoned")
        })?;
        if state.enabled || state.ever_started || state.sealed
            || !threads.threads.is_empty()
            || !threads.startup_delivery_claims.is_empty()
            || threads.starting_spawns.iter().any(|spawn| spawn.strong_count() != 0)
            || !threads.hard_delete_closing.is_empty()
            || !threads.startup_cleanup_closing.is_empty()
        {
            return Err(std::io::Error::other(
                "original Core custody must be enabled before any thread startup",
            ));
        }
        state.enabled = true;
        self.enabled.store(true, Ordering::Release);
        Ok(())
    }

    /// The actual tokio::spawn and registration happen while this admission
    /// is held, with no await in between. The default path retains no handle.
    pub(super) fn reserve_original_startup(
        &self,
    ) -> CodexResult<Option<OriginalThreadStartupAdmission<'_>>> {
        let mut state = self.state.lock().map_err(|_| {
            refused("original Core startup admission is poisoned")
        })?;
        if state.enabled && (state.sealed || state.admission_poisoned) {
            return Err(refused("original Core thread startup is sealed"));
        }
        state.ever_started = true;
        if !state.enabled {
            return Ok(None);
        }
        Ok(Some(OriginalThreadStartupAdmission { state, armed: true }))
    }

    /// Called synchronously on the actual Session::spawn result before any
    /// subsequent await. A poisoned admission still retains the real loop
    /// for cleanup, then refuses further ordinary startup processing.
    pub(super) fn retain_original_session_loop(&self, io: &SessionIo) -> CodexResult<()> {
        let mut state = match self.state.lock() {
            Ok(state) => state,
            Err(poisoned) => {
                let mut state = poisoned.into_inner();
                state.admission_poisoned = true;
                state
            }
        };
        if !state.enabled {
            return Ok(());
        }
        state.loops.push(io.retain_original_loop_shutdown());
        if state.admission_poisoned {
            return Err(refused("original Core session admission was poisoned"));
        }
        Ok(())
    }

    fn seal_original_startups(&self) -> std::io::Result<OriginalThreadShutdownPlan> {
        let mut state = match self.state.lock() {
            Ok(state) => state,
            Err(poisoned) => {
                let mut state = poisoned.into_inner();
                state.admission_poisoned = true;
                state
            }
        };
        if !state.enabled {
            return Err(std::io::Error::other(
                "original Core shutdown custody was not enabled before startup",
            ));
        }
        state.sealed = true;
        Ok(OriginalThreadShutdownPlan {
            startups: state.startups.clone(),
            admission_poisoned: state.admission_poisoned,
        })
    }

    async fn join_original_sealed(
        &self,
        plan: OriginalThreadShutdownPlan,
    ) -> Vec<Arc<OriginalCoreTaskFailure>> {
        let mut failures = Vec::new();
        let mut startups = plan.startups.into_iter().map(|job| async move {
            job.join_original_startup().await
        }).collect::<FuturesUnordered<_>>();
        while let Some(result) = startups.next().await {
            if let Err(error) = result {
                failures.push(error);
            }
        }
        // Every admitted startup handle has actually returned before this
        // snapshot. No new startup can cross the sealed admission mutex.
        let (loops, poisoned) = {
            let state = match self.state.lock() {
                Ok(state) => state,
                Err(poisoned) => poisoned.into_inner(),
            };
            (state.loops.clone(), state.admission_poisoned || self.state.is_poisoned())
        };
        let mut loops = loops.into_iter().map(|original| async move {
            OriginalSessionLoopShutdown::join_original_loop(&original).await
        }).collect::<FuturesUnordered<_>>();
        while let Some(result) = loops.next().await {
            if let Err(error) = result {
                failures.push(error);
            }
        }
        if plan.admission_poisoned || poisoned {
            failures.push(Arc::new(OriginalCoreTaskFailure::State(
                "original Core shutdown admission was poisoned",
            )));
        }
        failures
    }
}

impl OriginalThreadStartupAdmission<'_> {
    pub(super) fn retain_original_thread_startup_handle(
        mut self,
        handle: JoinHandle<()>,
    ) {
        self.state.startups.push(Arc::new(OriginalThreadStartupJob {
            state: tokio::sync::Mutex::new(OriginalThreadStartupState {
                handle: Some(handle),
                result: None,
            }),
        }));
        self.armed = false;
    }
}

impl Drop for OriginalThreadStartupAdmission<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.state.sealed = true;
            self.state.admission_poisoned = true;
        }
    }
}

impl OriginalThreadStartupJob {
    async fn join_original_startup(&self) -> Result<(), Arc<OriginalCoreTaskFailure>> {
        let mut state = self.state.lock().await;
        if let Some(result) = &state.result {
            return result.clone();
        }
        let result = match state.handle.as_mut() {
            Some(handle) => handle.await.map_err(|error| {
                Arc::new(OriginalCoreTaskFailure::Join(Arc::new(error)))
            }),
            None => Err(Arc::new(OriginalCoreTaskFailure::State(
                "actual original Core startup handle is unavailable",
            ))),
        };
        state.handle = None;
        state.result = Some(result.clone());
        result
    }
}

/// A cloned AgentControl keeps only this weak registry and its original
/// activation bit. An activated origin cannot degrade to the default path
/// merely because its actual registry has disappeared.
#[derive(Clone)]
pub(crate) struct OriginalSessionShutdownOrigin {
    registry: Weak<OriginalThreadShutdownCustody>,
    enabled: Arc<AtomicBool>,
}

impl ThreadManagerState {
    pub(crate) fn original_session_shutdown_origin(&self) -> OriginalSessionShutdownOrigin {
        OriginalSessionShutdownOrigin {
            registry: Arc::downgrade(&self.original_shutdown),
            enabled: Arc::clone(&self.original_shutdown.enabled),
        }
    }
}

impl OriginalSessionShutdownOrigin {
    pub(crate) async fn spawn_original_delegate(
        &self,
        args: SessionSpawnArgs,
    ) -> CodexResult<(Arc<Session>, SessionIo)> {
        let Some(registry) = self.registry.upgrade() else {
            if self.enabled.load(Ordering::Acquire) {
                return Err(refused("the original Core delegate custody has disappeared"));
            }
            return Session::spawn(args).await;
        };
        let mut args = Some(args);
        let receiver = {
            let admission = registry.reserve_original_startup()?;
            if let Some(admission) = admission {
                let Some(args) = args.take() else {
                    return Err(refused("the original delegate input was already consumed"));
                };
                let original = Arc::clone(&registry);
                let (sender, receiver) = tokio::sync::oneshot::channel();
                let worker = tokio::spawn(async move {
                    let result = match Session::spawn(args).await {
                        Ok((session, io)) => {
                            match original.retain_original_session_loop(&io) {
                                Ok(()) => Ok((session, io)),
                                Err(error) => Err(error),
                            }
                        }
                        Err(error) => Err(error),
                    };
                    // A cancelled delegate result waiter cannot release the
                    // registry's actual loop or startup handle.
                    let _ = sender.send(result);
                });
                OriginalThreadStartupAdmission::retain_original_thread_startup_handle(
                    admission,
                    worker,
                );
                Some(receiver)
            } else {
                None
            }
        };
        match receiver {
            Some(receiver) => receiver.await.map_err(|_| {
                refused("original delegate startup exited before delivering its result")
            })?,
            None => match args {
                Some(args) => Session::spawn(args).await,
                None => Err(refused("the original default delegate input is unavailable")),
            },
        }
    }
}

impl ThreadManager {
    /// Must be called by the actual strict AppServer owner before request
    /// dispatch. Historical ordinary starts prevent late activation.
    pub async fn enable_original_shutdown_custody(&self) -> std::io::Result<()> {
        let threads = self.state.thread_registry.read().await;
        self.state.original_shutdown.enable(&threads)
    }

    /// The caller first closes its RPC/background admission and joins the
    /// actual requests. This closes Core startup admission, joins every real
    /// admitted startup and every captured loop, including removed threads.
    /// It preserves all observed task failures and never calls the old bounded
    /// shutdown API or turns a timed-out/aborted wrapper into a joined owner.
    pub async fn shutdown_all_threads_original(&self) -> std::io::Result<()> {
        let plan = self.state.original_shutdown.seal_original_startups()?;
        let failures = self.state.original_shutdown.join_original_sealed(plan).await;
        // The original loop handles have now really completed, including
        // panicked loops whose original JoinError remains in the result.
        self.state.thread_registry.write().await.threads.clear();
        if failures.is_empty() {
            Ok(())
        } else {
            Err(std::io::Error::other(OriginalThreadShutdownError { failures }))
        }
    }
}

#[cfg(test)]
#[path = "thread_manager_original_shutdown_tests.rs"]
mod tests;
