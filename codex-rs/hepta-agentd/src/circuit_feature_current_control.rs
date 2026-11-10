//! CURRENT gates around the original Feature control, including its native
//! entry clock after both durable admission and dispatch fsyncs.

use codex_hepta_neuron::CellInferenceAdmissionV1;
use codex_hepta_neuron::CellInferenceReadbackPortV1;
use codex_hepta_neuron::ControlledNeuronFeaturePortV1;
use codex_hepta_neuron::DurableInferenceControl;
use codex_hepta_neuron::NeuronFeatureReceiptV1;
use codex_hepta_neuron::NeuronFeatureRequestV1;
use codex_hepta_neuron::NeuronFeatureWorkerV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;

use super::*;

pub struct PublishedCircuitFeatureControlV1<P> {
    original: P,
    task: PublishedCircuitFeatureTaskV1,
}

impl PublishedCircuitFeatureTaskV1 {
    pub fn control<W: NeuronFeatureWorkerV1>(
        &self,
        original: DurableInferenceControl,
        worker_generation: u64,
        worker: W,
        clock: Arc<dyn Fn() -> u64 + Send + Sync>,
    ) -> Result<PublishedCircuitFeatureControlV1<ControlledNeuronFeaturePortV1<W>>, NeuronModelError>
    {
        self.require_current()
            .map_err(|_| NeuronModelError::Rejected)?;
        let task = self.clone();
        let guarded_clock = Arc::new(move || {
            if task.require_active().is_err() {
                return u64::MAX;
            }
            clock()
        });
        let original = ControlledNeuronFeaturePortV1::new(
            original,
            self.definition().clone(),
            worker_generation,
            worker,
            guarded_clock,
        )?;
        self.require_current()
            .map_err(|_| NeuronModelError::Rejected)?;
        Ok(PublishedCircuitFeatureControlV1 {
            original,
            task: self.clone(),
        })
    }

    fn require_admission(
        &self,
        admission: &CellInferenceAdmissionV1,
    ) -> Result<(), NeuronModelError> {
        self.require_current()
            .map_err(|_| NeuronModelError::Indeterminate)?;
        let input = source_input(self.source(), admission.operation_id.clone());
        if admission.snapshot.scope != input.scope
            || admission.snapshot.source_frontier != input.source_frontier
            || admission.snapshot.writer_epoch != self.0.publication.target().writer_epoch()
            || admission.snapshot.revision != 0
            || admission.snapshot.checkpoint.is_some()
            || admission.snapshot.definition_digest
                != self
                    .definition()
                    .semantic_digest()
                    .map_err(|_| NeuronModelError::Rejected)?
            || admission.semantic_request_digest
                != canonical_cell_step_request_digest_v1(self.definition(), &input)
                    .map_err(|_| NeuronModelError::Rejected)?
            || admission.deadline_micros != input.deadline_micros
            || admission.admitted_at_micros < input.monotonic_micros
        {
            return Err(NeuronModelError::Rejected);
        }
        Ok(())
    }
}

impl<P: NeuronInferenceControlPort> NeuronInferenceControlPort
    for PublishedCircuitFeatureControlV1<P>
{
    fn bind_cell_inference(
        &mut self,
        admission: &CellInferenceAdmissionV1,
    ) -> Result<(), NeuronModelError> {
        self.task
            .require_active()
            .map_err(|_| NeuronModelError::Indeterminate)?;
        self.task.require_admission(admission)?;
        self.original.bind_cell_inference(admission)?;
        self.task
            .require_active()
            .map_err(|_| NeuronModelError::Indeterminate)
    }

    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        self.task
            .require_active()
            .map_err(|_| NeuronModelError::Indeterminate)?;
        let result = self.original.execute_feature(request)?;
        self.task
            .require_current()
            .map_err(|_| NeuronModelError::Indeterminate)?;
        Ok(result)
    }
}

impl<P: CellInferenceReadbackPortV1> CellInferenceReadbackPortV1
    for PublishedCircuitFeatureControlV1<P>
{
    fn bind_cell_readback(
        &mut self,
        admission: &CellInferenceAdmissionV1,
    ) -> Result<(), NeuronModelError> {
        self.task.require_admission(admission)?;
        self.original.bind_cell_readback(admission)?;
        self.task
            .require_current()
            .map_err(|_| NeuronModelError::Indeterminate)
    }

    fn read_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.task
            .require_current()
            .map_err(|_| NeuronModelError::Indeterminate)?;
        let result = self.original.read_feature(request)?;
        self.task
            .require_current()
            .map_err(|_| NeuronModelError::Indeterminate)?;
        Ok(result)
    }
}
