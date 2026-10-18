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

use codex_hepta_neuron::DataPlaneError;
use codex_hepta_neuron::HeadExecutionOutputV1;
use codex_hepta_neuron::MicrobatchPlanV1;
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronMicrobatchWorkerError {
    DataPlane(DataPlaneError),
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

/// The production owner that crosses the planner/backend boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronMicrobatchWorkerV1 {
    worker_id: StableId,
    generation: Generation,
    backend: ReferenceBackendBatchV1,
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
        }
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
        if plan.worker_id() != &self.worker_id {
            return Err(NeuronMicrobatchWorkerError::WorkerMismatch);
        }
        if plan.generation() != self.generation {
            return Err(NeuronMicrobatchWorkerError::GenerationMismatch);
        }
        plan.validate(now_micros)?;
        let outputs = self.backend.execute(plan.requests())?;
        let execution_digest = digest_execution(plan.plan_digest(), &outputs);
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
