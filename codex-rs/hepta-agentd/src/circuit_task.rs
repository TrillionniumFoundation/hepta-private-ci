//! Ordinary task computation through the original Circuit and Cell owners.
//! A task descriptor is not authority: only the daemon's authenticated
//! ObjectiveStart path can enqueue it with its original durable RunStart.

use std::collections::BTreeMap;

use codex_hepta_automation::CircuitCommittedTraceV2;
use codex_hepta_automation::CircuitDispatchV2;
use codex_hepta_automation::CircuitStartV2;
use codex_hepta_automation::TaskFlowError;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_neuron::CellStepInputV1;
use codex_hepta_types::Digest32;

use crate::CircuitCellErrorV1;
use crate::CircuitCellExecutionV1;

#[path = "circuit_task_driver.rs"]
mod driver;
#[path = "circuit_task_runtime.rs"]
mod runtime;
#[path = "circuit_task_source.rs"]
mod source;

pub use runtime::CircuitTaskHandleV1;
pub use runtime::CircuitTaskRuntimeBootstrapV1;
pub use runtime::circuit_task_channel_v1;
pub use source::CircuitTaskSourceInputV1;
pub use source::CircuitTaskSourcePublicationV1;
pub use source::CircuitTaskSourceReadbackV1;
pub use source::DurableCircuitTaskSourceV1;
pub use source::HistoricalCircuitTaskSourceObservationV1;
pub use source::HistoricalCircuitTaskSourceV1;

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum CircuitTaskErrorV1 {
    #[error("Circuit task does not match its original admitted task")]
    InvalidBinding,
    #[error("Circuit task queue is full")]
    QueueFull,
    #[error("Circuit task owner is unavailable or fenced")]
    Unavailable,
    #[error("Circuit task deadline has elapsed")]
    DeadlineExceeded,
    #[error("Circuit task needs original owner reconciliation")]
    ReconciliationRequired,
    #[error("Circuit task acknowledgement is uncertain")]
    CommitUncertain,
    #[error("Circuit task owner: {0}")]
    Circuit(#[from] TaskFlowError),
    #[error("Circuit task Cell: {0}")]
    Cell(#[from] CircuitCellErrorV1),
}

/// Immutable host-derived inputs. The Circuit definition, writer, Cell state,
/// encoders and model facility belong to the bootstrap, never to the caller.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitTaskRequestV1 {
    pub start: CircuitStartV2,
    pub objective_digest: Digest32,
    pub deadline_ms: u64,
}

impl CircuitTaskRequestV1 {
    pub(crate) fn validate_record(
        &self,
        record: &RunStartRecordV1,
        generation: u64,
    ) -> Result<(), CircuitTaskErrorV1> {
        if self.start.run_id != record.snapshot.run_id.as_str()
            || self.start.run_id.len() > 128
            || self.objective_digest != record.snapshot.objective_digest
            || self.objective_digest.is_zero()
            || record.snapshot.generation != generation
            || record.disposition != RunStartObjectiveDispositionV1::Compiled
            || self.start.created_at_ms != record.admission.observed_at_unix_micros / 1_000
            || self.deadline_ms <= self.start.created_at_ms
            || self.deadline_ms > record.admission.deadline_unix_micros / 1_000
            || self.deadline_ms > record.authentication.expires_at_ms
            || !(1..=3_600_000).contains(&self.start.lease_duration_ms)
            || record.objective_semantic_bytes.len() > 256 * 1_024
            || record.objective_function_v1_bytes.len() > 256 * 1_024
        {
            return Err(CircuitTaskErrorV1::InvalidBinding);
        }
        Ok(())
    }
}

/// Prepare may persist a new exact input; Readback must retrieve that original
/// input and must not rebuild it from changed ambient state or a fresh clock.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CircuitTaskInputModeV1 {
    Prepare,
    Readback,
}

/// Resolves data, never completion or authority. Implementations use the
/// original task/source owner to retain complete semantic Cell inputs before
/// returning Prepare, including clocks, masks and source frontier. Readback
/// must survive owner restart. The driver supplies only verified prior Cell
/// outputs; a missing input or withdrawn source must fail closed.
pub trait CircuitTaskInputProviderV1: Send {
    fn resolve(
        &mut self,
        request: &CircuitTaskRequestV1,
        dispatch: &CircuitDispatchV2,
        completed: &BTreeMap<u64, CircuitCellExecutionV1>,
        mode: CircuitTaskInputModeV1,
    ) -> Result<CellStepInputV1, CircuitTaskErrorV1>;
}

/// Complete Circuit history plus original, independently re-read Cell results.
/// The constructor is private: callers cannot replace committed observations.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitTaskReceiptV1 {
    trace: CircuitCommittedTraceV2,
    executions: BTreeMap<u64, CircuitCellExecutionV1>,
}

impl CircuitTaskReceiptV1 {
    pub fn trace(&self) -> &CircuitCommittedTraceV2 {
        &self.trace
    }

    pub fn executions(&self) -> &BTreeMap<u64, CircuitCellExecutionV1> {
        &self.executions
    }
}

#[derive(Clone, Copy)]
enum CircuitTaskModeV1 {
    Drive,
    Readback,
}
