//! Linux Legacy stdio shutdown custody. This mode retains the actual launch,
//! child wait, stderr reader and process-group termination work. An empty
//! custody is not evidence that a child exited. Default launchers do not use it.

use std::any::Any;
use std::error::Error;
use std::fmt;
use std::process::ExitStatus;
use std::sync::Mutex;
use std::sync::MutexGuard;

use rmcp::transport::async_rw::AsyncRwTransport;
use tokio::process::Child;
use tokio::process::ChildStdin;
use tokio::process::ChildStdout;
use tokio::runtime::Handle;
use tokio::sync::Mutex as AsyncMutex;
use tokio::sync::MutexGuard as AsyncMutexGuard;
use tokio::sync::Notify;
use tokio::task::JoinHandle;

use super::*;

type OriginalStdioIo = AsyncRwTransport<RoleClient, ChildStdout, ChildStdin>;
type TerminationThreadOwner = Arc<Mutex<Option<std::thread::JoinHandle<io::Result<()>>>>>;

#[derive(Clone, Debug)]
struct RecordedFailure {
    kind: io::ErrorKind,
    error: Arc<dyn Error + Send + Sync>,
}

impl RecordedFailure {
    fn io(error: io::Error) -> Self {
        Self {
            kind: error.kind(),
            error: Arc::new(error),
        }
    }

    fn join(error: tokio::task::JoinError) -> Self {
        Self {
            kind: io::ErrorKind::Other,
            error: Arc::new(error),
        }
    }

    fn to_io(&self) -> io::Error {
        io::Error::new(self.kind, self.clone())
    }
}

impl fmt::Display for RecordedFailure {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self.error.as_ref(), output)
    }
}

impl Error for RecordedFailure {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(self.error.as_ref())
    }
}

#[derive(Debug)]
struct ShutdownFailures(Vec<(&'static str, RecordedFailure)>);

impl fmt::Display for ShutdownFailures {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        for (index, (stage, failure)) in self.0.iter().enumerate() {
            if index != 0 {
                write!(output, "; ")?;
            }
            write!(output, "{stage}: {failure}")?;
        }
        Ok(())
    }
}

impl Error for ShutdownFailures {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        self.0.first().map(|(_, error)| error as &dyn Error)
    }
}

struct OwnedJob<T> {
    state: AsyncMutex<OwnedJobState<T>>,
}

struct OwnedJobState<T> {
    handle: Option<JoinHandle<io::Result<T>>>,
    result: Option<Result<T, RecordedFailure>>,
    joined: bool,
}

impl<T> OwnedJob<T> {
    fn track(handle: JoinHandle<io::Result<T>>) -> Arc<Self> {
        Arc::new(Self {
            state: AsyncMutex::new(OwnedJobState {
                handle: Some(handle),
                result: None,
                joined: false,
            }),
        })
    }

    async fn join(&self) -> AsyncMutexGuard<'_, OwnedJobState<T>> {
        let mut state = self.state.lock().await;
        if !state.joined && state.handle.is_none() {
            state.result = Some(Err(RecordedFailure::io(io::Error::other(
                "owned stdio job lost its actual handle before join",
            ))));
            state.joined = true;
        }
        if let Some(handle) = state.handle.as_mut() {
            // Borrow the SAME handle. Dropping this waiter leaves it in the
            // shared state. Record terminal state under the same lock before
            // another waiter may poll or consume it.
            let result = match handle.await {
                Ok(result) => result.map_err(RecordedFailure::io),
                Err(error) => Err(RecordedFailure::join(error)),
            };
            state.handle = None;
            state.result = Some(result);
            state.joined = true;
        }
        state
    }
}

#[derive(Default)]
struct CustodyState {
    launch: Option<Arc<OwnedJob<StdioServerTransport>>>,
    runtime: Option<Handle>,
    process_id: Option<u32>,
    child: Vec<Arc<OwnedJob<ExitStatus>>>,
    stderr: Vec<Arc<OwnedJob<()>>>,
    termination: Option<Arc<OwnedJob<()>>>,
    termination_attempted: bool,
    _termination_thread: Option<TerminationThreadOwner>,
    failures: Vec<RecordedFailure>,
    // A failed OS wait is never upgraded to a successful reap. Keep the
    // actual unreaped owner as well as its error until this custody is dropped.
    failed_child_owners: Vec<Box<dyn Any + Send>>,
    poisoned: bool,
}

