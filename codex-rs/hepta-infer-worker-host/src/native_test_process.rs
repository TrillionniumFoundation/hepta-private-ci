//! Isolate real Agentd/App Server hosts without resetting the product home binding.

use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;

use codex_utils_pty::StdChildCustody;
use tokio::time::Instant;

use super::Result;

const HOST_CASE_ENV: &str = "HEPTA_NATIVE_ISOLATED_HOST_CASE";
const HOST_DONE_ENV: &str = "HEPTA_NATIVE_ISOLATED_HOST_DONE";
const HOST_TIMEOUT: Duration = Duration::from_secs(50);

pub(super) struct HostCompletion {
    path: PathBuf,
    test_name: &'static str,
}

impl HostCompletion {
    pub(super) fn complete(self) -> Result<()> {
        std::fs::write(self.path, self.test_name.as_bytes())?;
        Ok(())
    }
}

/// The outer harness waits; only the exact child test may initialize a host.
pub(super) async fn isolate_host(test_name: &'static str) -> Result<Option<HostCompletion>> {
    if let Some(marker) = std::env::var_os(HOST_CASE_ENV) {
        if marker != test_name {
            return Err("isolated native host marker does not match the selected test".into());
        }
        let path = PathBuf::from(
            std::env::var_os(HOST_DONE_ENV)
                .ok_or("isolated native host completion path is missing")?,
        );
        if !path.is_absolute() {
            return Err("isolated native host completion path must be absolute".into());
        }
        return Ok(Some(HostCompletion { path, test_name }));
    }

    let directory = tempfile::Builder::new().prefix("hnt-").tempdir()?;
    let host_directory = directory.path().canonicalize()?;
    let completion_path = host_directory.join("complete");
    let log_path = host_directory.join("host.log");
    let log = std::fs::File::create(&log_path)?;
    // The exact test runs in a fresh host process. core_test_support also
    // registers the production arg0 helpers used by the embedded App Server.
    let mut command = Command::new(std::env::current_exe()?);
    command
        .args(["--exact", test_name, "--nocapture"])
        .env(HOST_CASE_ENV, test_name)
        .env(HOST_DONE_ENV, &completion_path)
        .stdout(Stdio::from(log.try_clone()?))
        .stderr(Stdio::from(log));
    let mut process = StdChildCustody::spawn(&mut command)?;
    let deadline = Instant::now() + HOST_TIMEOUT;
    let status = loop {
        if let Some(status) = process.try_wait()? {
            break status;
        }
        if Instant::now() >= deadline {
            return Err(format!(
                "isolated native host {test_name} exceeded its deadline: {}",
                std::fs::read_to_string(&log_path)?,
            )
            .into());
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    };
    if !status.success() {
        return Err(format!(
            "isolated native host {test_name} failed ({status}): {}",
            std::fs::read_to_string(&log_path)?,
        )
        .into());
    }
    if std::fs::read(&completion_path).ok().as_deref() != Some(test_name.as_bytes()) {
        return Err(format!(
            "isolated native host {test_name} exited without completing its assertions: {}",
            std::fs::read_to_string(&log_path)?,
        )
        .into());
    }
    Ok(None)
}
