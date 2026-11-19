//! Bounded, fresh local process invocation; no retries or model persistence.

use std::ffi::OsString;
use std::io::Write;
use std::path::Path;
use std::process::Stdio;
use std::time::Duration;

use codex_hepta_types::Digest32;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;

use crate::native_memory_types::NativeMemoryModelConfigV1;

const OUTPUT_LIMIT: u64 = 65_536;
const REAP_TIMEOUT: Duration = Duration::from_secs(1);
const RUNTIME_ENVIRONMENT: &[&str] = &[
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TMP",
    "TEMP",
    "SYSTEMROOT",
    "WINDIR",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
];

pub(super) async fn execute(
    config: &NativeMemoryModelConfigV1,
    input: Vec<u8>,
    cancellation: &tokio_util::sync::CancellationToken,
    before_spawn: impl FnOnce() -> Result<(), String>,
) -> Result<Vec<u8>, String> {
    execute_with_environment(
        config,
        input,
        cancellation,
        std::env::vars_os(),
        before_spawn,
    )
    .await
}

// The explicit iterator lets process tests inject synthetic ambient secrets
// without changing the daemon/test runner's process-global environment.
async fn execute_with_environment(
    config: &NativeMemoryModelConfigV1,
    input: Vec<u8>,
    cancellation: &tokio_util::sync::CancellationToken,
    environment: impl IntoIterator<Item = (OsString, OsString)>,
    before_spawn: impl FnOnce() -> Result<(), String>,
) -> Result<Vec<u8>, String> {
    if !cfg!(unix) {
        return Err(
            "native worker process-group ownership is unavailable on this platform".to_string(),
        );
    }
    let worker = config
        .repo
        .join("scripts/memory_cell_native/native_worker.py");
    let launcher = config
        .repo
        .join("scripts/memory_cell_network/model_child.py");
    let verify = || -> Result<(), String> {
        for (path, pin) in [
            (&worker, &config.pins.worker_sha256),
            (&launcher, &config.pins.launcher_sha256),
        ] {
            let file = std::fs::File::open(path).map_err(|e| e.to_string())?;
            if Digest32::of_reader(file, 256 * 1024)
                .map_err(|e| e.to_string())?
                .to_string()
                != *pin
            {
                return Err(
                    "worker or parent-death launcher differs from retained bytes".to_string(),
                );
            }
        }
        Ok(())
    };
    verify()?;
    if cancellation.is_cancelled() {
        return Err("native owner is closed before worker startup".to_string());
    }
    let directory = config
        .receipt_directory
        .join(Digest32::of_bytes(&input).to_string());
    let mut directory_options = std::fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        directory_options.mode(0o700);
    }
    directory_options
        .create(&directory)
        .map_err(|e| e.to_string())?;
    write_receipt(&directory.join("request.json"), &input)?;
    let deadline = tokio::time::Instant::now() + Duration::from_millis(config.timeout_millis);
    let mut command = Command::new(&config.python);
    command
        .args(["-I", "-B"])
        .arg(&launcher)
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .arg(&worker)
        .env_clear()
        .envs(environment.into_iter().filter(|(key, _)| {
            key.to_str().is_some_and(|key| {
                RUNTIME_ENVIRONMENT
                    .iter()
                    .any(|allowed| key.eq_ignore_ascii_case(allowed))
            })
        }))
        .env("HF_HUB_OFFLINE", "1")
        .env("TRANSFORMERS_OFFLINE", "1")
        .env("HF_HUB_DISABLE_TELEMETRY", "1")
        .env("TOKENIZERS_PARALLELISM", "false")
        .env("OMP_NUM_THREADS", "2")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    // This controls ordinary descendants that retain the inherited group. It
    // is cleanup, not an OS sandbox or a claim about descendants that escape it.
    #[cfg(unix)]
    command.process_group(0);
    if cancellation.is_cancelled() {
        return Err("native owner is closed".to_string());
    }
    // Revalidate the actual current owner after pinned-file hashing and request
    // persistence. This observes current authority; it grants no future lease.
    before_spawn()?;
    if cancellation.is_cancelled() {
        return Err("native owner is closed".to_string());
    }
    let mut child = command.spawn().map_err(|e| e.to_string())?;
    let pid = child.id().ok_or("worker pid absent")?;
    let mut group = ProcessGroupGuard::new(pid);
    let mut stdin = child.stdin.take().ok_or("worker stdin absent")?;
    let mut stdout = child.stdout.take().ok_or("worker stdout absent")?;
    let mut stderr = child.stderr.take().ok_or("worker stderr absent")?;
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let mut written = false;
    let mut timed_out = false;
    // The one deadline covers writing, both bounded drains, and process exit.
    // Dropping these async pipe futures closes their handles below. No blocking
    // reader/writer thread is joined, even if an escaped child still owns a pipe.
    let completion = {
        let communicate = async {
            let stdin_completed = &mut written;
            let send = async move {
                stdin.write_all(&input).await?;
                // Closing the descriptor, rather than only flushing/shutting
                // down AsyncWrite, delivers EOF to a worker reading all input.
                drop(stdin);
                *stdin_completed = true;
                Ok::<_, std::io::Error>(())
            };
            let read_output = async {
                (&mut stdout)
                    .take(OUTPUT_LIMIT + 1)
                    .read_to_end(&mut output)
                    .await?;
                check_output_bound(output.len())
            };
            let read_errors = async {
                (&mut stderr)
                    .take(OUTPUT_LIMIT + 1)
                    .read_to_end(&mut errors)
                    .await?;
                check_output_bound(errors.len())
            };
            let (_, _, _, status) = tokio::try_join!(send, read_output, read_errors, child.wait())?;
            Ok::<_, std::io::Error>(status)
        };
        tokio::select! {
            biased;
            _ = cancellation.cancelled() => Err("native owner cancelled worker".to_string()),
            result = tokio::time::timeout_at(deadline, communicate) => match result {
                Ok(result) => result.map_err(|e| e.to_string()),
                Err(_) => {
                    timed_out = true;
                    Err("worker I/O or process deadline expired".to_string())
                }
            },
        }
    };
    drop(stdout);
    drop(stderr);
    // Also clean up descendants after a successful direct-child exit. A worker
    // does not gain background-process lifetime by closing its standard streams.
    let group_cleanup_error = group.terminate().err();
    let mut status = completion.as_ref().ok().copied();
    if status.is_none() {
        let _ = child.start_kill();
        if let Ok(Ok(reaped)) = tokio::time::timeout(REAP_TIMEOUT, child.wait()).await {
            status = Some(reaped);
        }
    }
    write_receipt(&directory.join("stdout.json"), &output)?;
    write_receipt(&directory.join("stderr.log"), &errors)?;
    let process = serde_json::json!({
        "pid": pid, "parent_pid": std::process::id(),
        "exit_code": status.and_then(|status| status.code()),
        "timed_out": timed_out, "owner_cancelled": cancellation.is_cancelled(),
        "stdin_completed": written, "stdout_bytes": output.len(), "stderr_bytes": errors.len(),
        "process_reaped": status.is_some(), "io_error": completion.as_ref().err(),
        "unix_process_group_cleanup_attempted": cfg!(unix),
        "process_group_error": group_cleanup_error,
    });
    write_receipt(
        &directory.join("process.json"),
        &serde_json::to_vec(&process).map_err(|e| e.to_string())?,
    )?;
    if completion.is_err()
        || group_cleanup_error.is_some()
        || cancellation.is_cancelled()
        || status.is_none_or(|status| !status.success())
        || !written
        || output.len() as u64 > OUTPUT_LIMIT
        || errors.len() as u64 > OUTPUT_LIMIT
    {
        return Err(format!(
            "worker failed: timeout={timed_out}, status={status:?}; bounded raw output retained in the host receipt directory"
        ));
    }
    let first_line = errors
        .split(|byte| *byte == b'\n')
        .next()
        .ok_or("parent-death receipt absent")?;
    let bootstrap: serde_json::Value =
        serde_json::from_slice(first_line).map_err(|e| e.to_string())?;
    if bootstrap["pid"] != pid
        || bootstrap["parent_pid"] != std::process::id()
        || bootstrap["expected_parent_pid"] != std::process::id()
        || (cfg!(target_os = "linux") && bootstrap["parent_death"]["status"] != "bound")
    {
        return Err("parent-death bootstrap differs from actual child".to_string());
    }
    verify()?;
    Ok(output)
}

