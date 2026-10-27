//! Long-lived, serialized Python addressing behind the configured resolver port.
//! A cancelled or malformed exchange drops its child instead of reusing a tail.

use std::future::Future;
use std::pin::Pin;
use std::process::Stdio;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_cognitive_store::MemoryCellOwnerSnapshotV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::process::Child;
use tokio::process::ChildStdin;
use tokio::process::ChildStdout;
use tokio::process::Command;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;

use crate::MemoryCellAddressResolverV1;
use crate::MemoryCellResolvedAddressV1;

#[path = "memory_cell_address_worker_config.rs"]
mod config;
#[path = "memory_cell_address_worker_wire.rs"]
mod wire;
pub use config::MemoryCellAddressWorkerConfigV1;

use wire::BoundRequest;
use wire::MAX_REQUEST_FRAME;
use wire::MAX_RESPONSE_BODY;
use wire::WorkerReady;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct MemoryCellAddressWorkerMetricsV1 {
    pub attempted_requests: u64,
    pub validated_responses: u64,
    pub process_starts: u64,
    pub stdin_bytes: u64,
    pub stdout_bytes: u64,
    pub reported_cpu_nanoseconds: u64,
    pub reported_wall_nanoseconds: u64,
    pub host_request_nanoseconds: u64,
}

#[derive(Default)]
struct Counters {
    attempts: AtomicU64, responses: AtomicU64, starts: AtomicU64, stdin: AtomicU64, stdout: AtomicU64,
    cpu: AtomicU64, wall: AtomicU64, host: AtomicU64,
}

/// Start and prewarm once, then pass `Arc<MemoryCellAddressWorkerV1>` into
/// `AgentdMemoryCellRuntimeV1::new` and `AgentdConfig::with_memory_cells`.
pub struct MemoryCellAddressWorkerV1 {
    config: MemoryCellAddressWorkerConfigV1,
    policy_digest: ContractDigestV1,
    session: Mutex<Option<WorkerSession>>,
    counters: Counters,
}

impl MemoryCellAddressWorkerV1 {
    pub async fn start(config: MemoryCellAddressWorkerConfigV1) -> Result<Self, String> {
        let policy_digest = tokio::time::timeout(config.startup_timeout, config.verify()).await
            .map_err(|_| "address worker pin verification timed out")??;
        let worker = Self { config, policy_digest, session: Mutex::new(None), counters: Counters::default() };
        let session = tokio::time::timeout(worker.config.startup_timeout, worker.spawn()).await
            .map_err(|_| "address worker prewarm timed out")??;
        *worker.session.lock().await = Some(session);
        Ok(worker)
    }

    pub fn metrics(&self) -> MemoryCellAddressWorkerMetricsV1 {
        let count = &self.counters;
        MemoryCellAddressWorkerMetricsV1 {
            attempted_requests: count.attempts.load(Ordering::Relaxed), validated_responses: count.responses.load(Ordering::Relaxed),
            process_starts: count.starts.load(Ordering::Relaxed), stdin_bytes: count.stdin.load(Ordering::Relaxed), stdout_bytes: count.stdout.load(Ordering::Relaxed),
            reported_cpu_nanoseconds: count.cpu.load(Ordering::Relaxed), reported_wall_nanoseconds: count.wall.load(Ordering::Relaxed),
            host_request_nanoseconds: count.host.load(Ordering::Relaxed),
        }
    }

