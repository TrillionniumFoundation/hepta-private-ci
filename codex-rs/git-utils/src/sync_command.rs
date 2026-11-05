//! Synchronous Git subprocesses tied to one cancellable, retained run owner.

use codex_utils_pty::StdChildCustody;
use std::fs::File;
use std::future::Future;
use std::io;
#[cfg(unix)]
use std::os::unix::fs::FileExt;
#[cfg(windows)]
use std::os::windows::fs::FileExt;
use std::process::Command;
use std::process::Output;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

const POLL_INTERVAL: Duration = Duration::from_millis(100);

/// Cancellation of one retained sync owner. Cancellation is permanent and is
/// also checked before spawning another Git command or entering an HTTP fallback.
#[derive(Clone, Default)]
pub struct GitCommandCancellation {
    cancelled: Arc<AtomicBool>,
}

impl GitCommandCancellation {
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }

    pub fn check(&self) -> Result<(), String> {
        if self.is_cancelled() {
            Err("Git command owner was cancelled".to_string())
        } else {
            Ok(())
        }
    }

    /// Drops the in-flight request future when the same sync owner stops.
    /// This does not replace any request timeout or retry a cancelled request.
    pub async fn run<T>(
        &self,
        future: impl Future<Output = Result<T, String>>,
    ) -> Result<T, String> {
        self.check()?;
        tokio::select! {
            biased;
            () = self.wait_cancelled() => Err("Git command owner was cancelled".to_string()),
            value = future => {
                self.check()?;
                value
            }
        }
    }

    async fn wait_cancelled(&self) {
        while !self.is_cancelled() {
            tokio::time::sleep(POLL_INTERVAL).await;
        }
    }
}

/// Captures Git output without inherited pipe EOF controlling owner shutdown.
/// The actual leader remains owned by `StdChildCustody` through cleanup.
pub fn run_git_command_with_custody(
    command: &mut Command,
    context: &str,
    timeout: Duration,
    cancellation: &GitCommandCancellation,
) -> Result<Output, String> {
    cancellation.check()?;
    let stdout = tempfile::tempfile().map_err(|err| format!("failed to capture {context}: {err}"))?;
    let stderr = tempfile::tempfile().map_err(|err| format!("failed to capture {context}: {err}"))?;
    command
        .stdin(Stdio::null())
        .stdout(stdout.try_clone().map_err(|err| format!("failed to capture {context}: {err}"))?)
        .stderr(stderr.try_clone().map_err(|err| format!("failed to capture {context}: {err}"))?);
    cancellation.check()?;
    let mut child = StdChildCustody::spawn(command)
        .map_err(|err| format!("failed to run {context}: {err}"))?;
    let start = Instant::now();
    loop {
        if cancellation.is_cancelled() {
            child.kill_and_wait().map_err(|err| format!("failed to stop cancelled {context}: {err}"))?;
            return Err(format!("{context} cancelled"));
        }
        if let Some(status) = child.try_wait().map_err(|err| format!("failed to poll {context}: {err}"))? {
            return Ok(Output {
                status,
                stdout: read_captured(&stdout, context)?,
                stderr: read_captured(&stderr, context)?,
            });
        }
        if start.elapsed() >= timeout {
            child.kill_and_wait().map_err(|err| format!("failed to stop {context} after timeout: {err}"))?;
            let bytes = read_captured(&stderr, context)?;
            let stderr = String::from_utf8_lossy(&bytes).trim().to_string();
            return if stderr.is_empty() {
                Err(format!("{context} timed out after {}s", timeout.as_secs()))
            } else {
                Err(format!("{context} timed out after {}s: {stderr}", timeout.as_secs()))
            };
        }
        std::thread::sleep(POLL_INTERVAL);
    }
}

fn read_captured(file: &File, context: &str) -> Result<Vec<u8>, String> {
    // Bound this read to the observed file length. An escaped Unix descendant
    // cannot turn a continually appended file into an unbounded EOF wait.
    // Positional reads also leave the inherited writer's shared offset alone.
    let length = file.metadata().map_err(|err| format!("failed to read {context} capture: {err}"))?.len();
    let mut bytes = Vec::new();
    let mut offset = 0;
    let mut buffer = [0; 8192];
    while offset < length {
        let limit = (length - offset).min(buffer.len() as u64) as usize;
        #[cfg(unix)]
        let read = file.read_at(&mut buffer[..limit], offset);
        #[cfg(windows)]
        let read = file.seek_read(&mut buffer[..limit], offset);
        let count = match read {
            Ok(0) => break,
            Ok(count) => count,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(format!("failed to read {context} capture: {error}")),
        };
        bytes.extend_from_slice(&buffer[..count]);
        offset += count as u64;
    }
    Ok(bytes)
}

#[cfg(test)]
#[path = "sync_command_tests.rs"]
mod tests;