/// Owns exactly one attempted Linux Legacy launch and its real cleanup work.
/// It is not an authority or application-completion receipt.
pub struct OriginalStdioShutdownCustody {
    state: Mutex<CustodyState>,
    stopping: AtomicBool,
    changed: Notify,
}

/// Created only by actual custody observation. A non-successful exit status
/// still records physical child exit; application errors remain separate.
pub struct OriginalStdioShutdownObservation {
    process_id: Option<u32>,
    status: Option<ExitStatus>,
}

impl OriginalStdioShutdownObservation {
    pub fn require_original_child_exited(&self) -> io::Result<()> {
        if self.process_id.is_some() && self.status.is_some() {
            Ok(())
        } else {
            Err(io::Error::other(
                "owned stdio was not started and does not prove child exit",
            ))
        }
    }
}

impl OriginalStdioShutdownCustody {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            state: Mutex::new(CustodyState::default()),
            stopping: AtomicBool::new(false),
            changed: Notify::new(),
        })
    }

    fn state(&self) -> MutexGuard<'_, CustodyState> {
        match self.state.lock() {
            Ok(state) => state,
            Err(poisoned) => {
                // Retain every actual handle even on poison. This does not
                // repair the state: every final observation remains an error.
                let mut state = poisoned.into_inner();
                state.poisoned = true;
                state
            }
        }
    }

    /// Request the original process group's TERM -> two-second KILL policy.
    /// The actual termination thread is owned by a retained join task.
    pub fn request_stop(&self) {
        self.stopping.store(true, Ordering::Release);
        let mut state = self.state();
        if !state.termination_attempted
            && let (Some(process_id), Some(runtime)) =
                (state.process_id, state.runtime.clone())
        {
            self.start_termination(&mut state, process_id, &runtime);
        }
        drop(state);
        self.changed.notify_waiters();
    }

    #[cfg(target_os = "linux")]
    fn start_termination(&self, state: &mut CustodyState, process_id: u32, runtime: &Handle) {
        state.termination_attempted = true;
        let thread = std::thread::Builder::new()
            .name("mcp-owned-stdio-stop".to_owned())
            .spawn(move || -> io::Result<()> {
                let exists = terminate_process_group(process_id)?;
                if exists {
                    sleep(PROCESS_GROUP_TERM_GRACE_PERIOD);
                    kill_process_group(process_id)?;
                }
                Ok(())
            });
        match thread {
            Ok(thread) => {
                // Keep the thread in shared storage until the actual blocking
                // join starts. A cancelled Tokio scheduling attempt cannot
                // silently discard an unjoined std::thread::JoinHandle.
                let retained = Arc::new(Mutex::new(Some(thread)));
                let join_owner = Arc::clone(&retained);
                let handle = runtime.spawn_blocking(move || {
                    let (mut slot, poisoned) = match join_owner.lock() {
                        Ok(slot) => (slot, false),
                        Err(error) => (error.into_inner(), true),
                    };
                    let thread = slot.take().ok_or_else(|| {
                        io::Error::other("owned stdio termination thread already taken")
                    })?;
                    drop(slot);
                    let result = thread.join().map_err(|_| {
                        io::Error::other("owned stdio termination thread panicked")
                    })?;
                    if poisoned {
                        if let Err(error) = result {
                            return Err(io::Error::other(format!(
                                "owned stdio termination slot poisoned; actual thread: {error}"
                            )));
                        }
                        return Err(io::Error::other(
                            "owned stdio termination-thread slot poisoned",
                        ));
                    }
                    result
                });
                // Retain the ACTUAL blocking join handle, without an async
                // wrapper whose cancellation could detach that handle.
                state._termination_thread = Some(retained);
                state.termination = Some(OwnedJob::track(handle));
            }
            Err(error) => state.failures.push(RecordedFailure::io(error)),
        }
    }

    #[cfg(not(target_os = "linux"))]
    fn start_termination(&self, state: &mut CustodyState, _process_id: u32, _runtime: &Handle) {
        state.termination_attempted = true;
        state.failures.push(RecordedFailure::io(unsupported()));
    }

    pub(super) fn launch(
        self: Arc<Self>,
        command: StdioServerCommand,
        fallback_cwd: PathBuf,
    ) -> BoxFuture<'static, io::Result<StdioServerTransport>> {
        async move {
            let launch = self.start_launch(command, fallback_cwd)?;
            let mut state = launch.join().await;
            match state.result.take() {
                Some(Ok(transport)) => {
                    if self.stopping.load(Ordering::Acquire) {
                        drop(state);
                        // Drop outside the job lock transfers the SAME child
                        // into this custody's actual child-wait job.
                        drop(transport);
                        Err(io::Error::other("owned stdio launch was stopped"))
                    } else {
                        Ok(transport)
                    }
                }
                Some(Err(error)) => {
                    let returned = error.to_io();
                    state.result = Some(Err(error));
                    Err(returned)
                }
                None => Err(io::Error::other("owned stdio launch result already consumed")),
            }
        }
        .boxed()
    }

    fn start_launch(
        self: &Arc<Self>,
        command: StdioServerCommand,
        fallback_cwd: PathBuf,
    ) -> io::Result<Arc<OwnedJob<StdioServerTransport>>> {
        if !cfg!(target_os = "linux") || command.protocol_mode != McpProtocolMode::Legacy {
            return Err(unsupported());
        }
        let runtime = Handle::try_current().map_err(io::Error::other)?;
        let mut state = self.state();
        if state.poisoned || state.launch.is_some() || self.stopping.load(Ordering::Acquire) {
            return Err(io::Error::other("owned stdio launch is closed or already attempted"));
        }
        let original = Arc::clone(self);
        let launch = OwnedJob::track(runtime.spawn_blocking(move || {
            LocalStdioServerLauncher::launch_server_owned(command, fallback_cwd, original)
        }));
        state.runtime = Some(runtime);
        state.launch = Some(Arc::clone(&launch));
        Ok(launch)
    }

    fn register_process(&self, process_id: Option<u32>) -> io::Result<()> {
        let mut state = self.state();
        if state.process_id.is_some() {
            state.failures.push(RecordedFailure::io(io::Error::other(
                "owned stdio attempted a second process",
            )));
            return Err(io::Error::other("owned stdio attempted a second process"));
        }
        let process_id = process_id.ok_or_else(|| {
            io::Error::other("actual owned stdio child has no process id")
        })?;
        state.process_id = Some(process_id);
        drop(state);
        if self.stopping.load(Ordering::Acquire) {
            self.request_stop();
        }
        self.changed.notify_waiters();
        Ok(())
    }

    fn retain_stderr(
        &self,
        stderr: tokio::process::ChildStderr,
        program_name: String,
    ) -> io::Result<()> {
        let mut state = self.state();
        let Some(runtime) = state.runtime.clone() else {
            state.failed_child_owners.push(Box::new(stderr));
            let error = RecordedFailure::io(io::Error::other(
                "owned stdio lost its actual launch runtime",
            ));
            state.failures.push(error.clone());
            return Err(error.to_io());
        };
        let handle = runtime.spawn(async move {
            let mut reader = BufReader::new(stderr).lines();
            loop {
                match reader.next_line().await {
                    Ok(Some(line)) => info!("MCP server stderr ({program_name}): {line}"),
                    Ok(None) => return Ok(()),
                    Err(error) => {
                        warn!("Failed to read MCP server stderr ({program_name}): {error}");
                        return Err(error);
                    }
                }
            }
        });
        state.stderr.push(OwnedJob::track(handle));
        Ok(())
    }

    fn retain_child(self: &Arc<Self>, mut child: Child, mut transport: Option<OriginalStdioIo>) {
        self.request_stop();
        let mut state = self.state();
        let Some(runtime) = state.runtime.clone() else {
            state.failed_child_owners.push(Box::new((child, transport)));
            state.failures.push(RecordedFailure::io(io::Error::other(
                "owned child cleanup lost the actual launch runtime",
            )));
            drop(state);
            self.changed.notify_waiters();
            return;
        };
        let original = Arc::clone(self);
        let termination = state.termination.clone();
        let handle = runtime.spawn(async move {
            // SDK send futures retain this same write Arc. Its actual close
            // waits for the original write lock and takes the real Writer.
            // Dropping AsyncRw alone would not prove the stdin FD released.
            if let Some(transport) = transport.as_mut()
                && let Err(error) = transport.close().await
            {
                original.state().failures.push(RecordedFailure::io(error));
            }
            // AsyncRw has no background reader task. Its actual stdout owner
            // is released here, after any borrowed receive future has ended.
            drop(transport);
            let termination_failed = if let Some(termination) = termination {
                let terminal = termination.join().await;
                !matches!(terminal.result.as_ref(), Some(Ok(())))
            } else {
                true
            };
            if termination_failed {
                // Preserve the original helper error while still attempting
                // to reap this real child. Normally the original TERM/KILL
                // thread has already been genuinely joined before this wait.
                if let Err(error) = child.kill().await {
                    let failure = RecordedFailure::io(error);
                    original.state().failed_child_owners.push(Box::new(child));
                    return Err(failure.to_io());
                }
            }
            match child.wait().await {
                Ok(status) => Ok(status),
                Err(error) => {
                    let failure = RecordedFailure::io(error);
                    if let Err(kill_error) = child.kill().await {
                        original.state().failures.push(RecordedFailure::io(kill_error));
                    }
                    if let Err(wait_error) = child.wait().await {
                        original.state().failures.push(RecordedFailure::io(wait_error));
                        original.state().failed_child_owners.push(Box::new(child));
                    }
                    Err(failure.to_io())
                }
            }
        });
        state.child.push(OwnedJob::track(handle));
        drop(state);
        self.changed.notify_waiters();
    }

    /// Close admission, then genuinely join every actual owned job. Cancelling
    /// this waiter retains all handles and unconsumed launch output for a
    /// subsequent call. This has no "empty means successful exit" shortcut.
    pub async fn join_original_stdio(&self) -> io::Result<OriginalStdioShutdownObservation> {
        self.request_stop();
        let launch = self.state().launch.clone();
        let Some(launch) = launch else {
            let state = self.state();
            if state.poisoned {
                return Err(io::Error::other("owned stdio custody poisoned before launch"));
            }
            return Ok(OriginalStdioShutdownObservation {
                process_id: None,
                status: None,
            });
        };
        let mut failures = Vec::new();
        let mut launch_state = launch.join().await;
        let abandoned = match launch_state.result.take() {
            Some(Ok(transport)) => Some(transport),
            Some(Err(error)) => {
                failures.push(("launch", error.clone()));
                launch_state.result = Some(Err(error));
                None
            }
            None => None,
        };
        drop(launch_state);
        drop(abandoned);

        // A delivered transport may still be held by the SDK. Do not infer
        // that its real child has been handed back from process exit or EOF.
        // The caller must cancel/join the actual SDK driver, or drop that
        // exact transport, before this step can finish.
        let (process_id, children, stderr, termination) = loop {
            let notified = self.changed.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            let snapshot = {
                let state = self.state();
                if state.process_id.is_none()
                    || !state.child.is_empty()
                    || !state.failed_child_owners.is_empty()
                {
                    Some((
                        state.process_id,
                        state.child.clone(),
                        state.stderr.clone(),
                        state.termination.clone(),
                    ))
                } else {
                    None
                }
            };
            if let Some(snapshot) = snapshot {
                break snapshot;
            }
            notified.await;
        };

        let mut status = None;
        for child in &children {
            let child_state = child.join().await;
            match child_state.result.as_ref() {
                Some(Ok(exit)) => status = Some(*exit),
                Some(Err(error)) => failures.push(("child wait", error.clone())),
                None => failures.push(("child wait", RecordedFailure::io(io::Error::other(
                    "owned stdio child result missing",
                )))),
            }
        }
        for reader in &stderr {
            let reader_state = reader.join().await;
            if let Some(Err(error)) = reader_state.result.as_ref() {
                failures.push(("stderr", error.clone()));
            }
        }
        if let Some(termination) = &termination {
            let termination_state = termination.join().await;
            if let Some(Err(error)) = termination_state.result.as_ref() {
                failures.push(("process-group termination join", error.clone()));
            }
        }
        let state = self.state();
        failures.extend(state.failures.iter().cloned().map(|error| ("custody", error)));
        if state.poisoned {
            failures.push(("custody", RecordedFailure::io(io::Error::other(
                "owned stdio custody mutex poisoned",
            ))));
        }
        if process_id.is_some() && (children.len() != 1 || stderr.len() != 1) {
            failures.push(("custody", RecordedFailure::io(io::Error::other(
                "owned stdio did not retain exactly one child and stderr reader",
            ))));
        }
        if !failures.is_empty() {
            return Err(io::Error::other(ShutdownFailures(failures)));
        }
        Ok(OriginalStdioShutdownObservation { process_id, status })
    }
}

