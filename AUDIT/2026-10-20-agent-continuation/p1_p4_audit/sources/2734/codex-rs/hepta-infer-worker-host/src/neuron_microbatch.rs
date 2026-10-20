//! Production worker owner for the shared-feature neuron microbatch path.
//!
//! Planning is deliberately separate from execution, but the worker accepts
//! only a frozen [`MicrobatchPlanV1`] and verifies its worker/generation fence
//! before invoking the real [`ReferenceBackendBatchV1`].  This closes the
//! planner-to-worker gap without giving the reference backend any authority to
//! select, promote, release, or dispatch an external effect.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_neuron::DataPlaneError;
use codex_hepta_neuron::HeadExecutionOutputV1;
use codex_hepta_neuron::MetricsError;
use codex_hepta_neuron::MicrobatchPlanV1;
use codex_hepta_neuron::NeuronMetricEventV1;
use codex_hepta_neuron::NeuronMetricsGroupCommitWriterV1;
use codex_hepta_neuron::ReferenceBackendBatchV1;
use codex_hepta_neuron::plan_microbatch_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronMicrobatchExecutionV1 {
    pub worker_id: StableId,
    pub generation: Generation,
    pub plan_digest: Digest32,
    pub outputs: Vec<HeadExecutionOutputV1>,
    pub execution_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Debug, Eq, PartialEq)]
pub enum NeuronMicrobatchWorkerError {
    DataPlane(DataPlaneError),
    Metrics(MetricsError),
    MetricsLock,
    WorkerMismatch,
    GenerationMismatch,
}

impl fmt::Display for NeuronMicrobatchWorkerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronMicrobatchWorkerError {}

impl From<DataPlaneError> for NeuronMicrobatchWorkerError {
    fn from(value: DataPlaneError) -> Self {
        Self::DataPlane(value)
    }
}

impl From<MetricsError> for NeuronMicrobatchWorkerError {
    fn from(value: MetricsError) -> Self {
        Self::Metrics(value)
    }
}

/// The production owner that crosses the planner/backend boundary.
#[derive(Clone)]
pub struct NeuronMicrobatchWorkerV1 {
    worker_id: StableId,
    generation: Generation,
    backend: ReferenceBackendBatchV1,
    metrics: Option<Arc<Mutex<NeuronMetricsGroupCommitWriterV1>>>,
}

impl NeuronMicrobatchWorkerV1 {
    pub fn new(
        worker_id: StableId,
        generation: Generation,
        backend: ReferenceBackendBatchV1,
    ) -> Self {
        Self {
            worker_id,
            generation,
            backend,
            metrics: None,
        }
    }

    /// Attach the host-owned durable metrics writer.  The writer is shared by
    /// clones of this worker so retries serialize through one file lock and
    /// one generation fence.
    #[must_use]
    pub fn with_metrics_writer(
        mut self,
        writer: Arc<Mutex<NeuronMetricsGroupCommitWriterV1>>,
    ) -> Self {
        self.metrics = Some(writer);
        self
    }

