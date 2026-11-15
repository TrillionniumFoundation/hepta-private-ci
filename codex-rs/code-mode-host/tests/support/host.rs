use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::BufReader;
use tokio::process::Child;
use tokio::process::Command;
use tokio::time::timeout;

#[cfg(target_os = "macos")]
#[path = "startup_observation.rs"]
mod startup_observation;

pub(crate) struct HostHarness {
    pub(crate) _child: Child,
    pub(crate) endpoint: String,
}

impl HostHarness {
    pub(crate) async fn start(listen_url: &str) -> Result<Self> {
        let host_program = codex_utils_cargo_bin::cargo_bin("codex-code-mode-host")?;
        let spawn_started = Instant::now();
        let mut child = Command::new(&host_program)
            .args(["--listen", listen_url])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(/*kill_on_drop*/ true)
            .spawn()
            .context("failed to start code-mode host")?;
        let spawn_elapsed = spawn_started.elapsed();
        let stdout = child
            .stdout
            .take()
            .context("code-mode host stdout was not captured")?;
        let readiness_started = Instant::now();
        let startup = timeout(
            Duration::from_secs(/*secs*/ 10),
            BufReader::new(stdout).lines().next_line(),
        )
        .await;
        let endpoint = match startup {
            Ok(endpoint) => endpoint?,
            Err(error) => {
                let status = child.try_wait().context("inspect code-mode host status")?;
                let readiness_elapsed = readiness_started.elapsed();
                let mut bytes = [0_u8; 4096];
                let diagnostics = match child.stderr.as_mut() {
                    Some(stderr) => {
                        // Poll the pipe after the readiness deadline without consuming it
                        // on success; existing tests retain ownership of child.stderr.
                        match timeout(Duration::from_millis(/*millis*/ 100), stderr.read(&mut bytes)).await {
                            Ok(Ok(count)) => String::from_utf8_lossy(&bytes[..count]).into_owned(),
                            Ok(Err(error)) => format!("stderr read failed: {error}"),
                            Err(_) => "no stderr ready within diagnostic read budget".to_string(),
                        }
                    }
                    None => "stderr was not captured".to_string(),
                };
                #[cfg(target_os = "macos")]
                if status.is_none() {
                    let observation = startup_observation::observe_failed_child(&mut child).await;
                    eprintln!("code-mode host failed-readiness observation:\n{observation}");
                }
                return Err(error).with_context(|| {
                    format!(
                        "timed out waiting for code-mode host endpoint: program={}, status={status:?}, spawn_elapsed={spawn_elapsed:?}, readiness_elapsed={readiness_elapsed:?}, stderr_prefix={diagnostics:?}",
                        host_program.display()
                    )
                });
            }
        }
        .context("code-mode host exited before publishing its endpoint")?;
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
