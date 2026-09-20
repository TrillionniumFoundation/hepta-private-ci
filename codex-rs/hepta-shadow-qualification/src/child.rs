use std::path::Path;
use std::process::Stdio;
use std::time::Duration;

use serde::Serialize;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::io::BufReader;
use tokio::process::Child;
use tokio::process::ChildStdin;
use tokio::process::ChildStdout;
use tokio::process::Command;
use tokio::task::JoinHandle;

use crate::FrozenProductBinary;
use crate::QualificationError;
use crate::Surface;
use crate::SurfaceRuntimeLayout;
use crate::digest::sha256;
use crate::durable::create_or_verify_private_directory;
use crate::durable::sync_directory;
use crate::durable::write_private_new;
use crate::request::canonical_json;

const MAX_PROTOCOL_LINE_BYTES: usize = 1024 * 1024;
const MAX_STORED_STDERR_BYTES: usize = 1024 * 1024;

pub struct ProductChild {
    child: Child,
    inbound_sequence: u64,
    protocol_root: std::path::PathBuf,
    stderr_task: Option<JoinHandle<Result<StderrOutcome, QualificationError>>>,
    stdin: Option<ChildStdin>,
    stdout: Option<BufReader<ChildStdout>>,
    surface: Surface,
    timeout: Duration,
}

