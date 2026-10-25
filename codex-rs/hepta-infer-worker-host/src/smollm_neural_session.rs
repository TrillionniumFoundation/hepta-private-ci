//! Process ownership and bounded private framing for the CPU driver.
//! Drop retains a reaper; only shutdown can report an observed clean unload.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use serde::Deserialize;

const STOP: &[u8] = b"{\"schema\":\"hepta-smollm-neural-read-worker-v1\",\"stop\":true}\n";
const SUPERVISOR_WALL_SECONDS: u64 = 600;

#[path = "smollm_neural_session_owner.rs"]
mod owner;
use owner::SupervisorOwner;

pub(super) struct Session {
    directory: Arc<File>,
    supervisor: SupervisorOwner,
    runtime: tokio::runtime::Handle,
    cleanup_deadline: Instant,
    shutdown_deadline: Option<Instant>,
    in_flight_or_unknown: AtomicBool,
}

impl Session {
    pub(super) fn prepare(
        directory: File,
        runtime: tokio::runtime::Handle,
        deadline: Instant,
        cancellation: &tokio_util::sync::CancellationToken,
    ) -> Result<Self, String> {
        let supervisor = SupervisorOwner::prepare(directory, deadline, cancellation)?;
        let directory = supervisor.directory()?;
        let cleanup_deadline = supervisor.cutoff();
        Ok(Self {
            directory,
            supervisor,
            runtime,
            cleanup_deadline,
            shutdown_deadline: None,
            in_flight_or_unknown: AtomicBool::new(false),
        })
    }

    pub(super) fn spawn(&self, command: &mut Command) -> Result<(), String> {
        self.supervisor.spawn(command)
    }

    pub(super) fn path(&self, relative: &str) -> PathBuf {
        PathBuf::from(format!(
            "/proc/self/fd/{}/session/worker/{relative}",
            self.directory.as_raw_fd()
        ))
    }

    pub(super) fn has_exited(&mut self) -> Result<bool, String> {
        self.supervisor.try_wait().map(|value| value.is_some())
    }

    pub(super) fn wait_ready(
        &mut self,
        execution: &codex_hepta_agentd::NeuralCognitiveExecutionV1,
    ) -> Result<Vec<u8>, String> {
        let ready_path = self.path("ready.json");
        loop {
            execution.check()?;
            if self.has_exited()? {
                return Err("neural worker terminated before ready".to_owned());
            }
            if ready_path.exists() {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        let bytes = read_bounded(&ready_path, 65536)?;
        execution.check()?;
        Ok(bytes)
    }

    fn connect(&self, deadline: Instant) -> Result<UnixStream, String> {
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .ok_or("neural socket deadline")?;
        let socket = self.path("model.sock");
        let stream = self
            .runtime
            .block_on(async {
                tokio::time::timeout(remaining, tokio::net::UnixStream::connect(socket)).await
            })
            .map_err(|_| "neural socket connect deadline")?
            .map_err(|error| error.to_string())?
            .into_std()
            .map_err(|error| error.to_string())?;
        stream
            .set_nonblocking(false)
            .map_err(|error| error.to_string())?;
        Ok(stream)
    }

    pub(super) fn acknowledge_response(&self) {
        self.in_flight_or_unknown.store(false, Ordering::SeqCst);
    }

    pub(super) fn exchange(
        &self,
        bytes: &[u8],
        deadline: Instant,
        execution: &codex_hepta_agentd::NeuralCognitiveExecutionV1,
    ) -> Result<Vec<u8>, String> {
        execution.check()?;
        let deadline = deadline.min(execution.deadline());
        if self.in_flight_or_unknown.load(Ordering::SeqCst) {
            return Err(
                "neural session has unresolved physical execution; unload required".to_owned(),
            );
        }
        if bytes.is_empty() || bytes.len() >= 8192 || bytes.contains(&b'\n') {
            return Err("neural request frame bound".to_owned());
        }
        let mut stream = self.connect(deadline)?;
        execution.check()?;
        self.in_flight_or_unknown
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .map_err(|_| "neural session has unresolved physical execution; unload required")?;
        let mut frame = bytes.to_vec();
        frame.push(b'\n');
        let mut written = 0;
        while written < frame.len() {
            execution.check()?;
            let remaining = deadline
                .checked_duration_since(Instant::now())
                .ok_or("neural write deadline")?;
            stream
                .set_write_timeout(Some(remaining))
                .map_err(|error| error.to_string())?;
            let count = stream
                .write(&frame[written..])
                .map_err(|error| error.to_string())?;
            if count == 0 {
                return Err("neural write closed".to_owned());
            }
            written += count;
        }
        let mut raw = Vec::new();
        loop {
            execution.check()?;
            let remaining = deadline
                .checked_duration_since(Instant::now())
                .ok_or("neural read deadline")?;
            stream
                .set_read_timeout(Some(remaining))
                .map_err(|error| error.to_string())?;
            let mut bytes = [0_u8; 1024];
            let count = stream.read(&mut bytes).map_err(|error| error.to_string())?;
            if count == 0 {
                return Err("neural response closed before terminal frame".to_owned());
            }
            raw.extend_from_slice(&bytes[..count]);
            if raw.len() > 128 * 1024 {
                return Err("neural response frame bound".to_owned());
            }
            if raw.contains(&b'\n') {
                if raw.last() != Some(&b'\n')
                    || raw.iter().filter(|byte| **byte == b'\n').count() != 1
                {
                    return Err("neural response contains multiple or trailing frames".to_owned());
                }
                raw.pop();
                execution.check()?;
                return Ok(raw);
            }
        }
    }

    pub(super) fn shutdown(&mut self) -> Result<(), String> {
        let deadline = *self
            .shutdown_deadline
            .get_or_insert_with(|| Instant::now() + Duration::from_secs(10));
        shutdown_remaining(deadline)?;
        if !self.has_exited()? {
            let mut stream = self.connect(deadline)?;
            stream
                .set_write_timeout(Some(
                    shutdown_remaining(deadline)?.min(Duration::from_secs(1)),
                ))
                .map_err(|error| error.to_string())?;
            stream.write_all(STOP).map_err(|error| error.to_string())?;
        }
        while !self.has_exited()? {
            shutdown_remaining(deadline)?;
            std::thread::sleep(Duration::from_millis(10));
        }
        shutdown_remaining(deadline)?;
        verify_terminal_receipt(&self.directory, self.supervisor.try_wait()?)?;
        shutdown_remaining(deadline)?;
        self.supervisor.release_verified_terminal()?;
        Ok(())
    }
}

fn shutdown_remaining(deadline: Instant) -> Result<Duration, String> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|left| !left.is_zero())
        .ok_or_else(|| {
            "neural unload terminal observation unavailable; original supervisor retained"
                .to_owned()
        })
}

