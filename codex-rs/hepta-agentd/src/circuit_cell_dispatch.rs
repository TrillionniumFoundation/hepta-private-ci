//! Final live clock check after durable Cell admission and before model contact.
//! Refusal leaves the original pending record intact; it never permits redispatch.

use codex_hepta_neuron::NeuronFeatureReceiptV1;
use codex_hepta_neuron::NeuronFeatureRequestV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;

use crate::CircuitCellTimeV1;

/// Both the typed Cell checks and the enclosing Circuit guard sample this one
/// clock. The final guard must observe rollback relative to every intervening
/// sample, not merely relative to the earlier prepare/admission boundary.
pub(super) struct MonotonicCircuitCellClockV1<C> {
    clock: C,
    last: CircuitCellTimeV1,
    invalid: bool,
}

impl<C: FnMut() -> CircuitCellTimeV1> MonotonicCircuitCellClockV1<C> {
    pub(super) fn new(clock: C, last: CircuitCellTimeV1) -> Self {
        Self {
            clock,
            last,
            invalid: false,
        }
    }

    pub(super) fn sample(&mut self) -> CircuitCellTimeV1 {
        let observed = (self.clock)();
        if self.invalid
            || observed.circuit_millis < self.last.circuit_millis
            || observed.cell_micros < self.last.cell_micros
        {
            self.invalid = true;
            // An invalid sample is an absorbing failure, never a clamped time
            // or a claim of currentness. Both existing guards reject zero:
            // valid Cell input/admission timestamps are strictly positive.
            return CircuitCellTimeV1 {
                circuit_millis: 0,
                cell_micros: 0,
            };
        }
        self.last = observed;
        observed
    }
}

pub(super) struct GuardedCellDispatchV1<'a, P, C> {
    control: &'a mut P,
    clock: &'a mut C,
    not_before: CircuitCellTimeV1,
    circuit_deadline_ms: u64,
    cell_deadline_micros: u64,
    observed: Option<CircuitCellTimeV1>,
}

impl<'a, P, C> GuardedCellDispatchV1<'a, P, C> {
    pub(super) fn new(
        control: &'a mut P,
        clock: &'a mut C,
        not_before: CircuitCellTimeV1,
        circuit_deadline_ms: u64,
        cell_deadline_micros: u64,
    ) -> Self {
        Self {
            control,
            clock,
            not_before,
            circuit_deadline_ms,
            cell_deadline_micros,
            observed: None,
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
