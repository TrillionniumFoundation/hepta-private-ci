//! Consuming erasure of the original factory's Cell resources. The ordinary
//! local loop and the Root pump take the same one-shot slot; neither can clone
//! a writer or install a second Cell. No external callback constructs this lane.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_automation::CircuitDispatchV2;
use codex_hepta_neuron::CellInferenceReadbackPortV1;
use codex_hepta_neuron::CellInputEncoderV1;
use codex_hepta_neuron::CellStateOwnerV1;
use codex_hepta_neuron::CellStepInputV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::canonical_cell_step_request_digest_v1;

use super::CircuitTaskErrorV1 as Error;
use super::CircuitTaskInputProviderV1;
use super::remote::OriginalRemoteAdmission;
use crate::AgentdCircuitCellOwnerV1;
use crate::CircuitCellErrorV1;
use crate::CircuitCellExecutionV1;
use crate::CircuitCellTimeV1;

pub(super) struct OriginalOwners<O, P, E, I, C> {
    pub(super) cells: AgentdCircuitCellOwnerV1<O, P, E>,
    pub(super) inputs: I,
    pub(super) clock: C,
}

mod sealed {
    pub trait OriginalPump {}
    pub trait OriginalFactory {}
}

/// Erasure only of the concrete original Q24 factory owners. This trait is
/// crate-internal and implemented only below; the Root service has no callback
/// or public constructor for injecting a substituted Cell pump.
pub(crate) trait OriginalRootCellPump: sealed::OriginalPump + Send {
    fn clock(&mut self) -> CircuitCellTimeV1;
    fn execute(&mut self, admission: OriginalRemoteAdmission, input: CellStepInputV1)
        -> Result<CircuitCellExecutionV1, Error>;
    fn read(&mut self, dispatch: &CircuitDispatchV2, input: &CellStepInputV1)
        -> Result<CircuitCellExecutionV1, Error>;
}

/// Consuming erasure of the same private factory slot. Only OriginalFactory
/// below implements it; callers cannot provide a replacement writer factory.
pub(super) trait OriginalRootLaneFactory: sealed::OriginalFactory + Send {
    fn original_handoff_registry(&self) -> Result<(Vec<u8>, usize), Error>;
    fn take_original_root_cell_pump(self: Box<Self>) -> Result<Box<dyn OriginalRootCellPump>, Error>;
}

struct OriginalFactory<O, P, E, I, C>(Arc<Mutex<Option<OriginalOwners<O, P, E, I, C>>>>, usize);
struct OriginalPump<O, P, E, C> { cells: AgentdCircuitCellOwnerV1<O, P, E>, clock: C }

impl<O, P, E, I, C> sealed::OriginalFactory for OriginalFactory<O, P, E, I, C> {}
impl<O, P, E, C> sealed::OriginalPump for OriginalPump<O, P, E, C> {}

pub(super) fn retain<O, P, E, I, C>(
    owners: Arc<Mutex<Option<OriginalOwners<O, P, E, I, C>>>>,
    capacity: usize,
) -> Box<dyn OriginalRootLaneFactory>
where
    O: CellStateOwnerV1 + Send + 'static,
    P: NeuronInferenceControlPort + CellInferenceReadbackPortV1 + Send + 'static,
    E: CellInputEncoderV1 + Send + 'static,
    I: CircuitTaskInputProviderV1 + 'static,
    C: FnMut() -> CircuitCellTimeV1 + Send + 'static,
{ Box::new(OriginalFactory(owners, capacity)) }

impl<O, P, E, I, C> OriginalRootLaneFactory for OriginalFactory<O, P, E, I, C>
where
    O: CellStateOwnerV1 + Send + 'static,
    P: NeuronInferenceControlPort + CellInferenceReadbackPortV1 + Send + 'static,
    E: CellInputEncoderV1 + Send + 'static,
    I: CircuitTaskInputProviderV1 + 'static,
    C: FnMut() -> CircuitCellTimeV1 + Send + 'static,
{
    fn original_handoff_registry(&self) -> Result<(Vec<u8>, usize), Error> {
        let owners = self.0.try_lock().map_err(|_| Error::Unavailable)?;
        let original = owners.as_ref().ok_or(Error::Unavailable)?;
        Ok((crate::circuit_cell_binding::root_bootstrap::encode(original.cells.registry())?, self.1))
    }

    fn take_original_root_cell_pump(self: Box<Self>) -> Result<Box<dyn OriginalRootCellPump>, Error> {
        let owners = self.0.try_lock().map_err(|_| Error::Unavailable)?
            .take().ok_or(Error::Unavailable)?;
        Ok(Box::new(OriginalPump { cells: owners.cells, clock: owners.clock }))
    }
}

impl<O, P, E, C> OriginalRootCellPump for OriginalPump<O, P, E, C>
where
    O: CellStateOwnerV1 + Send,
    P: NeuronInferenceControlPort + CellInferenceReadbackPortV1 + Send,
    E: CellInputEncoderV1 + Send,
    C: FnMut() -> CircuitCellTimeV1 + Send,
{
    fn clock(&mut self) -> CircuitCellTimeV1 { (self.clock)() }

    fn execute(&mut self, admission: OriginalRemoteAdmission, input: CellStepInputV1)
        -> Result<CircuitCellExecutionV1, Error>
    { AgentdCircuitCellOwnerV1::execute_original_remote(&mut self.cells, admission, input, &mut self.clock).map_err(Error::from) }

    fn read(&mut self, dispatch: &CircuitDispatchV2, input: &CellStepInputV1)
        -> Result<CircuitCellExecutionV1, Error>
    {
        let binding = self.cells.registry().bind_input(dispatch, input)?;
        let digest = canonical_cell_step_request_digest_v1(&binding.cell, input)
            .map_err(CircuitCellErrorV1::from)?;
        let decision = self.cells.state_owner().lookup(&input.scope, &input.operation_id, digest)
            .map_err(CircuitCellErrorV1::from)?.ok_or(Error::ReconciliationRequired)?;
        crate::circuit_cell::finish(binding, dispatch, input, decision).map_err(Error::from)
    }
}
