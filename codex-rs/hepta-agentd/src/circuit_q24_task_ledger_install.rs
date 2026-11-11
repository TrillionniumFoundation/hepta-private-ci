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
        let producer = Arc::new(OriginalCellQ24TaskLedgerProducerV1::open_original(
            inputs,
            Arc::clone(&self.source),
            self.cell.clone(),
            published,
            config.identity().clone(),
        ).map_err(|error| AgentdError::Invalid(error.to_string()))?);
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
