use std::process::Stdio;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
#[cfg(not(unix))]
use futures::FutureExt;
use tokio::io::AsyncBufReadExt;
#[cfg(not(unix))]
use tokio::io::AsyncReadExt;
use tokio::io::BufReader;
use tokio::process::Child;
use tokio::process::Command;
use tokio::time::timeout;

#[cfg(unix)]
#[path = "startup_pipe.rs"]
mod startup_pipe;

pub(crate) struct HostHarness {
    pub(crate) _child: Child,
    pub(crate) endpoint: String,
}

impl HostHarness {
    pub(crate) async fn start(listen_url: &str) -> Result<Self> {
        let host_program = codex_utils_cargo_bin::cargo_bin("codex-code-mode-host")?;
        let mut child = Command::new(host_program)
            .args(["--listen", listen_url])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(/*kill_on_drop*/ true)
            .spawn()
            .context("failed to start code-mode host")?;
        let stdout = child
            .stdout
            .take()
            .context("code-mode host stdout was not captured")?;
        let endpoint = async {
            timeout(
                Duration::from_secs(/*secs*/ 10),
                BufReader::new(stdout).lines().next_line(),
            )
            .await
            .context("timed out waiting for code-mode host endpoint")??
            .context("code-mode host exited before publishing its endpoint")
        }
        .await
        .with_context(|| startup_failure_context(&mut child))?;
        let expected_scheme = if listen_url.starts_with("grpc://") {
            "http"
        } else {
            "ws"
        };
        if !endpoint.starts_with(&format!("{expected_scheme}://127.0.0.1:")) {
            anyhow::bail!("unexpected code-mode host endpoint `{endpoint}`");
        }

        Ok(Self {
            _child: child,
            endpoint,
        })
    }
}

/// Observe an already failed startup without extending its deadline or waiting
/// for the child. The child status and stderr are separate observations.
pub(crate) fn startup_failure_context(child: &mut Child) -> String {
    let state = match child.try_wait() {
        Ok(Some(status)) => format!("exited({status})"),
        Ok(None) => "running".to_string(),
        Err(error) => format!(
            "status_error(kind={:?}, os={:?})",
            error.kind(),
            error.raw_os_error(),
        ),
    };
    #[cfg(unix)]
    let stderr = match child.stderr.as_mut() {
        Some(stderr) => startup_pipe::observe(stderr),
        None => "not_captured".to_string(),
    };
    #[cfg(not(unix))]
    let mut buffer = [0_u8; 4096];
    #[cfg(not(unix))]
    let stderr = match child.stderr.as_mut() {
        Some(stderr) => match stderr.read(&mut buffer).now_or_never() {
            Some(Ok(bytes)) => format!(
                "single_read_bytes={bytes}, capacity={}, prefix={:?}",
                buffer.len(),
                String::from_utf8_lossy(&buffer[..bytes]),
            ),
            Some(Err(error)) => format!(
                "read_error(kind={:?}, os={:?})",
                error.kind(),
                error.raw_os_error(),
            ),
            None => "not_ready_at_observation".to_string(),
        },
        None => "not_captured".to_string(),
    };
    format!("code-mode host startup observation: child={state}; stderr={stderr}")
}