pub(super) struct OriginalOwnedStdioTransport {
    transport: Option<OriginalStdioIo>,
    child: Option<Child>,
    custody: Arc<OriginalStdioShutdownCustody>,
}

impl OriginalOwnedStdioTransport {
    fn retire_transport(&mut self) {
        if let Some(child) = self.child.take() {
            self.custody.retain_child(child, self.transport.take());
        }
    }
}

impl Drop for OriginalOwnedStdioTransport {
    fn drop(&mut self) {
        self.retire_transport();
    }
}

impl Transport<RoleClient> for OriginalOwnedStdioTransport {
    type Error = io::Error;

    fn send(
        &mut self,
        item: TxJsonRpcMessage<RoleClient>,
    ) -> impl Future<Output = io::Result<()>> + Send + 'static {
        match self.transport.as_mut() {
            Some(transport) => transport.send(item).boxed(),
            None => futures::future::ready(Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "owned stdio transport already retired",
            )))
            .boxed(),
        }
    }

    fn receive(&mut self) -> impl Future<Output = Option<RxJsonRpcMessage<RoleClient>>> + Send {
        match self.transport.as_mut() {
            Some(transport) => transport.receive().boxed(),
            None => futures::future::ready(None).boxed(),
        }
    }

    async fn close(&mut self) -> io::Result<()> {
        self.retire_transport();
        let observation = self.custody.join_original_stdio().await?;
        observation.require_original_child_exited()
    }
}

