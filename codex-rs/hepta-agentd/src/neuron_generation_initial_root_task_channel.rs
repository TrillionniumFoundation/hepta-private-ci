//! Root keeps the original factory's one task/Cell/Source without consuming
//! the daemon Config. This internal constructor is not a cross-process lane.

use std::sync::Arc;
use crate::AgentdError;
use crate::CircuitTaskSourceReadbackV1;
use codex_hepta_neuron::AnchorWitnessStore;

impl<SW: AnchorWitnessStore, CW: AnchorWitnessStore> OriginalRootCircuitTaskCustodyV1<SW, CW> {
    pub(crate) fn require_original_source(&self, source: &Arc<CircuitTaskSourceReadbackV1<SW>>)
        -> Result<(), AgentdError>
    {
        require_root()?;
        if !Arc::ptr_eq(&self.source, source) {
            return Err(invalid("Root task service differs from the original Source Arc"));
        }
        Ok(())
    }
}


use super::InitialPhase;
use super::OriginalRootCircuitTaskCustodyV1;
use super::OriginalRootCircuitTaskInputsV1;
use super::OriginalRootInitialGenerationCustodyV1;
use super::OriginalRootInitialInstallationErrorV1;
use super::invalid;
use super::require_root;
use crate::AgentdIdentity;
use crate::CircuitQ24TaskProfileV1;
use crate::CircuitQ24TaskRuntimeV1;
use crate::circuit_q24_task_channel_v1;

impl<W: AnchorWitnessStore + Send + 'static> OriginalRootInitialGenerationCustodyV1<W> {
    /// Only the concrete protected host consumes these parts. No public getter
    /// returns the task, writer, bootstrap or Ready value, and the caller cannot
    /// replace the task with a supplied profile. Factory failure may have effects.
    pub(crate) fn into_original_root_task_channel<SW, CW>(
        self,
        identity: &AgentdIdentity,
        inputs: OriginalRootCircuitTaskInputsV1<SW, CW>,
    ) -> Result<
        (CircuitQ24TaskRuntimeV1<SW, CW>, OriginalRootCircuitTaskCustodyV1<SW, CW>),
        OriginalRootInitialInstallationErrorV1,
    >
    where
        SW: AnchorWitnessStore + Send + 'static,
        CW: AnchorWitnessStore + Send + 'static,
    {
        let Self { operation, phase } = self;
        let installed = (|| {
            require_root()?;
            let InitialPhase::Ready(ready) = phase else {
                return Err(invalid("original initial publication is not ready"));
            };
            let task = (*ready).into_circuit_feature_task(inputs.definition, inputs.source)?;
            let retirement = task.clone();
            let profile = CircuitQ24TaskProfileV1 {
                files: inputs.files,
                source_mode: inputs.source_mode,
                published_task: task,
                fence: inputs.fence,
                circuit: inputs.circuit,
                routes: inputs.routes,
                bundle: inputs.bundle,
                model: inputs.model,
                worker_generation: inputs.worker_generation,
                maximum_cell_records: inputs.maximum_cell_records,
                queue_capacity: inputs.queue_capacity,
                clock: inputs.clock,
            };
            let runtime = circuit_q24_task_channel_v1(identity, profile)?;
            Ok((runtime, retirement))
        })();
        match installed {
            Ok((runtime, task)) => {
                // These are the actual factory outputs. Opening another Cell
                // or another Source here would break the original drain identity.
                let custody = OriginalRootCircuitTaskCustodyV1 {
                    operation,
                    task,
                    cell: runtime.cell(),
                    source: runtime.source(),
                    identity: identity.clone(),
                };
                Ok((runtime, custody))
            }
            Err(error) => Err(OriginalRootInitialInstallationErrorV1 { operation, error }),
        }
    }
}
