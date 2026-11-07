//! Final live clock check after durable Cell admission and before model contact.
//! Refusal leaves the original pending record intact; it never permits redispatch.

use codex_hepta_neuron::CellExecutionError;
use codex_hepta_neuron::NeuronFeatureReceiptV1;
use codex_hepta_neuron::NeuronFeatureRequestV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;

use crate::CircuitCellTimeV1;

pub(super) struct GuardedCellDispatchV1<'a, P, C> {
    control: &'a mut P,
    clock: &'a mut C,
    not_before: CircuitCellTimeV1,
    circuit_deadline_ms: u64,
    cell_deadline_micros: u64,
    observed: Option<CircuitCellTimeV1>,
    validate_new_use: &'a mut dyn FnMut() -> Result<(), CellExecutionError>,
}

impl<'a, P, C> GuardedCellDispatchV1<'a, P, C> {
    pub(super) fn new(
        control: &'a mut P,
        clock: &'a mut C,
        not_before: CircuitCellTimeV1,
        circuit_deadline_ms: u64,
        cell_deadline_micros: u64,
        validate_new_use: &'a mut dyn FnMut() -> Result<(), CellExecutionError>,
    ) -> Self {
        Self {
            control,
            clock,
            not_before,
            circuit_deadline_ms,
            cell_deadline_micros,
            observed: None,
            validate_new_use,
        }
    }

    pub(super) fn observed_at(&self) -> Option<CircuitCellTimeV1> {
        self.observed
    }
}

impl<P, C> NeuronInferenceControlPort for GuardedCellDispatchV1<'_, P, C>
where
    P: NeuronInferenceControlPort,
    C: FnMut() -> CircuitCellTimeV1,
{
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        (self.validate_new_use)().map_err(|_| NeuronModelError::Rejected)?;
        let now = (self.clock)();
        if now.circuit_millis < self.not_before.circuit_millis
            || now.cell_micros < self.not_before.cell_micros
            || now.circuit_millis >= self.circuit_deadline_ms
            || now.cell_micros >= self.cell_deadline_micros
        {
            return Err(NeuronModelError::Rejected);
        }
        self.observed = Some(now);
        self.control.execute_feature(request)
    }
}
