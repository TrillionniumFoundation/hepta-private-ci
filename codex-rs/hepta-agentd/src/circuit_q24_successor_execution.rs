//! Original execution resources and explicitly enrolled feedback capabilities.
//! Publication, selected bundle and loaded model enter solely from the original
//! Root driver. Feedback does not enroll the next Root learning source.

use super::*;
use codex_hepta_neuron::FileAnchorWitnessStore;

use crate::AgentdCircuitTaskInvocationProviderV1;
use crate::OriginalCellQ24TaskLedgerInputsV1;
use crate::OriginalCellQ24TaskLedgerProducerV1;

/// Learning is explicit. The original host supplies the already enrolled
/// Generator/Ledger capabilities; a successful task supplies no business label.
pub enum OriginalQ24SuccessorFeedbackV1 {
    NonLearning,
    OriginalLedger(OriginalCellQ24TaskLedgerInputsV1),
}

pub struct OriginalQ24SuccessorExecutionInputsV1 {
    pub files: CircuitQ24TaskFilesV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    pub source_mode: CircuitQ24TaskOpenModeV1,
    pub feedback: OriginalQ24SuccessorFeedbackV1,
    pub fence: TaskFlowFence,
    pub circuit: BoundedCircuitDefinitionV2,
    pub routes: Vec<CircuitCellRouteV1>,
    pub worker_generation: u64,
    pub maximum_cell_records: usize,
    pub clock: Arc<dyn Fn() -> CircuitCellTimeV1 + Send + Sync>,
}

/// Installed original owners, without an execution receipt. Actual C still
/// enters through signed ObjectiveStart and reads its original committed source.
pub struct OriginalQ24InstalledSuccessorV1 {
    pub(crate) identity: AgentdIdentity,
    pub(crate) source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    pub(crate) cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    task: PublishedCircuitFeatureTaskV1,
    ledger: Option<Arc<OriginalCellQ24TaskLedgerProducerV1>>,
}

impl OriginalQ24InstalledSuccessorV1 {
    pub fn source(&self) -> Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>> {
        Arc::clone(&self.source)
    }
    pub fn cell(&self) -> PublishedCircuitCellOwnerV1<FileAnchorWitnessStore> {
        self.cell.clone()
    }
    pub fn published_task(&self) -> PublishedCircuitFeatureTaskV1 {
        self.task.clone()
    }

    /// The original owner can accept an independently signed business Outcome
    /// and prepare a Dataset. This does not enroll the next Root source or
    /// authorize task execution; every owner operation retains its live checks.
    pub fn original_task_ledger(&self) -> Option<Arc<OriginalCellQ24TaskLedgerProducerV1>> {
        self.ledger.as_ref().map(Arc::clone)
    }
}

/// Created only with the original channel. No caller can replace its source or
/// Ledger owner after publication or install an arbitrary invocation provider.
pub(crate) struct OriginalQ24SuccessorInvocationV1 {
    source: Arc<DurableCircuitTaskSourceV1<FileAnchorWitnessStore>>,
    ledger: Option<Arc<OriginalCellQ24TaskLedgerProducerV1>>,
}

impl AgentdCircuitTaskInvocationProviderV1 for OriginalQ24SuccessorInvocationV1 {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &codex_hepta_learning_ledger::RunStartRecordV1,
    ) -> Result<crate::CircuitTaskRequestV1, AgentdError> {
        self.source.build(identity, record)
    }

    fn publish_result(
        &self,
        identity: &AgentdIdentity,
        record: &codex_hepta_learning_ledger::RunStartRecordV1,
        receipt: &crate::CircuitTaskReceiptV1,
    ) -> Result<(), AgentdError> {
        // Task publication is independent of learning readiness. A missing
        // business Outcome never causes another dispatch of committed C work.
        self.source.publish_result(identity, record, receipt)
    }

    fn observe_learning(
        &self,
        identity: &AgentdIdentity,
        record: &codex_hepta_learning_ledger::RunStartRecordV1,
        trace: &codex_hepta_automation::CircuitCommittedTraceV2,
    ) -> crate::CircuitTaskLearningReadinessV1 {
        match &self.ledger {
            Some(producer) => {
                let producer: &Arc<OriginalCellQ24TaskLedgerProducerV1> = producer;
                producer.observe_learning(identity, record, trace)
            }
            None => self.source.observe_learning(identity, record, trace),
        }
    }
}