fn check_output_bound(length: usize) -> std::io::Result<()> {
    if length as u64 > OUTPUT_LIMIT {
        Err(std::io::Error::other("worker output exceeds bound"))
    } else {
        Ok(())
    }
}

fn write_receipt(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    }
    options
        .open(path)
        .and_then(|mut file| file.write_all(bytes))
        .map_err(|e| e.to_string())
}

struct ProcessGroupGuard(Option<u32>);

impl ProcessGroupGuard {
    fn new(pid: u32) -> Self {
        Self(Some(pid))
    }

    fn terminate(&mut self) -> Result<(), String> {
        if let Some(pid) = self.0.take() {
            #[cfg(unix)]
            {
                let pid = i32::try_from(pid).map_err(|e| e.to_string())?;
                // SAFETY: the child created its own group with process_group(0).
                // A negative PID targets that group and never this daemon's group.
                if unsafe { libc::kill(-pid, libc::SIGKILL) } != 0 {
                    let error = std::io::Error::last_os_error();
                    if error.raw_os_error() != Some(libc::ESRCH) {
                        return Err(error.to_string());
                    }
                }
            }
            #[cfg(not(unix))]
            let _ = pid;
        }
        Ok(())
    }
}

impl Drop for ProcessGroupGuard {
    fn drop(&mut self) {
        let _ = self.terminate();
    }
}

#[cfg(all(test, unix))]
#[path = "native_memory_process_tests.rs"]
mod tests;

#[cfg(all(test, not(unix)))]
#[path = "native_memory_process_platform_tests.rs"]
mod platform_tests;
