use std::future::poll_fn;
use std::pin::Pin;
use std::process::Stdio;
use std::task::Poll;
use std::time::Duration;

use anyhow::Context;
use anyhow::Error;
use anyhow::Result;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncRead;
use tokio::io::BufReader;
use tokio::io::ReadBuf;
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
        let endpoint = timeout(
            Duration::from_secs(/*secs*/ 10),
            BufReader::new(stdout).lines().next_line(),
        )
        .await
        .context("timed out waiting for code-mode host endpoint")
        .and_then(|line| line.map_err(Error::from))
        .and_then(|line| line.context("code-mode host exited before publishing its endpoint"));
        let endpoint = match endpoint {
            Ok(endpoint) => endpoint,
            Err(error) => {
                return Err(with_startup_failure_diagnostics(error, &mut child).await);
            }
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

// Observe only an already-failed startup. Successful callers retain the original
// stderr handle untouched, including the malformed-frame diagnostic test.
pub(crate) async fn with_startup_failure_diagnostics(error: Error, child: &mut Child) -> Error {
    let child_id = child.id();
    let (child_status, wait_error) = match child.try_wait() {
        Ok(Some(status)) => (Some(status.to_string()), None),
        Ok(None) => (None, None),
        Err(error) => (None, Some((error.kind(), error.raw_os_error()))),
    };
    let mut stderr_bytes = [0_u8; 8 * 1024];
    let mut stderr_length = 0;
    let (stderr_observation, stderr_error) = if let Some(stderr) = child.stderr.as_mut() {
        // Each poll is nonblocking and this closure always returns Ready. The
        // fixed byte/read bounds add no wait, retry, or new startup deadline.
        poll_fn(|context| {
            for _ in 0..16 {
                if stderr_length == stderr_bytes.len() {
                    return Poll::Ready(("capacity", None));
                }
                let end = (stderr_length + 512).min(stderr_bytes.len());
                let mut read = ReadBuf::new(&mut stderr_bytes[stderr_length..end]);
                match Pin::new(&mut *stderr).poll_read(context, &mut read) {
                    Poll::Ready(Ok(())) => {
                        let read_length = read.filled().len();
                        if read_length == 0 {
                            return Poll::Ready(("eof", None));
                        }
                        stderr_length += read_length;
                    }
                    Poll::Ready(Err(error)) => {
                        return Poll::Ready((
                            "read_error",
                            Some((error.kind(), error.raw_os_error())),
                        ));
                    }
                    Poll::Pending => return Poll::Ready(("not_ready", None)),
                }
            }
            Poll::Ready(("read_bound", None))
        })
        .await
    } else {
        ("not_captured", None)
    };
    // Arbitrary stderr, paths, arguments, and environment values are not emitted.
    // Markers report observed fixed substrings, not an inferred root cause.
    let stderr_lower = stderr_bytes[..stderr_length].to_ascii_lowercase();
    let known_markers: &[(&str, &[u8])] = &[
        ("dynamic_loader", b"dyld"),
        ("library_not_loaded", b"library not loaded"),
        ("symbol_not_found", b"symbol not found"),
        ("unsupported_architecture", b"bad cpu type"),
        ("executable_format", b"exec format error"),
        ("permission_denied", b"permission denied"),
        ("operation_not_permitted", b"operation not permitted"),
        ("address_in_use", b"address already in use"),
        ("address_unavailable", b"can't assign requested address"),
        ("open_file_limit", b"too many open files"),
        ("resource_unavailable", b"resource temporarily unavailable"),
        ("panic", b"panicked at"),
    ];
    let stderr_markers = known_markers
        .iter()
        .filter_map(|(marker, needle)| {
            stderr_lower
                .windows(needle.len())
                .any(|bytes| bytes == *needle)
                .then_some(*marker)
        })
        .collect::<Vec<_>>();
    error.context(format!(
        "code-mode host startup observation: child_id={child_id:?}, child_status={child_status:?}, wait_error={wait_error:?}, stderr_bytes={stderr_length}, stderr_observation={stderr_observation}, stderr_error={stderr_error:?}, stderr_markers={stderr_markers:?}"
    ))
}
