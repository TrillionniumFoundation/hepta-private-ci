//! Negotiated representations enter the original Circuit and Cell owners.
//! Current endpoint observations are reacquired at model contact; historical
//! readback does not require the old producer to remain the selected version.

use codex_hepta_neuron::CellNativeRepresentationInputV1;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_neuron::CellEncodedInputV1;
use codex_hepta_neuron::CellEncodingRequestV1;
use codex_hepta_neuron::InferredCellStepV1;
use codex_hepta_neuron::PreparedCellStepV1;
use codex_hepta_neuron::RegisteredCellBackendV1;

pub use codex_hepta_neuron::CellRepresentationResolverV1 as CircuitCellRepresentationResolverV1;

use super::*;

/// Per-activation data plus the original owner resolver. The long-lived Cell
/// owner and shared worker are reused; this is not a new agent turn or writer.
pub struct CircuitCellRepresentationUseV1<'a, R> {
    pub backend: &'a RegisteredCellBackendV1,
    pub input: &'a CellNativeRepresentationInputV1,
    pub resolver: &'a R,
}

impl<O, P, E> AgentdCircuitCellOwnerV1<O, P, E>
where
    O: CellStateOwnerV1,
    P: NeuronInferenceControlPort + CellInferenceReadbackPortV1,
    E: CellInputEncoderV1,
{
    /// Consume the original durable Circuit admission with its exact projected
    /// observation and backend. A stale observation before admission refuses
    /// new Cell work. A stale observation after admission leaves the original
    /// pending identity intact, with no model call and no automatic retry.
    /// Committed or uncertain historical operations use only original readback.
    pub fn execute_representation<R: CircuitCellRepresentationResolverV1>(
        &mut self,
        admission: CircuitComputationAdmissionV2,
        input: CellStepInputV1,
        representation: CircuitCellRepresentationUseV1<'_, R>,
        clock: impl FnMut() -> CircuitCellTimeV1,
    ) -> Result<CircuitCellExecutionV1, CircuitCellErrorV1> {
        representation
            .input
            .validate_backend(representation.backend)?;
        let binding = self.registry.bind_input(admission.dispatch(), &input)?;
        if binding.cell != representation.backend.registration().definition
            || input.observation != representation.input.observation_bytes()
        {
            return Err(CircuitCellErrorV1::InputMismatch);
        }
        CircuitCellExecutionOwnersV1 {
            registry: &self.registry,
            state_owner: &mut self.state_owner,
            inference_control: &mut self.inference_control,
            encoder: &representation,
        }
        .execute(admission, input, clock)
    }
}

impl<R> CellInputEncoderV1 for CircuitCellRepresentationUseV1<'_, R> {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError> {
        self.input.encode(request)
    }
}

impl<R: CircuitCellRepresentationResolverV1> CircuitCellPipelineV1
    for CircuitCellRepresentationUseV1<'_, R>
{
    fn enter(
        &self,
        definition: &CellDefinitionV1,
        owner: &impl CellStateOwnerV1,
        input: CellStepInputV1,
        now_micros: u64,
    ) -> Result<CellStepEntryV1, CellExecutionError> {
        if definition != &self.backend.registration().definition {
            return Err(CellExecutionError::IncompatibleBundle);
        }
        let current = self.resolver.current_use(&input.scope)?;
        self.backend
            .enter_representation(owner, self.input, &current, input, now_micros)
    }

    fn infer(
        &self,
        prepared: PreparedCellStepV1,
        owner: &mut impl CellStateOwnerV1,
        control: &mut impl NeuronInferenceControlPort,
        _now_micros: u64,
        clock_micros: impl FnMut() -> u64,
    ) -> Result<InferredCellStepV1, CellExecutionError> {
        self.backend.infer_representation(
            owner,
            self.input,
            prepared,
            self.resolver,
            control,
            clock_micros,
        )
    }
}
