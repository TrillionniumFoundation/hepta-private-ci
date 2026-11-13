//! The existing driver has exactly two internal Cell paths. The local path
//! forwards to its original owner; the remote path retains the same admission
//! in the daemon and visits the fixed Root Cell lane. External implementations
//! cannot enter this trait or substitute a completed-task provider.

use codex_hepta_automation::CircuitComputationAdmissionV2;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::CellExecutionError;
use codex_hepta_neuron::CellInferenceReadbackPortV1;
use codex_hepta_neuron::CellInputEncoderV1;
use codex_hepta_neuron::CellScopeV1;
use codex_hepta_neuron::CellStateOwnerV1;
use codex_hepta_neuron::CellStepInputV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdCircuitCellOwnerV1;
use crate::CircuitCellErrorV1;
use crate::CircuitCellExecutionV1;
use crate::CircuitCellRegistryV1;
use crate::CircuitCellTimeV1;

mod sealed {
    pub trait OriginalCellPath {}
}

/// Only this module implements the sealed supertrait for the original native
/// Cell owner and the purpose-fixed daemon client. Its clock remains the
/// existing driver's repeated signed-RunStart/currentness observation.
pub(super) trait OriginalCellPort: sealed::OriginalCellPath + Send {
    fn registry(&self) -> &CircuitCellRegistryV1;
    fn state_owner(&self) -> &Self { self }
    fn lookup(&self, scope: &CellScopeV1, operation: &StableId, request: Digest32)
        -> Result<Option<CellDecisionReceiptV1>, CellExecutionError>;
    fn execute(&mut self, admission: CircuitComputationAdmissionV2, input: CellStepInputV1,
        clock: impl FnMut() -> CircuitCellTimeV1) -> Result<CircuitCellExecutionV1, CircuitCellErrorV1>;
}

impl<O, P, E> sealed::OriginalCellPath for AgentdCircuitCellOwnerV1<O, P, E> {}

impl<O, P, E> OriginalCellPort for AgentdCircuitCellOwnerV1<O, P, E>
where
    O: CellStateOwnerV1 + Send,
    P: NeuronInferenceControlPort + CellInferenceReadbackPortV1 + Send,
    E: CellInputEncoderV1 + Send,
{
    fn registry(&self) -> &CircuitCellRegistryV1 { AgentdCircuitCellOwnerV1::registry(self) }
    fn lookup(&self, scope: &CellScopeV1, operation: &StableId, request: Digest32)
        -> Result<Option<CellDecisionReceiptV1>, CellExecutionError>
    { AgentdCircuitCellOwnerV1::state_owner(self).lookup(scope, operation, request) }
    fn execute(&mut self, admission: CircuitComputationAdmissionV2, input: CellStepInputV1,
        clock: impl FnMut() -> CircuitCellTimeV1) -> Result<CircuitCellExecutionV1, CircuitCellErrorV1>
    { AgentdCircuitCellOwnerV1::execute(self, admission, input, clock) }
}

#[cfg(target_os = "linux")]
impl sealed::OriginalCellPath for super::remote::DaemonCellPort {}

#[cfg(target_os = "linux")]
impl OriginalCellPort for super::remote::DaemonCellPort {
    fn registry(&self) -> &CircuitCellRegistryV1 { self.original_registry() }
    fn lookup(&self, scope: &CellScopeV1, operation: &StableId, request: Digest32)
        -> Result<Option<CellDecisionReceiptV1>, CellExecutionError>
    { self.original_lookup(scope, operation, request) }
    fn execute(&mut self, admission: CircuitComputationAdmissionV2, input: CellStepInputV1,
        mut clock: impl FnMut() -> CircuitCellTimeV1) -> Result<CircuitCellExecutionV1, CircuitCellErrorV1>
    {
        let before = clock();
        let result = self.original_execute(admission, input, before);
        let after = clock();
        if after.circuit_millis < before.circuit_millis || after.cell_micros < before.cell_micros
            || after.circuit_millis == u64::MAX || after.cell_micros == u64::MAX
        { return Err(CircuitCellErrorV1::ReconciliationRequired); }
        result
    }
}
