//! A bounded process transport. Only this owned child may be interrupted.

use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;

use crate::CellGenerationErrorV2;
use crate::cell_joint_protocol::MAX_RESULT_BYTES;

const MAX_BINARY_BYTES: u64 = 2 * 1024 * 1024 * 1024;
const MAX_STDERR_BYTES: usize = 16 * 1024;

pub(crate) enum ProcessStatus {
    Succeeded,
    Failed,
    Cancelled,
    Deadline,
}

pub(crate) struct ProcessObservation {
    pub status: ProcessStatus,
    pub stdout: Vec<u8>,
    pub wall_micros: u64,
    pub communication_bytes: u64,
}

pub(crate) struct ProcessRequest<'a> {
    pub executable: &'a File,
    pub executable_digest: [u8; 32],
    pub payload: Vec<u8>,
    pub cancellation: &'a AtomicBool,
    pub deadline_micros: u64,
    pub clock: &'a (dyn Fn() -> u64 + Send + Sync),
}

/// Hash the opened inode using an independent cursor. Concurrent invocations
/// cannot interfere by seeking a shared descriptor, and path replacement does
/// not substitute the file inspected here. The admitting host must keep this
/// artifact immutable in place; before/after hashes cannot prove absence of a
/// transient in-place mutation between those observations.
#[cfg(target_os = "linux")]
pub(crate) fn executable_digest(file: &File) -> Result<[u8; 32], CellGenerationErrorV2> {
    use std::os::unix::fs::FileExt;
    use std::os::unix::fs::MetadataExt;

    struct Reader<'a> {
        file: &'a File,
        offset: u64,
    }
    impl Read for Reader<'_> {
        fn read(&mut self, bytes: &mut [u8]) -> std::io::Result<usize> {
            let count = self.file.read_at(bytes, self.offset)?;
            self.offset += count as u64;
            Ok(count)
        }
    }
    let before = file
        .metadata()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    if !before.is_file() || before.len() > MAX_BINARY_BYTES || before.mode() & 0o111 == 0 {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    let mut magic = [0; 4];
    file.read_exact_at(&mut magic, 0)
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    if magic != *b"\x7fELF" {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    let digest = Digest32::of_reader(Reader { file, offset: 0 }, MAX_BINARY_BYTES)
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    let after = file
        .metadata()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    if (
        before.len(),
        before.ctime(),
        before.ctime_nsec(),
        before.mtime(),
        before.mtime_nsec(),
    ) != (
        after.len(),
        after.ctime(),
        after.ctime_nsec(),
        after.mtime(),
        after.mtime_nsec(),
    ) {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    Ok(digest.into_array())
}

#[cfg(not(target_os = "linux"))]
pub(crate) fn executable_digest(_file: &File) -> Result<[u8; 32], CellGenerationErrorV2> {
    Err(CellGenerationErrorV2::Unavailable)
}

struct OwnedChild(Option<Child>);

impl Drop for OwnedChild {
    fn drop(&mut self) {
        let Some(mut child) = self.0.take() else {
            return;
        };
        if !matches!(child.try_wait(), Ok(Some(_))) {
            let _ = child.kill();
            // Custody moves only this Child to a reaper. A stuck kernel wait
            // must not block control RPCs or pretend cancellation completed.
            // If thread creation fails, dropping its captured Child does not
            // wait; the durable operation remains unresolved in either case.
            drop(
                thread::Builder::new()
                    .name("joint-proposal-reaper".into())
                    .spawn(move || {
                        let _ = child.wait();
                    }),
            );
        }
    }
}

fn bounded_read(
    mut input: impl Read,
    maximum: usize,
    overflow: &AtomicBool,
    transferred: &AtomicU64,
) -> std::io::Result<Vec<u8>> {
    let mut bytes = Vec::new();
    let mut buffer = [0; 8192];
    loop {
        let limit = buffer.len().min(maximum + 1 - bytes.len());
        let count = match input.read(&mut buffer[..limit]) {
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            value => value?,
        };
        if count == 0 {
            return Ok(bytes);
        }
        transferred.fetch_add(count as u64, Ordering::Relaxed);
        bytes.extend_from_slice(&buffer[..count]);
        if bytes.len() > maximum {
            overflow.store(true, Ordering::Release);
            return Err(std::io::Error::other("bounded proposal pipe exceeded"));
        }
    }
}

#[cfg(target_os = "linux")]
pub(crate) fn run(
    request: ProcessRequest<'_>,
) -> Result<ProcessObservation, CellGenerationErrorV2> {
    use std::os::fd::AsRawFd;

    let started = Instant::now();
    if executable_digest(request.executable)? != request.executable_digest {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    let mut last_clock = (request.clock)();
    if request.cancellation.load(Ordering::Acquire) || last_clock >= request.deadline_micros {
        return Ok(ProcessObservation {
            status: if request.cancellation.load(Ordering::Acquire) {
                ProcessStatus::Cancelled
            } else {
                ProcessStatus::Deadline
            },
            stdout: Vec::new(),
            wall_micros: elapsed_micros(started)?,
            communication_bytes: 0,
        });
    }
    // Resolve the already opened inode in the parent's procfs. The File stays
    // alive through wait; pathname replacement cannot switch the executable.
    let path = format!(
        "/proc/{}/fd/{}",
        std::process::id(),
        request.executable.as_raw_fd()
    );
    let child = Command::new(path)
        .env_clear()
        .env("LC_ALL", "C")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn();
    let mut owned_child = match child {
        Ok(value) => OwnedChild(Some(value)),
        Err(_) => {
            return Ok(ProcessObservation {
                status: ProcessStatus::Failed,
                stdout: Vec::new(),
                wall_micros: elapsed_micros(started)?,
                communication_bytes: 0,
            });
        }
    };
    let child = owned_child
        .0
        .as_mut()
        .ok_or(CellGenerationErrorV2::Unavailable)?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or(CellGenerationErrorV2::Unavailable)?;
    let stdout = child
        .stdout
        .take()
        .ok_or(CellGenerationErrorV2::Unavailable)?;
    let stderr = child
        .stderr
        .take()
        .ok_or(CellGenerationErrorV2::Unavailable)?;
    let overflow = Arc::new(AtomicBool::new(false));
    let transferred = Arc::new(AtomicU64::new(0));
    let (input_tx, input_rx) = mpsc::sync_channel(1);
    let input_count = Arc::clone(&transferred);
    let input_thread = thread::Builder::new()
        .name("joint-proposal-input".into())
        .spawn(move || {
            let result = (|| {
                let mut left = request.payload.as_slice();
                while !left.is_empty() {
                    let count = match stdin.write(left) {
                        Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                        value => value?,
                    };
                    if count == 0 {
                        return Err(std::io::Error::other("proposal stdin closed"));
                    }
                    input_count.fetch_add(count as u64, Ordering::Relaxed);
                    left = &left[count..];
                }
                stdin.flush()
            })();
            drop(stdin);
            let _ = input_tx.send(result);
        })
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    let (output_tx, output_rx) = mpsc::sync_channel(1);
    let output_overflow = Arc::clone(&overflow);
    let output_count = Arc::clone(&transferred);
    let output_thread = thread::Builder::new()
        .name("joint-proposal-output".into())
        .spawn(move || {
            let _ = output_tx.send(bounded_read(
                stdout,
                MAX_RESULT_BYTES,
                &output_overflow,
                &output_count,
            ));
        })
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    let (error_tx, error_rx) = mpsc::sync_channel(1);
    let error_overflow = Arc::clone(&overflow);
    let error_count = Arc::clone(&transferred);
    let error_thread = thread::Builder::new()
        .name("joint-proposal-errors".into())
        .spawn(move || {
            let _ = error_tx.send(bounded_read(
                stderr,
                MAX_STDERR_BYTES,
                &error_overflow,
                &error_count,
            ));
        })
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;

    let mut interruption = None;
    let mut termination_started = None;
    let status = loop {
        let now = (request.clock)();
        if interruption.is_none() {
            interruption = if request.cancellation.load(Ordering::Acquire) {
                Some(ProcessStatus::Cancelled)
            } else if now < last_clock {
                Some(ProcessStatus::Failed)
            } else if now >= request.deadline_micros {
                Some(ProcessStatus::Deadline)
            } else if overflow.load(Ordering::Acquire) {
                Some(ProcessStatus::Failed)
            } else {
                None
            };
            if interruption.is_some() {
                termination_started = Some(Instant::now());
                let _ = child.kill();
            }
        }
        last_clock = now;
        if let Some(exit) = child
            .try_wait()
            .map_err(|_| CellGenerationErrorV2::Unavailable)?
        {
            break interruption.unwrap_or(if exit.success() {
                ProcessStatus::Succeeded
            } else {
                ProcessStatus::Failed
            });
        }
        if termination_started
            .is_some_and(|started: Instant| started.elapsed() >= Duration::from_secs(1))
        {
            // SIGKILL is intent, not a terminal observation. Drop transfers the
            // owned process to a reaper; the original durable slot stays unknown.
            return Err(CellGenerationErrorV2::Unavailable);
        }
        thread::park_timeout(Duration::from_millis(2));
    };
    // A qualified pure proposal binary cannot leave descendants holding pipes.
    // If that contract is broken, preserve an unknown result instead of waiting
    // indefinitely or treating the leader's exit as complete model evidence.
    let timeout = Duration::from_secs(1);
    let written = input_rx
        .recv_timeout(timeout)
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    let output = output_rx
        .recv_timeout(timeout)
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    let errors = error_rx
        .recv_timeout(timeout)
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    input_thread
        .join()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    output_thread
        .join()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    error_thread
        .join()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    if executable_digest(request.executable).map_err(|_| CellGenerationErrorV2::Unavailable)?
        != request.executable_digest
    {
        return Err(CellGenerationErrorV2::Unavailable);
    }
    let status = if matches!(status, ProcessStatus::Succeeded)
        && (written.is_err() || output.is_err() || errors.is_err())
    {
        ProcessStatus::Failed
    } else {
        status
    };
    Ok(ProcessObservation {
        status,
        stdout: output.unwrap_or_default(),
        wall_micros: elapsed_micros(started)?,
        communication_bytes: transferred.load(Ordering::Relaxed),
    })
}

#[cfg(not(target_os = "linux"))]
pub(crate) fn run(
    _request: ProcessRequest<'_>,
) -> Result<ProcessObservation, CellGenerationErrorV2> {
    Err(CellGenerationErrorV2::Unavailable)
}

pub(crate) fn elapsed_micros(started: Instant) -> Result<u64, CellGenerationErrorV2> {
    u64::try_from(started.elapsed().as_micros()).map_err(|_| CellGenerationErrorV2::Capacity)
}
