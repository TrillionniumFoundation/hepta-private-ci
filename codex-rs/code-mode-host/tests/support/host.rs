use std::process::Stdio;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use futures::FutureExt;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::BufReader;
use tokio::process::Child;
use tokio::process::Command;
use tokio::time::timeout;

pub(crate) struct HostHarness {
    pub(crate) _child: Child,
    pub(crate) endpoint: String,
}

impl HostHarness {
    pub(crate) async fn start(listen_url: &str) -> Result<Self> {
        let host_program = codex_utils_cargo_bin::cargo_bin("codex-code-mode-host")?;
        let mut child = Command::new(&host_program)
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
        let startup = timeout(
            Duration::from_secs(/*secs*/ 10),
            BufReader::new(stdout).lines().next_line(),
        )
        .await;
        let endpoint = match startup {
            Ok(endpoint) => endpoint?,
            Err(error) => {
                let status = child.try_wait().context("inspect code-mode host status")?;
                let mut bytes = [0_u8; 4096];
                let diagnostics = match child.stderr.as_mut() {
                    Some(stderr) => match stderr.read(&mut bytes).now_or_never() {
                        Some(Ok(count)) => String::from_utf8_lossy(&bytes[..count]).into_owned(),
                        Some(Err(error)) => format!("stderr read failed: {error}"),
                        None => "no stderr ready".to_string(),
                    },
                    None => "stderr was not captured".to_string(),
                };
                return Err(error).with_context(|| {
                    format!(
                        "timed out waiting for code-mode host endpoint: program={}, status={status:?}, stderr={diagnostics:?}",
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