    async fn spawn(&self) -> Result<WorkerSession, String> {
        if self.config.verify().await? != self.policy_digest { return Err("address import policy changed".to_string()); }
        let mut child = Command::new(&self.config.python)
            .args(["-I", "-u", "-B"]).arg(&self.config.worker_script)
            .arg("--model").arg(&self.config.model_directory)
            .arg("--model-digest").arg(self.config.model_digest.to_string())
            .arg("--encoder").arg(&self.config.encoder_directory)
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())
            .kill_on_drop(true).spawn().map_err(|_| "cannot spawn configured address worker")?;
        self.counters.starts.fetch_add(1, Ordering::Relaxed);
        let stdin = child.stdin.take().ok_or("address worker stdin is unavailable")?;
        let stdout = BufReader::new(child.stdout.take().ok_or("address worker stdout is unavailable")?);
        let mut stderr = BufReader::new(child.stderr.take().ok_or("address worker stderr is unavailable")?);
        let mut ready = Vec::new();
        (&mut stderr).take(4_097).read_until(b'\n', &mut ready).await.map_err(|_| "address worker readiness pipe failed")?;
        if ready.len() > 4_096 || !ready.ends_with(b"\n") { return Err("address worker readiness frame exceeds its bound".to_string()); }
        let ready: WorkerReady = serde_json::from_slice(&ready).map_err(|_| "invalid address worker readiness envelope")?;
        if ready.schema != "hepta.memory.v7.address-worker-ready.v1" || ready.model_digest != self.config.model_digest
            || ready.policy_digest != self.policy_digest || ready.max_frame_bytes != MAX_REQUEST_FRAME || ready.max_response_bytes != MAX_RESPONSE_BODY {
            return Err("address worker readiness differs from configured pins".to_string());
        }
        let stderr_task = tokio::spawn(async move {
            // Drain without retaining or forwarding request text. This keeps a
            // noisy child from blocking on a full stderr pipe.
            let _ = tokio::io::copy(&mut stderr, &mut tokio::io::sink()).await;
        });
        Ok(WorkerSession { child, stdin, stdout, stderr_task })
    }

    async fn exchange(&self, request: &MemoryRequestV1, bound: BoundRequest) -> Result<Option<MemoryCellResolvedAddressV1>, String> {
        let mut slot = self.session.lock().await;
        // Taking ownership is deliberate: cancellation drops this exact child,
        // while the shared slot stays empty for the next explicitly new spawn.
        let mut session = match slot.take() { Some(session) => session, None => self.spawn().await? };
        if session.child.try_wait().map_err(|_| "address worker status failed")?.is_some() { return Err("address worker has exited".to_string()); }
        let mut written = 0;
        while written < bound.bytes.len() {
            let count = session.stdin.write(&bound.bytes[written..]).await.map_err(|_| "address worker input failed")?;
            self.counters.stdin.fetch_add(count as u64, Ordering::Relaxed);
            if count == 0 { return Err("address worker input closed".to_string()); }
            written += count;
        }
        session.stdin.flush().await.map_err(|_| "address worker input flush failed")?;
        let mut response = Vec::new();
        let read = (&mut session.stdout).take((MAX_RESPONSE_BODY + 2) as u64).read_until(b'\n', &mut response).await;
        self.counters.stdout.fetch_add((response.len() + session.stdout.buffer().len()) as u64, Ordering::Relaxed);
        read.map_err(|_| "address worker output failed")?;
        if response.len() > MAX_RESPONSE_BODY + 1 || !response.ends_with(b"\n") || !session.stdout.buffer().is_empty() {
            return Err("address worker returned an oversized, incomplete or unsolicited frame".to_string());
        }
        let (decision, cost) = bound.validate_response(&response, self.config.model_digest, request)?;
        self.counters.responses.fetch_add(1, Ordering::Relaxed);
        self.counters.cpu.fetch_add((cost.processing_cpu_seconds * 1_000_000_000.0) as u64, Ordering::Relaxed);
        self.counters.wall.fetch_add((cost.processing_wall_seconds * 1_000_000_000.0) as u64, Ordering::Relaxed);
        *slot = Some(session);
        Ok(decision)
    }
}

impl MemoryCellAddressResolverV1 for MemoryCellAddressWorkerV1 {
    fn model_digest(&self) -> ContractDigestV1 { self.config.model_digest }

    fn resolve<'a>(&'a self, request: &'a MemoryRequestV1, snapshot: &'a MemoryCellOwnerSnapshotV1)
    -> Pin<Box<dyn Future<Output = Result<Option<MemoryCellResolvedAddressV1>, String>> + Send + 'a>> {
        Box::pin(async move {
            let _elapsed = ElapsedCounter { counter: &self.counters.host, started: Instant::now() };
            self.counters.attempts.fetch_add(1, Ordering::Relaxed);
            let bound = BoundRequest::build(request, snapshot, &self.config.aliases)?;
            let result = tokio::time::timeout(self.config.request_timeout, self.exchange(request, bound)).await
                .map_err(|_| "address worker request timed out".to_string()).and_then(|result| result);
            result
        })
    }
}

struct WorkerSession { child: Child, stdin: ChildStdin, stdout: BufReader<ChildStdout>, stderr_task: JoinHandle<()> }

impl Drop for WorkerSession {
    fn drop(&mut self) {
        self.stderr_task.abort();
        let _ = self.child.start_kill();
    }
}

struct ElapsedCounter<'a> { counter: &'a AtomicU64, started: Instant }

impl Drop for ElapsedCounter<'_> {
    fn drop(&mut self) {
        self.counter.fetch_add(self.started.elapsed().as_nanos().min(u128::from(u64::MAX)) as u64, Ordering::Relaxed);
    }
}

#[cfg(test)]
#[path = "memory_cell_address_worker_test_support.rs"]
mod test_support;
#[cfg(test)]
#[path = "memory_cell_address_worker_tests.rs"]
mod tests;