    #[must_use]
    pub fn worker_id(&self) -> &StableId {
        &self.worker_id
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    /// Freeze a bounded work set for this worker.  This is the only planner
    /// entry exposed by the worker owner, so a plan cannot be routed to a
    /// different worker without failing the execution fence below.
    pub fn plan(
        &self,
        planned_at_micros: u64,
        deadline_micros: u64,
        requests: Vec<codex_hepta_neuron::HeadExecutionRequestV1>,
    ) -> Result<MicrobatchPlanV1, NeuronMicrobatchWorkerError> {
        plan_microbatch_v1(
            self.worker_id.clone(),
            self.generation,
            planned_at_micros,
            deadline_micros,
            requests,
        )
        .map_err(Into::into)
    }

    /// Execute one exact plan using the actual deterministic backend.
    ///
    /// The backend receives the same frozen request slice produced by the
    /// planner.  There is no per-item re-planning or silent fallback to a
    /// single-item path, which makes the batch receipt meaningful for
    /// production throughput and recovery accounting.
    pub fn execute(
        &self,
        now_micros: u64,
        plan: &MicrobatchPlanV1,
    ) -> Result<NeuronMicrobatchExecutionV1, NeuronMicrobatchWorkerError> {
        let started = Instant::now();
        let cpu_before = process_cpu_micros();
        if plan.worker_id() != &self.worker_id {
            return Err(NeuronMicrobatchWorkerError::WorkerMismatch);
        }
        if plan.generation() != self.generation {
            return Err(NeuronMicrobatchWorkerError::GenerationMismatch);
        }
        plan.validate(now_micros)?;
        let outputs = self.backend.execute(plan.requests())?;
        let execution_digest = digest_execution(plan.plan_digest(), &outputs);
        if let Some(metrics) = &self.metrics {
            let lock_started = Instant::now();
            let mut writer = metrics
                .lock()
                .map_err(|_| NeuronMicrobatchWorkerError::MetricsLock)?;
            let lock_wait_micros =
                u64::try_from(lock_started.elapsed().as_micros()).unwrap_or(u64::MAX);
            let elapsed_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
            let cpu_micros = process_cpu_micros()
                .zip(cpu_before)
                .map(|(after, before)| after.saturating_sub(before))
                .unwrap_or(elapsed_micros);
            let event_id =
                StableId::new(format!("microbatch:{}", plan.plan_digest())).map_err(|_| {
                    NeuronMicrobatchWorkerError::Metrics(MetricsError::InvalidEvent("event id"))
                })?;
            writer.append(NeuronMetricEventV1 {
                event_id,
                generation: self.generation,
                plan_digest: plan.plan_digest(),
                execution_digest,
                request_count: u32::try_from(outputs.len()).map_err(|_| {
                    NeuronMicrobatchWorkerError::Metrics(MetricsError::InvalidEvent(
                        "request count",
                    ))
                })?,
                elapsed_micros,
                cpu_micros,
                rss_bytes: process_rss_bytes().unwrap_or(0),
                p95_micros: elapsed_micros,
                p99_micros: elapsed_micros,
                lock_wait_micros,
                recovered: false,
            })?;
        }
        Ok(NeuronMicrobatchExecutionV1 {
            worker_id: self.worker_id.clone(),
            generation: self.generation,
            plan_digest: plan.plan_digest(),
            outputs,
            execution_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

/// Read process CPU time without introducing an unsafe syscall dependency into
/// the authority boundary. Linux exposes aggregate user/system ticks in
/// `/proc/self/stat`; Linux production hosts conventionally use a 100 Hz
/// scheduler tick, so this is converted to microseconds at the sampling edge.
/// Hosts without procfs still receive a wall-time sample, while the durable
/// record keeps RSS explicitly zero to make that limitation auditable.
fn process_cpu_micros() -> Option<u64> {
    #[cfg(target_os = "linux")]
    {
        let stat = fs::read_to_string("/proc/self/stat").ok()?;
        let end = stat.rfind(')')?;
        let fields = stat.get(end + 2..)?.split_whitespace().collect::<Vec<_>>();
        let user = fields.get(11)?.parse::<u64>().ok()?;
        let system = fields.get(12)?.parse::<u64>().ok()?;
        user.checked_add(system)?.checked_mul(10_000)
    }
    #[cfg(not(target_os = "linux"))]
    {
        None
    }
}

fn process_rss_bytes() -> Option<u64> {
    #[cfg(target_os = "linux")]
    {
        let status = fs::read_to_string("/proc/self/status").ok()?;
        let kib = status.lines().find_map(|line| {
            let rest = line.strip_prefix("VmRSS:")?;
            rest.split_whitespace().next()?.parse::<u64>().ok()
        })?;
        kib.checked_mul(1024)
    }
    #[cfg(not(target_os = "linux"))]
    {
        None
    }
}

fn digest_execution(plan_digest: Digest32, outputs: &[HeadExecutionOutputV1]) -> Digest32 {
    let mut bytes = b"hepta.infer-worker.neuron-microbatch-execution.v1\0".to_vec();
    bytes.extend_from_slice(plan_digest.as_array());
    bytes.extend_from_slice(&(outputs.len() as u64).to_be_bytes());
    for output in outputs {
        bytes.extend_from_slice(output.request_id.as_str().as_bytes());
        bytes.extend_from_slice(output.model_id.as_str().as_bytes());
        bytes.extend_from_slice(&output.generation.get().to_be_bytes());
        bytes.extend_from_slice(output.input_digest.as_array());
        bytes.extend_from_slice(output.output_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "neuron_microbatch_tests.rs"]
mod tests;