impl Drop for Session {
    fn drop(&mut self) {
        self.supervisor.request_cleanup(self.cleanup_deadline);
    }
}

fn verify_terminal_receipt(
    directory: &File,
    supervisor_status: Option<std::process::ExitStatus>,
) -> Result<(), String> {
    if !supervisor_status.is_some_and(|status| status.success()) {
        return Err("neural supervisor did not exit successfully".to_owned());
    }
    let receipt: SupervisorReceipt = serde_json::from_slice(&read_bounded(
        &PathBuf::from(format!(
            "/proc/self/fd/{}/session/worker/supervisor.json",
            directory.as_raw_fd()
        )),
        1024 * 1024,
    )?)
    .map_err(|error| error.to_string())?;
    if receipt.outcome != "success"
        || receipt.exit_code != Some(0)
        || receipt.stop_reason.is_some()
        || !receipt.waited_child_reaped
        || !receipt.owned_child_reap_resolved
        || receipt.waited_child_observation_error.is_some()
        || receipt.budget.wall_seconds != SUPERVISOR_WALL_SECONDS
        || receipt.budget.rss_bytes != 8 * 1024 * 1024 * 1024
        || receipt.observed_wall_ns > 600_000_000_000
        || !receipt
            .waited_child_peak_rss_bytes
            .is_some_and(|value| value > 0 && value <= receipt.budget.rss_bytes)
    {
        return Err("neural unload lacks a successful original owned-child receipt".to_owned());
    }
    Ok(())
}

#[derive(Deserialize)]
struct SupervisorReceipt {
    outcome: String,
    exit_code: Option<i32>,
    stop_reason: Option<String>,
    waited_child_reaped: bool,
    owned_child_reap_resolved: bool,
    waited_child_observation_error: Option<String>,
    observed_wall_ns: u64,
    waited_child_peak_rss_bytes: Option<u64>,
    budget: Budget,
}
#[derive(Deserialize)]
struct Budget {
    wall_seconds: u64,
    rss_bytes: u64,
}

pub(super) fn read_bounded(path: &Path, limit: u64) -> Result<Vec<u8>, String> {
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .map_err(|error| error.to_string())?;
    let metadata = file.metadata().map_err(|error| error.to_string())?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > limit {
        return Err("neural file bound".to_owned());
    }
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    if bytes.len() as u64 != metadata.len() {
        return Err("neural file changed while reading".to_owned());
    }
    Ok(bytes)
}

pub(super) fn write_private(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .map_err(|error| error.to_string())?;
    file.write_all(bytes).map_err(|error| error.to_string())?;
    file.sync_all().map_err(|error| error.to_string())
}

#[cfg(test)]
#[path = "smollm_neural_session_tests.rs"]
mod tests;
