//! Installs the real task result producer beside the exact original runtime.
//! A missing independent Outcome changes learning readiness, not task success.

use codex_hepta_automation::CircuitCommittedTraceV2;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_neuron::FileAnchorWitnessStore;

use super::*;
use crate::AgentdCircuitTaskInvocationProviderV1;
use crate::CircuitTaskLearningReadinessV1;
use crate::CircuitTaskReceiptV1;
use crate::CircuitTaskRequestV1;
use crate::OriginalCellQ24TaskLedgerInputsV1;
use crate::OriginalCellQ24TaskLedgerProducerV1;

pub struct AgentdQ24LearningTaskRuntimeV1 {
    pub task: AgentdQ24CircuitTaskRuntimeV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    pub ledger: Arc<OriginalCellQ24TaskLedgerProducerV1>,
}

/// Actual A owners for one already-bound same-actor phase. No public provider
/// or descriptor can construct this pair, and abandoning it closes that phase.
pub(crate) struct OriginalSameActorATaskParts {
    gate: Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>,
    bootstrap: CircuitTaskRuntimeBootstrapV1,
    invocation: Arc<dyn AgentdCircuitTaskInvocationProviderV1>,
    source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    ledger: Arc<OriginalCellQ24TaskLedgerProducerV1>,
    close: crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop,
}

impl OriginalSameActorATaskParts {
    pub(crate) fn into_task_parts(
        mut self,
        identity: &AgentdIdentity,
        gate: &Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>,
    ) -> Result<
        (
            CircuitTaskRuntimeBootstrapV1,
            Arc<dyn AgentdCircuitTaskInvocationProviderV1>,
            Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
            PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
            Arc<OriginalCellQ24TaskLedgerProducerV1>,
        ),
        AgentdError,
    > {
        if !Arc::ptr_eq(&self.gate, gate) {
            return Err(AgentdError::GenerationFenced(
                "original A task belongs to another phase".into(),
            ));
        }
        self.gate
            .require_open()
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        self.bootstrap.require_identity(identity)?;
        self.bootstrap
            .handle()
            .require_direct_original_handle()
            .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        self.close.disarm();
        Ok((
            self.bootstrap,
            self.invocation,
            self.source,
            self.cell,
            self.ledger,
        ))
    }
}

struct OriginalTaskInvocation {
    source: Arc<DurableCircuitTaskSourceV1<FileAnchorWitnessStore>>,
    producer: Arc<OriginalCellQ24TaskLedgerProducerV1>,
}

impl CircuitQ24TaskRuntimeV1<FileAnchorWitnessStore, FileAnchorWitnessStore> {
    pub(crate) fn install_original_task_ledger(
        self,
        config: AgentdConfig,
        published: PublishedCircuitFeatureTaskV1,
        inputs: OriginalCellQ24TaskLedgerInputsV1,
    ) -> Result<AgentdQ24LearningTaskRuntimeV1, AgentdError> {
        let producer = Arc::new(
            OriginalCellQ24TaskLedgerProducerV1::open_original(
                inputs,
                Arc::clone(&self.source),
                self.cell.clone(),
                published,
                config.identity().clone(),
            )
            .map_err(|error| AgentdError::Invalid(error.to_string()))?,
        );
        let invocation = Arc::new(OriginalTaskInvocation {
            source: self.invocation,
            producer: Arc::clone(&producer),
        });
        let config = config.with_circuit_task_bootstrap(self.bootstrap, invocation)?;
        Ok(AgentdQ24LearningTaskRuntimeV1 {
            task: AgentdQ24CircuitTaskRuntimeV1 {
                config,
                source: self.source,
                cell: self.cell,
            },
            ledger: producer,
        })
    }
}

impl CircuitQ24TaskRuntimeV1<FileAnchorWitnessStore, FileAnchorWitnessStore> {
    /// Runs only after the original Initial publication and actual task-channel
    /// construction. Opening the real producer does not invent an Outcome.
    pub(crate) fn into_original_same_actor_task_parts(
        self,
        identity: &AgentdIdentity,
        gate: Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>,
        published: PublishedCircuitFeatureTaskV1,
        inputs: OriginalCellQ24TaskLedgerInputsV1,
    ) -> Result<OriginalSameActorATaskParts, AgentdError> {
        let close = crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop::new(&gate);
        gate.require_open()
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        self.bootstrap.require_identity(identity)?;
        self.bootstrap
            .handle()
            .require_direct_original_handle()
            .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        let producer = Arc::new(
            OriginalCellQ24TaskLedgerProducerV1::open_original(
                inputs,
                Arc::clone(&self.source),
                self.cell.clone(),
                published,
                identity.clone(),
            )
            .map_err(|error| AgentdError::Invalid(error.to_string()))?,
        );
        let invocation = Arc::new(OriginalTaskInvocation {
            source: self.invocation,
            producer: Arc::clone(&producer),
        });
        gate.require_open()
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        Ok(OriginalSameActorATaskParts {
            gate,
            bootstrap: self.bootstrap,
            invocation,
            source: self.source,
            cell: self.cell,
            ledger: producer,
            close,
        })
    }
}

impl AgentdCircuitTaskInvocationProviderV1 for OriginalTaskInvocation {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<CircuitTaskRequestV1, AgentdError> {
        self.source.build(identity, record)
    }

    fn publish_result(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        receipt: &CircuitTaskReceiptV1,
    ) -> Result<(), AgentdError> {
        // Only this method determines whether the actual task result was
        // published. Later Generator/Observer failures cannot undo success.
        self.source.publish_result(identity, record, receipt)
    }

    fn observe_learning(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        trace: &CircuitCommittedTraceV2,
    ) -> CircuitTaskLearningReadinessV1 {
        let producer: &Arc<OriginalCellQ24TaskLedgerProducerV1> = &self.producer;
        producer.observe_learning(identity, record, trace)
    }
}
