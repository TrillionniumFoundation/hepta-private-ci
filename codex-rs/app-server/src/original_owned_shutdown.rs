//! Actual task custody for the explicit inherited Unix App Server lifetime.
//! A successful observation covers these registered tasks, not business effects,
//! Root authority, another runtime, or process exit. Default embeddings use None.

use futures::FutureExt;
use futures::future::BoxFuture;
use futures::future::Shared;
use std::error::Error;
use std::fmt;
use std::future::Future;
use std::future::IntoFuture;
use std::io;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

use crate::AppServerDrainHandle;
use crate::message_processor::MessageProcessor;

#[derive(Clone, Debug)]
pub(crate) struct OriginalAppServerFailure {
    error: Arc<dyn Error + Send + Sync>,
}

impl OriginalAppServerFailure {
    fn from_io(error: io::Error) -> Self {
        Self {
            error: Arc::new(error),
        }
    }

    fn from_join(error: tokio::task::JoinError) -> Self {
        Self {
            error: Arc::new(error),
        }
    }

    pub(crate) fn to_io(&self) -> io::Error {
        io::Error::other(self.clone())
    }
}

impl fmt::Display for OriginalAppServerFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self.error.as_ref(), formatter)
    }
}

impl Error for OriginalAppServerFailure {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(self.error.as_ref())
    }
}

