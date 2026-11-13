use std::process::Stdio;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
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
        let mut stdout = BufReader::new(stdout).lines();
        let endpoint = async {
            timeout(Duration::from_secs(/*secs*/ 10), stdout.next_line())
                .await
                .context("timed out waiting for code-mode host endpoint")??
                .context("code-mode host exited before publishing its endpoint")
        }
        .await;
        let endpoint = match endpoint {
            Ok(endpoint) => endpoint,
            Err(error) => return Err(error.context(startup_diagnostics(&mut child).await)),
        };
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

pub(crate) async fn startup_diagnostics(child: &mut Child) -> String {
    let pid = child.id();
    let status = match child.try_wait() {
        Ok(Some(status)) => format!("exited: {status}"),
        Ok(None) => "running".to_string(),
        Err(error) => format!("unavailable: {error}"),
    };
    // Read one bounded chunk only after startup has failed. Do not wait for EOF
    // or change the child's existing kill-on-drop cleanup.
    let stderr = match child.stderr.as_mut() {
        Some(stderr) => {
            let mut buffer = [0_u8; 4096];
            match timeout(
                Duration::from_millis(/*millis*/ 100),
                stderr.read(&mut buffer),
            )
            .await
            {
                Ok(Ok(bytes_read)) => {
                    let text = String::from_utf8_lossy(&buffer[..bytes_read]);
                    format!("first stderr read ({bytes_read} bytes, 4096 byte cap): {text:?}")
                }
                Ok(Err(error)) => format!("stderr read failed: {error}"),
                Err(_) => "no stderr available within 100ms".to_string(),
            }
        }
        None => "stderr was not captured".to_string(),
    };
    format!("code-mode host startup failed: pid={pid:?}, status={status}; {stderr}")
}