impl LocalStdioServerLauncher {
    pub fn new_with_owned_shutdown(
        fallback_cwd: PathBuf,
        custody: Arc<OriginalStdioShutdownCustody>,
    ) -> Self {
        Self {
            fallback_cwd,
            owned_shutdown: Some(custody),
        }
    }

    fn launch_server_owned(
        command: StdioServerCommand,
        fallback_cwd: PathBuf,
        custody: Arc<OriginalStdioShutdownCustody>,
    ) -> io::Result<StdioServerTransport> {
        if !cfg!(target_os = "linux") || command.protocol_mode != McpProtocolMode::Legacy {
            return Err(unsupported());
        }
        let StdioServerCommand {
            program,
            args,
            env,
            env_vars,
            cwd,
            protocol_mode: _,
        } = command;
        let program_name = program.to_string_lossy().into_owned();
        let envs = create_env_for_mcp_server(env, &env_vars).map_err(io::Error::other)?;
        let cwd = cwd.map(PathBuf::from).unwrap_or(fallback_cwd);
        let resolved_program =
            program_resolver::resolve(program, &envs, &cwd).map_err(io::Error::other)?;
        if custody.stopping.load(Ordering::Acquire) {
            return Err(io::Error::other("owned stdio stopped before process spawn"));
        }
        let mut command = Command::new(&resolved_program);
        command
            .kill_on_drop(true)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .current_dir(&cwd)
            .env_clear()
            .envs(&envs)
            .args(&args);
        #[cfg(unix)]
        command.process_group(0);
        let child = command.stderr(Stdio::piped()).spawn()?;
        // Retain the actual child immediately, including every later pipe or
        // registration error. The strict branch uses the SAME SDK AsyncRw
        // framing as TokioChildProcess, but owns its Child and IO separately.
        let mut transport = OriginalOwnedStdioTransport {
            transport: None,
            child: Some(child),
            custody: Arc::clone(&custody),
        };
        let child = transport.child.as_mut().ok_or_else(|| {
            io::Error::other("owned stdio lost its newly spawned child")
        })?;
        custody.register_process(child.id())?;
        let stdin = child.stdin.take()
            .ok_or_else(|| io::Error::other("owned stdio stdin missing"))?;
        let stdout = child.stdout.take()
            .ok_or_else(|| io::Error::other("owned stdio stdout missing"))?;
        let stderr = child.stderr.take()
            .ok_or_else(|| io::Error::other("owned stdio stderr missing"))?;
        transport.transport = Some(AsyncRwTransport::new(stdout, stdin));
        custody.retain_stderr(stderr, program_name.clone())?;
        let process = StdioServerProcessHandle {
            inner: Arc::new(StdioServerProcessHandleInner {
                program_name,
                kind: StdioServerProcessKind::OwnedLocal(Arc::clone(&custody)),
                terminated: AtomicBool::new(false),
            }),
        };
        Ok(StdioServerTransport {
            inner: StdioServerTransportInner::OwnedLocalLegacy(transport),
            process,
        })
    }
}

fn unsupported() -> io::Error {
    io::Error::new(
        io::ErrorKind::Unsupported,
        "owned stdio shutdown supports Linux local Legacy transport only",
    )
}

#[cfg(all(test, target_os = "linux"))]
#[path = "stdio_server_owned_shutdown_tests.rs"]
mod tests;
