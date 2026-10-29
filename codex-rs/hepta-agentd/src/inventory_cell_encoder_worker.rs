//! One serialized, persistent MiniLM session behind a bounded embedding port.
//! Cancellation drops the in-flight child; no trailing response is reused.

use std::pin::Pin;
use std::process::Stdio;
use std::sync::atomic::{AtomicU64, Ordering};
use std::task::Poll;
use std::time::Instant;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use serde::Serialize;
use tokio::io::{AsyncBufRead, AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::Mutex;
use tokio::task::JoinHandle;

#[path = "inventory_cell_encoder_config.rs"]
mod config;
#[path = "inventory_cell_encoder_wire.rs"]
mod wire;
pub use config::InventoryCellEncoderWorkerConfigV1;
use wire::{Bound, MAX_REQUEST, MAX_RESPONSE, Ready};

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct InventoryCellEncoderWorkerMetricsV1 {
    pub attempted_requests: u64,
    pub validated_responses: u64,
    pub truncated_responses: u64,
    pub process_starts: u64,
    pub stdin_bytes: u64,
    pub stdout_bytes: u64,
    pub reported_cpu_nanoseconds: u64,
    pub reported_wall_nanoseconds: u64,
    pub host_request_nanoseconds: u64,
    pub startup_nanoseconds: u64,
}
#[derive(Default)]
struct Counters {
    attempts: AtomicU64, responses: AtomicU64, truncated: AtomicU64, starts: AtomicU64,
    stdin: AtomicU64, stdout: AtomicU64, cpu: AtomicU64, wall: AtomicU64, host: AtomicU64,
    startup: AtomicU64, sequence: AtomicU64,
}

/// Prewarm one instance at node startup and share its `Arc` across all small
/// semantic heads.  This type never creates an encoder per cell or per query.
pub struct InventoryCellEncoderWorkerV1 {
    config: InventoryCellEncoderWorkerConfigV1,
    session: Mutex<Option<Session>>,
    counters: Counters,
}

impl InventoryCellEncoderWorkerV1 {
    pub async fn start(config: InventoryCellEncoderWorkerConfigV1) -> Result<Self, String> {
        let started = Instant::now();
        let worker = Self { config, session: Mutex::new(None), counters: Counters::default() };
        let session = tokio::time::timeout(worker.config.startup_timeout, worker.spawn()).await
            .map_err(|_| "semantic encoder prewarm timed out")??;
        *worker.session.lock().await = Some(session);
        worker.counters.startup.store(nanos(started), Ordering::Relaxed);
        Ok(worker)
    }

    pub fn encoder_digest(&self) -> ContractDigestV1 { self.config.encoder_digest }

    pub fn metrics(&self) -> InventoryCellEncoderWorkerMetricsV1 {
        let count = &self.counters;
        InventoryCellEncoderWorkerMetricsV1 {
            attempted_requests: count.attempts.load(Ordering::Relaxed), validated_responses: count.responses.load(Ordering::Relaxed),
            truncated_responses: count.truncated.load(Ordering::Relaxed), process_starts: count.starts.load(Ordering::Relaxed),
            stdin_bytes: count.stdin.load(Ordering::Relaxed), stdout_bytes: count.stdout.load(Ordering::Relaxed),
            reported_cpu_nanoseconds: count.cpu.load(Ordering::Relaxed), reported_wall_nanoseconds: count.wall.load(Ordering::Relaxed),
            host_request_nanoseconds: count.host.load(Ordering::Relaxed), startup_nanoseconds: count.startup.load(Ordering::Relaxed),
        }
    }

    /// `None` is a typed truncation abstention.  An invalid or cancelled frame
    /// is an error and closes the session before any subsequent request.
    pub async fn encode(&self, text: &str) -> Result<Option<Vec<f32>>, String> {
        if text.trim().is_empty() || text.len() > 8192 { return Err("semantic encoder text bound".to_string()); }
        let _elapsed = Elapsed { counter: &self.counters.host, started: Instant::now() };
        self.counters.attempts.fetch_add(1, Ordering::Relaxed);
        tokio::time::timeout(self.config.request_timeout, self.exchange(text)).await
            .map_err(|_| "semantic encoder request timed out".to_string())?
    }

    async fn spawn(&self) -> Result<Session, String> {
        self.config.verify().await?;
        let mut child = Command::new(&self.config.python)
            .args(["-I", "-u", "-B"])
            .arg(&self.config.worker_script)
            .arg("--encoder-source").arg(&self.config.encoder_source)
            .arg("--source-sha256").arg(self.config.source_digest.to_string())
            .arg("--encoder").arg(&self.config.encoder_directory)
            .arg("--encoder-digest").arg(self.config.encoder_digest.to_string())
            .env("TOKENIZERS_PARALLELISM", "false")
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())
            .kill_on_drop(true).spawn().map_err(|_| "cannot spawn semantic encoder worker")?;
        self.counters.starts.fetch_add(1, Ordering::Relaxed);
        let stdin = child.stdin.take().ok_or("semantic encoder stdin unavailable")?;
        let stdout = BufReader::new(child.stdout.take().ok_or("semantic encoder stdout unavailable")?);
        let mut stderr = BufReader::new(child.stderr.take().ok_or("semantic encoder stderr unavailable")?);
        let mut raw = Vec::new();
        (&mut stderr).take(4097).read_until(b'\n', &mut raw).await.map_err(|_| "semantic encoder readiness failed")?;
        if raw.len() > 4096 || !raw.ends_with(b"\n") { return Err("semantic encoder readiness frame bound".to_string()); }
        let ready: Ready = serde_json::from_slice(&raw).map_err(|_| "invalid semantic encoder readiness")?;
        if ready.schema != "hepta.memory.inventory-encoder-ready.v1" || ready.encoder_digest != self.config.encoder_digest
            || ready.worker_digest.digest() != self.config.worker_digest || ready.source_digest.digest() != self.config.source_digest
            || ready.dimension != 384 || ready.native_batch != 1 || ready.max_request != MAX_REQUEST
            || ready.max_response != MAX_RESPONSE || ready.base_bytes != 127_536_988
        { return Err("semantic encoder readiness differs from configured pins".to_string()); }
        let stderr_task = tokio::spawn(async move { let _ = tokio::io::copy(&mut stderr, &mut tokio::io::sink()).await; });
        Ok(Session { child, stdin, stdout, stderr_task })
    }

    async fn exchange(&self, text: &str) -> Result<Option<Vec<f32>>, String> {
        let mut slot = self.session.lock().await;
        // Keep the slot empty while the request owns the child.  Cancellation
        // therefore kills exactly this exchange instead of returning its tail.
        let mut session = match slot.take() { Some(session) => session, None => self.spawn().await? };
        if session.child.try_wait().map_err(|_| "semantic encoder status unavailable")?.is_some() {
            return Err("semantic encoder exited".to_string());
        }
        session.require_idle(&self.counters.stdout).await?;
        let sequence = self.counters.sequence.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| value.checked_add(1))
            .map_err(|_| "semantic encoder request sequence exhausted")? + 1;
        let bound = Bound::new(sequence, text, self.config.encoder_digest)?;
        let mut written = 0;
        while written < bound.bytes.len() {
            let count = session.stdin.write(&bound.bytes[written..]).await.map_err(|_| "semantic encoder input failed")?;
            self.counters.stdin.fetch_add(count as u64, Ordering::Relaxed);
            if count == 0 { return Err("semantic encoder input closed".to_string()); }
            written += count;
        }
        session.stdin.flush().await.map_err(|_| "semantic encoder input flush failed")?;
        let mut raw = Vec::new();
        let read = (&mut session.stdout).take((MAX_RESPONSE + 2) as u64).read_until(b'\n', &mut raw).await;
        self.counters.stdout.fetch_add(raw.len() as u64, Ordering::Relaxed);
        if read.is_err() || raw.len() > MAX_RESPONSE + 1 || !raw.ends_with(b"\n") {
            self.counters.stdout.fetch_add(session.stdout.buffer().len() as u64, Ordering::Relaxed);
            return Err("semantic encoder output frame bound or I/O failure".to_string());
        }
        session.require_idle(&self.counters.stdout).await?;
        let response = bound.response(&raw)?;
        self.counters.responses.fetch_add(1, Ordering::Relaxed);
        self.counters.cpu.fetch_add(response.cpu_ns, Ordering::Relaxed);
        self.counters.wall.fetch_add(response.wall_ns, Ordering::Relaxed);
        self.counters.truncated.fetch_add(u64::from(response.truncated), Ordering::Relaxed);
        *slot = Some(session);
        Ok(if response.truncated { None } else { Some(response.features) })
    }
}

