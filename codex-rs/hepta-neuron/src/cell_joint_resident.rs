//! One serialized, bounded resident child beneath an existing generation worker.
//! The child caches immutable tensors only. Any uncertain exchange poisons the
//! session permanently; rebuilding a worker is an explicit owner decision.

use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::TryLockError;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use crate::CellGenerationErrorV2;
use crate::cell_joint_process::OwnedChild;
use crate::cell_joint_process::ProcessObservation;
use crate::cell_joint_process::ProcessRequest;
use crate::cell_joint_process::ProcessStatus;
use crate::cell_joint_process::elapsed_micros;
use crate::cell_joint_process::executable_digest;
use crate::cell_joint_protocol::read_proposal;

#[path = "cell_joint_resident_io.rs"]
mod io;

use io::read_frame;
use io::write_counted;

const POLL: Duration = Duration::from_millis(1);
const TERMINATION_GRACE: Duration = Duration::from_secs(1);
const MAX_STDERR: u64 = 16 * 1024;

#[derive(Default)]
pub(super) struct ResidentTransport {
    state: Mutex<TransportState>,
}

#[derive(Default)]
struct TransportState {
    session: Option<Session>,
    poisoned: bool,
}

impl ResidentTransport {
    pub(super) fn run(
        &self,
        mut request: ProcessRequest<'_>,
        initial_payload: impl FnOnce() -> Result<Vec<u8>, CellGenerationErrorV2>,
        request_digest: [u8; 32],
        remaining_prefix_bytes: usize,
    ) -> Result<ProcessObservation, CellGenerationErrorV2> {
        let started = Instant::now();
        let mut last_clock = (request.clock)();
        // There is no queued request collection and no payload is written while
        // another Cell owns the transport. Cancellation also covers contention.
        let mut state = loop {
            if let Some(status) = interrupted(&request, &mut last_clock)? {
                return observation(status, started, Vec::new(), 0);
            }
            match self.state.try_lock() {
                Ok(state) => break state,
                Err(TryLockError::WouldBlock) => thread::sleep(POLL),
                Err(TryLockError::Poisoned(_)) => return Err(CellGenerationErrorV2::Unavailable),
            }
        };
        if state.poisoned {
            return Err(CellGenerationErrorV2::Unavailable);
        }
        if executable_digest(request.executable).ok() != Some(request.executable_digest) {
            state.poisoned = true;
            state.session.take();
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        if state
            .session
            .as_ref()
            .is_none_or(|session| !session.model_loaded)
        {
            request.payload = initial_payload()?;
        }
        // Artifact hashing and preparing the initial model packet can take
        // time. Recheck the live budget before starting any native process.
        if let Some(status) = interrupted(&request, &mut last_clock)? {
            return observation(status, started, Vec::new(), 0);
        }
        if state.session.is_none() {
            match Session::start(request.executable) {
                Ok(session) => state.session = Some(session),
                Err(error) => {
                    // A partial spawn can already have executed before pipe or
                    // thread setup fails. Never turn that uncertainty into retry.
                    state.poisoned = true;
                    return Err(error);
                }
            }
        }
        let session = state
            .session
            .as_mut()
            .ok_or(CellGenerationErrorV2::Unavailable)?;
        let before = session.transferred.load(Ordering::Relaxed);
        let mut dispatch = DispatchProgress::Waiting;
        let mut result = session.exchange(&request, &mut last_clock, &mut dispatch);
        if matches!(dispatch, DispatchProgress::Waiting) {
            // No frame entered the writer queue. A cancellation/clock failure
            // here must not poison another Cell's healthy cached model.
            return match result {
                Ok((status, output)) => observation(status, started, output, 0),
                Err(error) => Err(error),
            };
        }
        if let Ok((ProcessStatus::Succeeded, output)) = &result {
            let valid = read_proposal(output, request_digest)
                .ok()
                .is_some_and(|proposal| {
                    proposal.delta.len() <= remaining_prefix_bytes
                        && proposal
                            .wall_micros
                            .iter()
                            .try_fold(0_u64, |sum, phase| sum.checked_add(*phase))
                            .is_some_and(|sum| {
                                elapsed_micros(started).is_ok_and(|wall| sum <= wall)
                            })
                });
            if !valid {
                result = Ok((ProcessStatus::Failed, Vec::new()));
            }
        }
        let bytes = session
            .transferred
            .load(Ordering::Relaxed)
            .saturating_sub(before);
        match result {
            Ok((ProcessStatus::Succeeded, output)) => {
                session.model_loaded = true;
                if executable_digest(request.executable).ok() != Some(request.executable_digest) {
                    state.poisoned = true;
                    state.session.take();
                    return Err(CellGenerationErrorV2::InvalidBinding);
                }
                observation(ProcessStatus::Succeeded, started, output, bytes)
            }
            Ok((status, _)) => {
                let terminated = session.terminate();
                let bytes = session
                    .transferred
                    .load(Ordering::Relaxed)
                    .saturating_sub(before);
                state.poisoned = true;
                state.session.take();
                if !terminated {
                    return Err(CellGenerationErrorV2::Unavailable);
                }
                if executable_digest(request.executable).ok() != Some(request.executable_digest) {
                    return Err(CellGenerationErrorV2::InvalidBinding);
                }
                observation(status, started, Vec::new(), bytes)
            }
            Err(error) => {
                session.terminate();
                state.poisoned = true;
                state.session.take();
                Err(error)
            }
        }
    }
}

fn interrupted(
    request: &ProcessRequest<'_>,
    last: &mut u64,
) -> Result<Option<ProcessStatus>, CellGenerationErrorV2> {
    let now = (request.clock)();
    if now < *last {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    *last = now;
    Ok(if request.cancellation.load(Ordering::Acquire) {
        Some(ProcessStatus::Cancelled)
    } else if now >= request.deadline_micros {
        Some(ProcessStatus::Deadline)
    } else {
        None
    })
}

fn observation(
    status: ProcessStatus,
    started: Instant,
    stdout: Vec<u8>,
    communication_bytes: u64,
) -> Result<ProcessObservation, CellGenerationErrorV2> {
    Ok(ProcessObservation {
        status,
        stdout,
        wall_micros: elapsed_micros(started)?,
        communication_bytes,
    })
}

enum DispatchProgress {
    Waiting,
    Sent,
}

struct Session {
    model_loaded: bool,
    child: OwnedChild,
    input: Option<mpsc::SyncSender<Vec<u8>>>,
    written: mpsc::Receiver<std::io::Result<()>>,
    output: Option<mpsc::Receiver<std::io::Result<Vec<u8>>>>,
    transferred: Arc<AtomicU64>,
    stderr_overflow: Arc<AtomicBool>,
    completed: Vec<Arc<AtomicBool>>,
    threads: Vec<thread::JoinHandle<()>>,
}

impl Session {
    #[cfg(target_os = "linux")]
    fn start(executable: &File) -> Result<Self, CellGenerationErrorV2> {
        use std::os::fd::AsRawFd;
        use std::process::Command;
        use std::process::Stdio;

        let executable_fd = executable.as_raw_fd();
        let parent_pid = std::process::id();
        let child = Command::new(format!("/proc/{parent_pid}/fd/{executable_fd}"))
            .arg("--resident-v1")
            .env_clear()
            .env("LC_ALL", "C")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        let mut child = OwnedChild(Some(child));
        let process = child.0.as_mut().ok_or(CellGenerationErrorV2::Unavailable)?;
        let mut stdin = process
            .stdin
            .take()
            .ok_or(CellGenerationErrorV2::Unavailable)?;
        let mut stdout = process
            .stdout
            .take()
            .ok_or(CellGenerationErrorV2::Unavailable)?;
        let mut stderr = process
            .stderr
            .take()
            .ok_or(CellGenerationErrorV2::Unavailable)?;
        let (input, incoming) = mpsc::sync_channel::<Vec<u8>>(1);
        let (written_tx, written) = mpsc::sync_channel(1);
        let (output_tx, output) = mpsc::sync_channel(1);
        let transferred = Arc::new(AtomicU64::new(0));
        let stderr_overflow = Arc::new(AtomicBool::new(false));
        let mut completed = Vec::new();
        let mut threads = Vec::new();
        let count = Arc::clone(&transferred);
        start_thread(
            &mut completed,
            &mut threads,
            "joint-resident-input",
            move || {
                while let Ok(bytes) = incoming.recv() {
                    let result =
                        write_counted(&mut stdin, &bytes, &count).and_then(|()| stdin.flush());
                    let failed = result.is_err();
                    if written_tx.send(result).is_err() || failed {
                        break;
                    }
                }
            },
        )?;
        let count = Arc::clone(&transferred);
        start_thread(
            &mut completed,
            &mut threads,
            "joint-resident-output",
            move || {
                loop {
                    let result = read_frame(&mut stdout, &count);
                    let failed = result.is_err();
                    if output_tx.send(result).is_err() || failed {
                        break;
                    }
                }
            },
        )?;
        let count = Arc::clone(&transferred);
        let overflow = Arc::clone(&stderr_overflow);
        start_thread(
            &mut completed,
            &mut threads,
            "joint-resident-error",
            move || {
                let mut buffer = [0; 1024];
                let mut total = 0;
                loop {
                    match stderr.read(&mut buffer) {
                        Ok(0) => break,
                        Ok(length) => {
                            count.fetch_add(length as u64, Ordering::Relaxed);
                            total += length as u64;
                            if total > MAX_STDERR {
                                overflow.store(true, Ordering::Release);
                                break;
                            }
                        }
                        Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                        Err(_) => {
                            overflow.store(true, Ordering::Release);
                            break;
                        }
                    }
                }
            },
        )?;
        Ok(Self {
            model_loaded: false,
            child,
            input: Some(input),
            written,
            output: Some(output),
            transferred,
            stderr_overflow,
            completed,
            threads,
        })
    }

    #[cfg(not(target_os = "linux"))]
    fn start(_executable: &File) -> Result<Self, CellGenerationErrorV2> {
        Err(CellGenerationErrorV2::Unavailable)
    }

    fn exchange(
        &mut self,
        request: &ProcessRequest<'_>,
        last_clock: &mut u64,
        dispatch: &mut DispatchProgress,
    ) -> Result<(ProcessStatus, Vec<u8>), CellGenerationErrorV2> {
        let length = u32::try_from(request.payload.len())
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        let mut framed = length.to_le_bytes().to_vec();
        framed.extend(&request.payload);
        // Spawning and framing are also outside the native request boundary.
        // Check immediately before the writer can transfer the first byte.
        if let Some(status) = interrupted(request, last_clock)? {
            return Ok((status, Vec::new()));
        }
        self.input
            .as_ref()
            .ok_or(CellGenerationErrorV2::Unavailable)?
            .try_send(framed)
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
        *dispatch = DispatchProgress::Sent;
        let mut written = false;
        let mut response = None;
        loop {
            if let Some(status) = interrupted(request, last_clock)? {
                return Ok((status, Vec::new()));
            }
            if self.stderr_overflow.load(Ordering::Acquire) {
                return Ok((ProcessStatus::Failed, Vec::new()));
            }
            if !written {
                match self.written.try_recv() {
                    Ok(Ok(())) => written = true,
                    Ok(Err(_)) | Err(mpsc::TryRecvError::Disconnected) => {
                        return Ok((ProcessStatus::Failed, Vec::new()));
                    }
                    Err(mpsc::TryRecvError::Empty) => {}
                }
            }
            if response.is_none() {
                match self
                    .output
                    .as_ref()
                    .ok_or(CellGenerationErrorV2::Unavailable)?
                    .try_recv()
                {
                    Ok(Ok(bytes)) => response = Some(bytes),
                    Ok(Err(_)) | Err(mpsc::TryRecvError::Disconnected) => {
                        return Ok((ProcessStatus::Failed, Vec::new()));
                    }
                    Err(mpsc::TryRecvError::Empty) => {}
                }
            }
            if written && let Some(bytes) = response.take() {
                return Ok((ProcessStatus::Succeeded, bytes));
            }
            if self
                .child
                .0
                .as_mut()
                .ok_or(CellGenerationErrorV2::Unavailable)?
                .try_wait()
                .map_err(|_| CellGenerationErrorV2::Unavailable)?
                .is_some()
            {
                return Ok((ProcessStatus::Failed, Vec::new()));
            }
            thread::sleep(POLL);
        }
    }

    fn terminate(&mut self) -> bool {
        self.input.take();
        self.output.take();
        let Some(child) = self.child.0.as_mut() else {
            return false;
        };
        let _ = child.kill();
        let started = Instant::now();
        loop {
            let reaped = matches!(child.try_wait(), Ok(Some(_)));
            if reaped
                && self
                    .completed
                    .iter()
                    .all(|done| done.load(Ordering::Acquire))
            {
                return self.threads.drain(..).all(|thread| thread.join().is_ok());
            }
            if started.elapsed() >= TERMINATION_GRACE {
                return false;
            }
            thread::sleep(POLL);
        }
    }
}

impl Drop for Session {
    fn drop(&mut self) {
        self.input.take();
        self.output.take();
        // OwnedChild retains custody and schedules a reaper without blocking.
    }
}

fn start_thread(
    completed: &mut Vec<Arc<AtomicBool>>,
    threads: &mut Vec<thread::JoinHandle<()>>,
    name: &str,
    run: impl FnOnce() + Send + 'static,
) -> Result<(), CellGenerationErrorV2> {
    let done = Arc::new(AtomicBool::new(false));
    let signal = Arc::clone(&done);
    threads.push(
        thread::Builder::new()
            .name(name.into())
            .spawn(move || {
                run();
                signal.store(true, Ordering::Release);
            })
            .map_err(|_| CellGenerationErrorV2::Unavailable)?,
    );
    completed.push(done);
    Ok(())
}
