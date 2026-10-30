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
        let endpoint = async {
            let mut frame = Vec::new();
            let mut reader = BufReader::new(stdout).take(4096);
            timeout(
                Duration::from_secs(/*secs*/ 10),
                reader.read_until(b'\n', &mut frame),
            )
            .await
            .context("timed out waiting for code-mode host endpoint")??;
            anyhow::ensure!(
                !frame.is_empty(),
                "code-mode host exited before publishing its endpoint"
            );
            anyhow::ensure!(
                frame.ends_with(b"\n"),
                "code-mode host endpoint was incomplete or exceeded 4096 bytes"
            );
            let endpoint = std::str::from_utf8(&frame)
                .context("code-mode host endpoint was not UTF-8")?
                .trim()
                .to_string();
            let expected_scheme = if listen_url.starts_with("grpc://") {
                "http"
            } else {
                "ws"
            };
            anyhow::ensure!(
                endpoint.starts_with(&format!("{expected_scheme}://127.0.0.1:")),
                "unexpected code-mode host endpoint scheme or authority"
            );
            Ok::<_, anyhow::Error>(endpoint)
        }
        .await;
        let endpoint = match endpoint {
            Ok(endpoint) => endpoint,
            Err(error) => {
                let before = match child.try_wait() {
                    Ok(Some(status)) => format!("exited: {status}"),
                    Ok(None) => "running".to_string(),
                    Err(error) => format!("unavailable: {:?}", error.kind()),
                };
                let kill = child.start_kill().map_err(|error| error.kind());
                let after = match timeout(Duration::from_secs(1), child.wait()).await {
                    Ok(Ok(status)) => format!("reaped: {status}"),
                    Ok(Err(error)) => format!("wait error: {:?}", error.kind()),
                    Err(_) => "reap timed out; kill_on_drop remains active".to_string(),
                };
                let mut stderr = Vec::new();
                let stderr_read = if let Some(stream) = child.stderr.take() {
                    match timeout(
                        Duration::from_millis(250),
                        stream.take(8192).read_to_end(&mut stderr),
                    )
                    .await
                    {
                        Ok(Ok(_)) => "complete".to_string(),
                        Ok(Err(error)) => format!("read error: {:?}", error.kind()),
                        Err(_) => "timed out".to_string(),
                    }
                } else {
                    "not captured".to_string()
                };
                // Emit only fixed markers, never arbitrary stderr or inherited
                // environment values. Keep successful stderr ownership unchanged.
                let stderr_text = String::from_utf8_lossy(&stderr);
                let markers = [
                    "codex-code-mode-host listening on",
                    "failed to bind code-mode",
                    "failed to publish code-mode",
                    "invalid websocket --listen URL",
                    "invalid gRPC --listen URL",
                    "unsupported --listen URL",
                    "panicked at",
                    "Error:",
                ]
                .into_iter()
                .filter(|marker| stderr_text.contains(*marker))
                .collect::<Vec<_>>();
                return Err(error.context(format!(
                    "code-mode host startup diagnostics: before={before}; kill={kill:?}; \
                     after={after}; stderr_bytes={}; stderr_reached_cap={}; \
                     stderr_read={stderr_read}; stderr_markers={markers:?}",
                    stderr.len(),
                    stderr.len() == 8192,
                )));
            }
        };

        Ok(Self {
            _child: child,
            endpoint,
        })
    }
}