struct Session { child: Child, stdin: ChildStdin, stdout: BufReader<ChildStdout>, stderr_task: JoinHandle<()> }
impl Session {
    async fn require_idle(&mut self, received: &AtomicU64) -> Result<(), String> {
        let ready = std::future::poll_fn(|cx| Poll::Ready(match Pin::new(&mut self.stdout).poll_fill_buf(cx) {
            Poll::Pending => None,
            Poll::Ready(Ok(bytes)) => Some(Ok(bytes.len())),
            Poll::Ready(Err(_)) => Some(Err("semantic encoder output failed")),
        })).await;
        match ready {
            None => Ok(()),
            Some(Ok(0)) => Err("semantic encoder output closed".to_string()),
            Some(Ok(count)) => { received.fetch_add(count as u64, Ordering::Relaxed); Err("semantic encoder unsolicited output".to_string()) }
            Some(Err(reason)) => Err(reason.to_string()),
        }
    }
}
impl Drop for Session {
    fn drop(&mut self) { self.stderr_task.abort(); let _ = self.child.start_kill(); }
}
struct Elapsed<'a> { counter: &'a AtomicU64, started: Instant }
impl Drop for Elapsed<'_> {
    fn drop(&mut self) { self.counter.fetch_add(nanos(self.started), Ordering::Relaxed); }
}
fn nanos(started: Instant) -> u64 { started.elapsed().as_nanos().min(u128::from(u64::MAX)) as u64 }

#[cfg(test)]
#[path = "inventory_cell_encoder_tests.rs"]
mod tests;