impl ProductChild {
    pub fn spawn(
        product: &FrozenProductBinary,
        layout: &SurfaceRuntimeLayout,
        run_root: impl AsRef<Path>,
        timeout: Duration,
    ) -> Result<Self, QualificationError> {
        FrozenProductBinary::verify(product.path())?;
        if !layout.config().is_file() {
            return Err(state("surface config must be written before child spawn"));
        }
        let protocol_root = run_root.as_ref().join("protocol");
        create_or_verify_private_directory(&protocol_root)?;
        let args: &[&str] = match layout.surface() {
            Surface::AppServer => &["app-server", "--stdio", "--strict-config"],
            Surface::Mcp => &["mcp-server", "--strict-config"],
        };
        #[cfg(unix)]
        let mut command = {
            let mut command = Command::new("/bin/sh");
            command
                .args(["-c", "umask 077; exec \"$@\""])
                .arg("hepta-shadow-product")
                .arg(product.path());
            command
        };
        #[cfg(not(unix))]
        let mut command = Command::new(product.path());
        command
            .args(args)
            .current_dir(layout.work())
            .env_clear()
            .envs(layout.environment())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        if layout.surface() == Surface::AppServer {
            command.env("CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED", "1");
        }
        let mut child = command.spawn()?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| state("child stdin pipe is unavailable"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| state("child stdout pipe is unavailable"))?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| state("child stderr pipe is unavailable"))?;
        let stderr_path = protocol_root.join(format!("{}-stderr.log", layout.surface().as_str()));
        let stderr_task = tokio::spawn(capture_stderr(stderr, stderr_path));
        Ok(Self {
            child,
            inbound_sequence: 0,
            protocol_root,
            stderr_task: Some(stderr_task),
            stdin: Some(stdin),
            stdout: Some(BufReader::new(stdout)),
            surface: layout.surface(),
            timeout,
        })
    }

    pub fn take_stdin(&mut self) -> Result<ChildStdin, QualificationError> {
        self.stdin
            .take()
            .ok_or_else(|| state("child stdin was already taken"))
    }

    pub async fn read_response(&mut self, expected_id: u64) -> Result<Value, QualificationError> {
        loop {
            let message = self.read_message().await?;
            if message.get("id").and_then(Value::as_u64) == Some(expected_id) {
                if message.get("error").is_some() {
                    return Err(invalid(format!(
                        "child returned protocol error for id {expected_id}"
                    )));
                }
                return Ok(message);
            }
        }
    }

    pub async fn read_notification(&mut self, method: &str) -> Result<Value, QualificationError> {
        loop {
            let message = self.read_message().await?;
            if message.get("method").and_then(Value::as_str) == Some(method)
                && message.get("id").is_none()
            {
                return Ok(message);
            }
        }
    }

    pub async fn shutdown(mut self) -> Result<ChildOutcome, QualificationError> {
        drop(self.stdin.take());
        let stdout = self
            .stdout
            .take()
            .ok_or_else(|| state("child stdout pipe is unavailable"))?;
        let protocol_root = self.protocol_root.clone();
        let surface = self.surface;
        let sequence = self.inbound_sequence;
        let mut stdout_task =
            tokio::spawn(
                async move { drain_stdout(stdout, protocol_root, surface, sequence).await },
            );
        let status = match tokio::time::timeout(self.timeout, self.child.wait()).await {
            Ok(status) => status?,
            Err(_) => {
                self.child.start_kill()?;
                tokio::time::timeout(self.timeout, self.child.wait())
                    .await
                    .map_err(|_| state("child did not exit after bounded kill"))??
            }
        };
        let tail_count = match tokio::time::timeout(self.timeout, &mut stdout_task).await {
            Ok(result) => {
                result.map_err(|error| state(format!("stdout drain task failed: {error}")))??
            }
            Err(_) => {
                stdout_task.abort();
                return Err(state("timed out draining child protocol tail"));
            }
        };
        self.inbound_sequence = self.inbound_sequence.saturating_add(tail_count);
        let mut stderr_task = self
            .stderr_task
            .take()
            .ok_or_else(|| state("stderr capture task is unavailable"))?;
        let stderr = match tokio::time::timeout(self.timeout, &mut stderr_task).await {
            Ok(result) => {
                result.map_err(|error| state(format!("stderr task failed: {error}")))??
            }
            Err(_) => {
                stderr_task.abort();
                return Err(state("timed out draining child stderr"));
            }
        };
        if !status.success() {
            return Err(state(format!("product child exited with {status}")));
        }
        Ok(ChildOutcome {
            exit_code: status.code(),
            inbound_message_count: self.inbound_sequence,
            stderr_sha256: stderr.sha256,
            stderr_size_bytes: stderr.size_bytes,
            stderr_truncated: stderr.truncated,
        })
    }

    pub async fn abort(mut self) -> Result<(), QualificationError> {
        drop(self.stdin.take());
        self.child.start_kill()?;
        let _ = tokio::time::timeout(self.timeout, self.child.wait()).await;
        if let Some(mut task) = self.stderr_task.take()
            && tokio::time::timeout(self.timeout, &mut task).await.is_err()
        {
            task.abort();
        }
        Ok(())
    }

    async fn read_message(&mut self) -> Result<Value, QualificationError> {
        let mut wire = Vec::new();
        let stdout = self
            .stdout
            .as_mut()
            .ok_or_else(|| state("child stdout pipe is unavailable"))?;
        let count = tokio::time::timeout(self.timeout, stdout.read_until(b'\n', &mut wire))
            .await
            .map_err(|_| state("timed out reading child protocol line"))??;
        if count == 0 {
            return Err(state(
                "child stdout closed before expected protocol message",
            ));
        }
        self.inbound_sequence += 1;
        persist_inbound(
            &self.protocol_root,
            self.surface,
            self.inbound_sequence,
            &wire,
        )
    }
}

async fn drain_stdout(
    mut stdout: BufReader<ChildStdout>,
    protocol_root: std::path::PathBuf,
    surface: Surface,
    mut sequence: u64,
) -> Result<u64, QualificationError> {
    let initial_sequence = sequence;
    loop {
        let mut wire = Vec::new();
        if stdout.read_until(b'\n', &mut wire).await? == 0 {
            return Ok(sequence.saturating_sub(initial_sequence));
        }
        sequence = sequence.saturating_add(1);
        persist_inbound(&protocol_root, surface, sequence, &wire)?;
    }
}