impl OriginalQ24SuccessorExecutionInputsV1 {
    pub(crate) fn validate_original_successor_execution(
        &self,
        identity: &AgentdIdentity,
        target: &crate::OriginalCellQ24FeatureTargetV1,
        capacity: usize,
    ) -> Result<(), AgentdError> {
        TaskFlowFence::new(
            self.fence.owner_agent_id.clone(),
            &self.fence.owner_id,
            self.fence.owner_epoch,
            self.fence.generation,
            &self.fence.fencing_token,
        )
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        if self.fence.owner_agent_id != identity.agent_id
            || identity.spawn_generation == 0
            || identity.spawn_generation.checked_add(1) != Some(self.fence.generation)
            || self.worker_generation == 0
            || !(1..=64).contains(&capacity)
            || !(3..=16).contains(&self.maximum_cell_records)
        {
            return Err(AgentdError::GenerationFenced(
                "successor execution identity or bounds differ".into(),
            ));
        }
        let program = self
            .circuit
            .programs
            .iter()
            .find(|program| program.program_id == self.circuit.entry_program)
            .ok_or_else(|| AgentdError::Invalid("successor has no original root program".into()))?;
        CircuitCellRegistryV1::new(
            self.circuit.clone(),
            vec![CircuitCellBindingV1 {
                program_id: program.program_id.clone(),
                node_id: program.entry_node.clone(),
                cell: target.definition.clone(),
                routes: self.routes.clone(),
            }],
        )
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        Ok(())
    }

    pub(crate) fn open_original_successor_channel(
        self,
        identity: &AgentdIdentity,
        task: PublishedCircuitFeatureTaskV1,
        bundle: CellCompatibilityBundleV1,
        model: Arc<LoadedCellQ24ModelV1>,
        capacity: usize,
    ) -> Result<
        (
            CircuitTaskRuntimeBootstrapV1,
            Arc<OriginalQ24SuccessorInvocationV1>,
            OriginalQ24InstalledSuccessorV1,
        ),
        AgentdError,
    > {
        let runtime: CircuitQ24TaskRuntimeV1<FileAnchorWitnessStore, FileAnchorWitnessStore> =
            circuit_q24_task_channel_v1(
                identity,
                CircuitQ24TaskProfileV1 {
                    files: self.files,
                    source_mode: self.source_mode,
                    published_task: task.clone(),
                    fence: self.fence,
                    circuit: self.circuit,
                    routes: self.routes,
                    bundle,
                    model,
                    worker_generation: self.worker_generation,
                    maximum_cell_records: self.maximum_cell_records,
                    queue_capacity: capacity,
                    clock: self.clock,
                },
            )?;
        let ledger = match self.feedback {
            OriginalQ24SuccessorFeedbackV1::NonLearning => None,
            OriginalQ24SuccessorFeedbackV1::OriginalLedger(inputs) => {
                let producer = OriginalCellQ24TaskLedgerProducerV1::open_original(
                    inputs,
                    Arc::clone(&runtime.source),
                    runtime.cell.clone(),
                    task.clone(),
                    identity.clone(),
                )
                .map_err(|error| AgentdError::Io(std::io::Error::other(error)))?;
                Some(Arc::new(producer))
            }
        };
        let invocation = Arc::new(OriginalQ24SuccessorInvocationV1 {
            source: runtime.invocation,
            ledger: ledger.as_ref().map(Arc::clone),
        });
        let installed = OriginalQ24InstalledSuccessorV1 {
            identity: identity.clone(),
            source: runtime.source,
            cell: runtime.cell,
            task,
            ledger,
        };
        Ok((runtime.bootstrap, invocation, installed))
    }
}
