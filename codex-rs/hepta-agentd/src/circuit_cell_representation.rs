//! Negotiated representations enter the original Circuit and Cell owners.
//! Current endpoint observations are reacquired at model contact; historical
//! readback does not require the old producer to remain the selected version.

use codex_hepta_neuron::CellNativeRepresentationInputV1;
use codex_hepta_neuron::CellRepresentationUseV1;
use codex_hepta_neuron::CellScopeV1;
use codex_hepta_neuron::RegisteredCellBackendV1;

use super::*;

/// Resolve the existing source and consumer owners' current observations.
/// Implementations must authenticate those owners and their selected contracts;
/// copying pins out of the negotiated input is not a current observation.
/// This read-only callback must return promptly and grants no effect authority.
pub trait CircuitCellRepresentationResolverV1 {
    fn current_use(
        &self,
        scope: &CellScopeV1,
    ) -> Result<CellRepresentationUseV1, CellExecutionError>;
}

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
        representation.input.validate_backend(representation.backend)?;
        let binding = self.registry.bind_input(admission.dispatch(), &input)?;
        if binding.cell != representation.backend.registration().definition
            || input.observation != representation.input.observation_bytes()
        {
            return Err(CircuitCellErrorV1::InputMismatch);
        }
        let scope = input.scope.clone();
        CircuitCellExecutionOwnersV1 {
            registry: &self.registry,
            state_owner: &mut self.state_owner,
            inference_control: &mut self.inference_control,
            encoder: representation.input,
        }
        .execute(admission, input, clock, || {
            representation.input.validate_current_use(
                representation.backend,
                &representation.resolver.current_use(&scope)?,
            )
        })
    }
}