impl Drop for ProductChild {
    fn drop(&mut self) {
        let _ = self.child.start_kill();
        if let Some(task) = &self.stderr_task {
            task.abort();
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ChildOutcome {
    exit_code: Option<i32>,
    inbound_message_count: u64,
    stderr_sha256: String,
    stderr_size_bytes: u64,
    stderr_truncated: bool,
}

impl ChildOutcome {
    pub fn exit_code(&self) -> Option<i32> {
        self.exit_code
    }

    pub fn inbound_message_count(&self) -> u64 {
        self.inbound_message_count
    }

    pub fn stderr_sha256(&self) -> &str {
        &self.stderr_sha256
    }

    pub fn stderr_size_bytes(&self) -> u64 {
        self.stderr_size_bytes
    }

    pub fn stderr_truncated(&self) -> bool {
        self.stderr_truncated
    }
}

#[derive(Serialize)]
struct InboundReceipt<'a> {
    authority: bool,
    direction: &'static str,
    enforce: bool,
    outbound: bool,
    promotion: bool,
    raw_sha256: &'a str,
    raw_size_bytes: usize,
    schema: &'static str,
    schema_version: u32,
    sequence: u64,
    surface: Surface,
}

pub(crate) fn persist_inbound(
    protocol_root: &Path,
    surface: Surface,
    sequence: u64,
    wire: &[u8],
) -> Result<Value, QualificationError> {
    let stem = format!("{}-inbound-{sequence:06}", surface.as_str());
    write_private_new(&protocol_root.join(format!("{stem}.raw.jsonl")), wire)?;
    let raw_sha256 = sha256(wire);
    let receipt = InboundReceipt {
        authority: false,
        direction: "inbound_post_receive",
        enforce: false,
        outbound: false,
        promotion: false,
        raw_sha256: &raw_sha256,
        raw_size_bytes: wire.len(),
        schema: "hepta_shadow_qualification_protocol_artifact_v2",
        schema_version: 2,
        sequence,
        surface,
    };
    write_private_new(
        &protocol_root.join(format!("{stem}.receipt.json")),
        &canonical_json(&receipt)?,
    )?;
    sync_directory(protocol_root)?;
    if wire.len() < 2
        || wire.len() > MAX_PROTOCOL_LINE_BYTES
        || wire.last() != Some(&b'\n')
        || wire[..wire.len() - 1]
            .iter()
            .any(|byte| matches!(byte, b'\n' | b'\r'))
    {
        return Err(invalid(
            "child protocol message is not one bounded JSON line",
        ));
    }
    serde_json::from_slice(&wire[..wire.len() - 1])
        .map_err(|error| invalid(format!("invalid child protocol JSON: {error}")))
}

pub(crate) struct StderrOutcome {
    pub(crate) sha256: String,
    pub(crate) size_bytes: u64,
    pub(crate) truncated: bool,
}

pub(crate) async fn capture_stderr<R>(
    mut reader: R,
    path: std::path::PathBuf,
) -> Result<StderrOutcome, QualificationError>
where
    R: AsyncRead + Unpin,
{
    let mut hasher = Sha256::new();
    let mut stored = Vec::new();
    let mut size_bytes = 0_u64;
    let mut chunk = [0_u8; 8_192];
    loop {
        let count = reader.read(&mut chunk).await?;
        if count == 0 {
            break;
        }
        hasher.update(&chunk[..count]);
        size_bytes = size_bytes.saturating_add(count as u64);
        let remaining = MAX_STORED_STDERR_BYTES.saturating_sub(stored.len());
        stored.extend_from_slice(&chunk[..count.min(remaining)]);
    }
    write_private_new(&path, &stored)?;
    Ok(StderrOutcome {
        sha256: format!("{:x}", hasher.finalize()),
        size_bytes,
        truncated: size_bytes > stored.len() as u64,
    })
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}

fn state(message: impl Into<String>) -> QualificationError {
    QualificationError::State(message.into())
}
