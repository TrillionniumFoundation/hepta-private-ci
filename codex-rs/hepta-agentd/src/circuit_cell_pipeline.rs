//! Private execution strategy. Representation work cannot select the ordinary
//! fresh entry/dispatch primitives while historical encoding remains reusable.

use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_neuron::CellEncodedInputV1;
use codex_hepta_neuron::CellEncodingRequestV1;
use codex_hepta_neuron::InferredCellStepV1;
use codex_hepta_neuron::PreparedCellStepV1;
use codex_hepta_neuron::enter_cell_step;
use codex_hepta_neuron::infer_cell;

use super::*;

pub(super) trait CircuitCellPipelineV1: CellInputEncoderV1 {
    fn enter(
        &self,
        definition: &CellDefinitionV1,
        owner: &impl CellStateOwnerV1,
        input: CellStepInputV1,
        now_micros: u64,
    ) -> Result<CellStepEntryV1, CellExecutionError>;

    fn infer(
        &self,
        prepared: PreparedCellStepV1,
        owner: &mut impl CellStateOwnerV1,
        control: &mut impl NeuronInferenceControlPort,
        now_micros: u64,
        clock_micros: impl FnMut() -> u64,
    ) -> Result<InferredCellStepV1, CellExecutionError>;
}

pub(super) struct NativeCellPipelineV1<'a, E>(pub(super) &'a E);

impl<E: CellInputEncoderV1> CellInputEncoderV1 for NativeCellPipelineV1<'_, E> {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError> {
        self.0.encode(request)
    }
}

impl<E: CellInputEncoderV1> CircuitCellPipelineV1 for NativeCellPipelineV1<'_, E> {
    fn enter(
        &self,
        definition: &CellDefinitionV1,
        owner: &impl CellStateOwnerV1,
        input: CellStepInputV1,
        now_micros: u64,
    ) -> Result<CellStepEntryV1, CellExecutionError> {
        enter_cell_step(definition, owner, self.0, input, now_micros)
    }

    fn infer(
        &self,
        prepared: PreparedCellStepV1,
        owner: &mut impl CellStateOwnerV1,
        control: &mut impl NeuronInferenceControlPort,
        now_micros: u64,
        _clock_micros: impl FnMut() -> u64,
    ) -> Result<InferredCellStepV1, CellExecutionError> {
        infer_cell(prepared, owner, control, now_micros)
    }
}