#[derive(Debug)]
struct OriginalAppServerFailures(Vec<(&'static str, OriginalAppServerFailure)>);

impl fmt::Display for OriginalAppServerFailures {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        for (index, (kind, error)) in self.0.iter().enumerate() {
            if index != 0 {
                write!(formatter, "; ")?;
            }
            write!(formatter, "{kind}: {error}")?;
        }
        Ok(())
    }
}

impl Error for OriginalAppServerFailures {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        self.0.first().map(|(_, error)| error as &dyn Error)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum OriginalAppServerTaskKind {
    Acceptor,
    Processor,
    Outbound,
    Telemetry,
    Rpc,
    SerializedQueue,
    ConnectionCleanup,
    ThreadStartup,
    ThreadListener,
    ThreadUnload,
    PluginRefresh,
}

pub(crate) struct OriginalAppServerJob {
    completion: Shared<BoxFuture<'static, Result<(), OriginalAppServerFailure>>>,
    terminal: OnceLock<Result<(), OriginalAppServerFailure>>,
}

impl OriginalAppServerJob {
    fn unit(handle: JoinHandle<()>) -> Arc<Self> {
        let completion = async move {
            handle
                .await
                .map_err(OriginalAppServerFailure::from_join)
        }
        .boxed()
        .shared();
        Arc::new(Self {
            completion,
            terminal: OnceLock::new(),
        })
    }

    fn result(handle: JoinHandle<io::Result<()>>) -> Arc<Self> {
        let completion = async move {
            match handle.await {
                Ok(result) => result.map_err(OriginalAppServerFailure::from_io),
                Err(error) => Err(OriginalAppServerFailure::from_join(error)),
            }
        }
        .boxed()
        .shared();
        Arc::new(Self {
            completion,
            terminal: OnceLock::new(),
        })
    }

    pub(crate) async fn join_original(&self) -> Result<(), OriginalAppServerFailure> {
        // The registry retains the one actual join future. Cancellation drops
        // only this waiter; Shared coordinates concurrent observers and caches
        // the same Arc-backed original error after the handle has completed.
        let result = self.completion.clone().await;
        let _ = self.terminal.set(result.clone());
        result
    }

    fn require_original_success(&self) -> io::Result<()> {
        match self.terminal.get() {
            Some(Ok(())) => Ok(()),
            Some(Err(error)) => Err(error.to_io()),
            None => Err(io::Error::other("original App Server task is not joined")),
        }
    }
}

/// The ordinary branch awaits its original JoinHandle. The explicit branch
/// awaits the registered job; dropping this local waiter cannot detach it.
pub(crate) enum OptionalAppServerTask {
    Ordinary(JoinHandle<()>),
    Original(Arc<OriginalAppServerJob>),
}

impl IntoFuture for OptionalAppServerTask {
    type Output = io::Result<()>;
    type IntoFuture = Pin<Box<dyn Future<Output = Self::Output> + Send>>;

    fn into_future(self) -> Self::IntoFuture {
        Box::pin(async move {
            match self {
                Self::Ordinary(handle) => handle.await.map_err(io::Error::other),
                Self::Original(job) => OriginalAppServerJob::join_original(&job)
                    .await
                    .map_err(|error| error.to_io()),
            }
        })
    }
}

#[derive(Default)]
struct OriginalAppServerState {
    main: Option<Arc<OriginalAppServerJob>>,
    tasks: Vec<(OriginalAppServerTaskKind, Arc<OriginalAppServerJob>)>,
    processors: Vec<Arc<MessageProcessor>>,
    unreleased_processors: Vec<Arc<MessageProcessor>>,
    processor_cleanup: Option<Arc<OriginalAppServerJob>>,
    drain: Option<AppServerDrainHandle>,
    transports: Vec<CancellationToken>,
    failures: Vec<OriginalAppServerFailure>,
    poisoned: bool,
    sealed: bool,
    background_closed: bool,
}

/// Empty custody grants no runtime permission and is not a joined observation.
/// Only the concrete App Server entry registers the original main invocation.
pub struct OriginalAppServerOwnerCustody {
    state: Mutex<OriginalAppServerState>,
    stopping: AtomicBool,
}

/// Retains actual already-observed job objects from one original invocation.
/// It is not a C, Root, FinalUse, or OS-exit receipt.
pub struct OriginalAppServerJoined {
    original: Arc<OriginalAppServerOwnerCustody>,
    main: Arc<OriginalAppServerJob>,
    processor_cleanup: Arc<OriginalAppServerJob>,
    tasks: Vec<(OriginalAppServerTaskKind, Arc<OriginalAppServerJob>)>,
}

impl OriginalAppServerJoined {
    pub fn require_original_custody(
        &self,
        original: &Arc<OriginalAppServerOwnerCustody>,
    ) -> io::Result<()> {
        if !Arc::ptr_eq(&self.original, original) {
            return Err(io::Error::other(
                "App Server observation has another actual owner",
            ));
        }
        self.main.require_original_success()?;
        self.processor_cleanup.require_original_success()?;
        for (_, task) in &self.tasks {
            task.require_original_success()?;
        }
        let state = original.state();
        if state.poisoned
            || !state.sealed
            || !state.failures.is_empty()
            || !state.unreleased_processors.is_empty()
            || state.tasks.len() != self.tasks.len()
            || state
                .tasks
                .iter()
                .zip(&self.tasks)
                .any(|(actual, recorded)| {
                    actual.0 != recorded.0 || !Arc::ptr_eq(&actual.1, &recorded.1)
                })
        {
            return Err(io::Error::other(
                "App Server task custody changed after terminal join",
            ));
        }
        Ok(())
    }
}

impl OriginalAppServerOwnerCustody {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            state: Mutex::new(OriginalAppServerState::default()),
            stopping: AtomicBool::new(false),
        })
    }

    fn state(&self) -> std::sync::MutexGuard<'_, OriginalAppServerState> {
        match self.state.lock() {
            Ok(state) => state,
            Err(error) => {
                let mut state = error.into_inner();
                state.poisoned = true;
                state
            }
        }
    }

    pub fn request_stop(&self) {
        self.stopping.store(true, Ordering::Release);
        let (drain, transports) = {
            let mut state = self.state();
            state.background_closed = true;
            (state.drain.clone(), state.transports.clone())
        };
        if let Some(drain) = drain {
            drain.request_drain();
        }
        for transport in transports {
            transport.cancel();
        }
    }

    pub(crate) async fn run_original_main(
        self: &Arc<Self>,
        drain: AppServerDrainHandle,
        future: impl Future<Output = io::Result<()>> + Send + 'static,
    ) -> io::Result<()> {
        let main = {
            let mut state = self.state();
            if state.poisoned || state.main.is_some() || self.stopping.load(Ordering::Acquire) {
                return Err(io::Error::other(
                    "original App Server invocation cannot start again",
                ));
            }
            state.drain = Some(drain);
            let job = OriginalAppServerJob::result(tokio::spawn(future));
            state.main = Some(Arc::clone(&job));
            job
        };
        let mut stopped_on_drop = StopOriginalAppServerOnDrop(Some(Arc::clone(self)));
        let result = OriginalAppServerJob::join_original(&main).await;
        if result.is_err() {
            self.request_stop();
        }
        // A main startup error may occur after a real acceptor was registered.
        // Finish all actual retained owners before returning that same error.
        let joined = self.join_original_app_server().await;
        stopped_on_drop.0 = None;
        match (result, joined) {
            (Ok(()), Ok(_)) => Ok(()),
            (Err(error), Ok(_)) => Err(error.to_io()),
            (Ok(()), Err(error)) => Err(error),
            (Err(error), Err(cleanup)) => Err(io::Error::other(OriginalAppServerFailures(vec![
                ("main", error),
                ("cleanup", OriginalAppServerFailure::from_io(cleanup)),
            ]))),
        }
    }

    pub(crate) fn retain_original_transport(&self, token: &CancellationToken) {
        let mut state = self.state();
        if !state.transports.is_empty() {
            state.poisoned = true;
        }
        state.transports.push(token.clone());
        let stopped = self.stopping.load(Ordering::Acquire);
        drop(state);
        if stopped {
            token.cancel();
        }
    }

    pub(crate) fn seal_original_background(&self) {
        self.state().background_closed = true;
    }

    pub(crate) fn spawn_original_background(
        &self,
        future: impl Future<Output = ()> + Send + 'static,
    ) {
        let mut state = self.state();
        // No weak manager is upgraded and no effect starts before this cut.
        // Late notifications are simply unadmitted, not completed work.
        if state.background_closed || state.sealed || state.poisoned {
            return;
        }
        let job = OriginalAppServerJob::unit(tokio::spawn(future));
        state
            .tasks
            .push((OriginalAppServerTaskKind::PluginRefresh, job));
    }

    pub(crate) fn retain_unreleased_original_processor(&self, processor: Arc<MessageProcessor>) {
        let mut state = self.state();
        state.poisoned = true;
        state.unreleased_processors.push(processor);
    }

    pub(crate) fn record_original_failure(&self, error: io::Error) {
        self.state()
            .failures
            .push(OriginalAppServerFailure::from_io(error));
    }

    pub(crate) fn retain_original_processor(&self, processor: Arc<MessageProcessor>) {
        let mut state = self.state();
        if !state.processors.is_empty() || state.processor_cleanup.is_some() {
            state.poisoned = true;
        }
        state.processors.push(processor);
    }

    pub(crate) fn retain_original_task(
        &self,
        kind: OriginalAppServerTaskKind,
        handle: JoinHandle<()>,
    ) -> Arc<OriginalAppServerJob> {
        let job = OriginalAppServerJob::unit(handle);
        let mut state = self.state();
        // Cleanup keeps the handle even if a programming error starts work
        // after sealing; that error can never produce a successful observation.
        if state.sealed {
            state.poisoned = true;
        }
        state.tasks.push((kind, Arc::clone(&job)));
        job
    }

    pub(crate) fn optional_original_task(
        original: Option<&Arc<Self>>,
        kind: OriginalAppServerTaskKind,
        handle: JoinHandle<()>,
    ) -> OptionalAppServerTask {
        match original {
            Some(original) => {
                OptionalAppServerTask::Original(Self::retain_original_task(original, kind, handle))
            }
            None => OptionalAppServerTask::Ordinary(handle),
        }
    }

    pub(crate) async fn join_original_group(
        &self,
        kind: OriginalAppServerTaskKind,
    ) -> io::Result<()> {
        let tasks = self
            .state()
            .tasks
            .iter()
            .filter(|(actual, _)| *actual == kind)
            .map(|(_, task)| Arc::clone(task))
            .collect::<Vec<_>>();
        let mut failures = Vec::new();
        for task in tasks {
            if let Err(error) = OriginalAppServerJob::join_original(&task).await {
                failures.push(("actual inner task", error));
            }
        }
        if failures.is_empty() {
            Ok(())
        } else {
            Err(io::Error::other(OriginalAppServerFailures(failures)))
        }
    }

    pub(crate) async fn finish_original_processor(self: &Arc<Self>) -> io::Result<()> {
        let cleanup = {
            let mut state = self.state();
            if let Some(cleanup) = &state.processor_cleanup {
                Some(Arc::clone(cleanup))
            } else if state.processors.is_empty() {
                None
            } else {
                let processors = std::mem::take(&mut state.processors);
                let original = Arc::clone(self);
                let job = OriginalAppServerJob::result(tokio::spawn(async move {
                    let duplicate = processors.len() != 1;
                    let mut failures = Vec::new();
                    for processor in processors {
                        if let Err(error) =
                            MessageProcessor::finish_original_owners(processor, &original).await
                        {
                            failures.push((
                                "actual MessageProcessor owners",
                                OriginalAppServerFailure::from_io(error),
                            ));
                        }
                    }
                    if duplicate {
                        failures.push((
                            "processor identity",
                            OriginalAppServerFailure::from_io(io::Error::other(
                                "original App Server has more than one processor",
                            )),
                        ));
                    }
                    if failures.is_empty() {
                        Ok(())
                    } else {
                        Err(io::Error::other(OriginalAppServerFailures(failures)))
                    }
                }));
                state.processor_cleanup = Some(Arc::clone(&job));
                Some(job)
            }
        };
        match cleanup {
            Some(cleanup) => OriginalAppServerJob::join_original(&cleanup)
                .await
                .map_err(|error| error.to_io()),
            None => Ok(()),
        }
    }

    pub async fn join_original_app_server(self: &Arc<Self>) -> io::Result<OriginalAppServerJoined> {
        self.request_stop();
        let main = self
            .state()
            .main
            .clone()
            .ok_or_else(|| io::Error::other("original App Server main was never started"))?;
        let mut failures = Vec::new();
        if let Err(error) = OriginalAppServerJob::join_original(&main).await {
            failures.push(("actual main", error));
        }
        if let Err(error) = Self::finish_original_processor(self).await {
            failures.push((
                "processor cleanup",
                OriginalAppServerFailure::from_io(error),
            ));
        }
        // The actual main and processor cleanup have ended. Their retained
        // producer tasks are joined in order by finish_original_owners; no
        // background count or zero Arc count substitutes for these awaits.
        let mut observed = 0;
        loop {
            let tasks = self.state().tasks[observed..]
                .iter()
                .map(|(kind, task)| (*kind, Arc::clone(task)))
                .collect::<Vec<_>>();
            if tasks.is_empty() {
                break;
            }
            for (_, task) in &tasks {
                if let Err(error) = OriginalAppServerJob::join_original(task).await {
                    failures.push(("actual retained inner task", error));
                }
            }
            observed += tasks.len();
        }
        let (tasks, processor_cleanup) = {
            let mut state = self.state();
            state.sealed = true;
            failures.extend(
                state
                    .failures
                    .iter()
                    .cloned()
                    .map(|error| ("original owner", error)),
            );
            if state.poisoned {
                failures.push((
                    "custody",
                    OriginalAppServerFailure::from_io(io::Error::other(
                        "original App Server custody poisoned",
                    )),
                ));
            }
            for required in [
                OriginalAppServerTaskKind::Acceptor,
                OriginalAppServerTaskKind::Processor,
                OriginalAppServerTaskKind::Outbound,
                OriginalAppServerTaskKind::Telemetry,
            ] {
                if !state.tasks.iter().any(|(kind, _)| *kind == required) {
                    failures.push((
                        "startup",
                        OriginalAppServerFailure::from_io(io::Error::other(format!(
                            "original App Server task absent: {required:?}"
                        ))),
                    ));
                }
            }
            (state.tasks.clone(), state.processor_cleanup.clone())
        };
        if !failures.is_empty() {
            return Err(io::Error::other(OriginalAppServerFailures(failures)));
        }
        let processor_cleanup = processor_cleanup
            .ok_or_else(|| io::Error::other("original App Server processor was never owned"))?;
        let joined = OriginalAppServerJoined {
            original: Arc::clone(self),
            main,
            processor_cleanup,
            tasks,
        };
        OriginalAppServerJoined::require_original_custody(&joined, self)?;
        Ok(joined)
    }
}

struct StopOriginalAppServerOnDrop(Option<Arc<OriginalAppServerOwnerCustody>>);

impl Drop for StopOriginalAppServerOnDrop {
    fn drop(&mut self) {
        if let Some(original) = &self.0 {
            OriginalAppServerOwnerCustody::request_stop(original);
        }
    }
}

/// Aggregate original sources without replacing actual failures by success.
pub(crate) fn finish_original_failures(failures: Vec<(&'static str, io::Error)>) -> io::Result<()> {
    if failures.is_empty() {
        Ok(())
    } else {
        Err(io::Error::other(OriginalAppServerFailures(
            failures
                .into_iter()
                .map(|(kind, error)| (kind, OriginalAppServerFailure::from_io(error)))
                .collect(),
        )))
    }
}

#[cfg(test)]
#[path = "original_owned_shutdown_tests.rs"]
mod tests;
