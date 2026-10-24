//! Bounded, fresh local process invocation; no retries or model persistence.

use std::io::Read;
use std::io::Write;
use std::process::Command;
use std::process::Stdio;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;

use crate::native_memory_types::NativeMemoryModelConfigV1;

pub(super) fn execute(
    config: &NativeMemoryModelConfigV1,
    input: Vec<u8>,
    cancellation: &tokio_util::sync::CancellationToken,
) -> Result<Vec<u8>, String> {
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
    let directory = config
        .receipt_directory
        .join(Digest32::of_bytes(&input).to_string());
    std::fs::create_dir(&directory).map_err(|e| e.to_string())?;
    std::fs::write(directory.join("request.json"), &input).map_err(|e| e.to_string())?;
    let deadline = Instant::now() + Duration::from_millis(config.timeout_millis);
    let mut child = Command::new(&config.python)
        .args(["-I", "-B"])
        .arg(&launcher)
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .arg(&worker)
        .env("HF_HUB_OFFLINE", "1")
        .env("TRANSFORMERS_OFFLINE", "1")
        .env("TOKENIZERS_PARALLELISM", "false")
        .env("OMP_NUM_THREADS", "2")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;
    let mut stdin = child.stdin.take().ok_or("worker stdin absent")?;
    let stdout = child.stdout.take().ok_or("worker stdout absent")?;
    let stderr = child.stderr.take().ok_or("worker stderr absent")?;
    let out = thread::spawn(move || {
        let mut v = Vec::new();
        stdout.take(65_537).read_to_end(&mut v).map(|_| v)
    });
    let err = thread::spawn(move || {
        let mut v = Vec::new();
        stderr.take(65_537).read_to_end(&mut v).map(|_| v)
    });
    // Writing a full pipe is included in the same timeout as model execution.
    let write = thread::spawn(move || stdin.write_all(&input));
    let mut timed_out = false;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) if Instant::now() < deadline && !cancellation.is_cancelled() => {
                thread::sleep(Duration::from_millis(10))
            }
            Ok(None) => {
                timed_out = Instant::now() >= deadline;
                let _ = child.kill();
                break child.wait();
            }
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                break Err(error);
            }
        }
    }
    .map_err(|e| e.to_string())?;
    let output = out
        .join()
        .map_err(|_| "worker stdout reader panic")?
        .map_err(|e| e.to_string())?;
    let errors = err
        .join()
        .map_err(|_| "worker stderr reader panic")?
        .map_err(|e| e.to_string())?;
    let written = write.join().map_err(|_| "worker stdin writer panic")?;
    std::fs::write(directory.join("stdout.json"), &output).map_err(|e| e.to_string())?;
    std::fs::write(directory.join("stderr.log"), &errors).map_err(|e| e.to_string())?;
    let process = serde_json::json!({"pid": child.id(), "parent_pid": std::process::id(), "exit_code": status.code(), "timed_out": timed_out, "owner_cancelled": cancellation.is_cancelled(), "stdin_completed": written.is_ok(), "stdout_bytes": output.len(), "stderr_bytes": errors.len()});
    std::fs::write(
        directory.join("process.json"),
        serde_json::to_vec(&process).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    if timed_out
        || !status.success()
        || written.is_err()
        || output.len() > 65_536
        || errors.len() > 65_536
    {
        return Err(format!(
            "worker failed: timeout={timed_out}, status={status}; bounded raw output retained in the host receipt directory"
        ));
    }
    let first_line = errors
        .split(|byte| *byte == b'\n')
        .next()
        .ok_or("parent-death receipt absent")?;
    let bootstrap: serde_json::Value =
        serde_json::from_slice(first_line).map_err(|e| e.to_string())?;
    if bootstrap["pid"] != child.id()
        || bootstrap["parent_pid"] != std::process::id()
        || bootstrap["expected_parent_pid"] != std::process::id()
        || (cfg!(target_os = "linux") && bootstrap["parent_death"]["status"] != "bound")
    {
        return Err("parent-death bootstrap differs from actual child".to_string());
    }
    verify()?;
    Ok(output)
}

#[cfg(all(test, unix))]
#[path = "native_memory_process_tests.rs"]
mod tests;
