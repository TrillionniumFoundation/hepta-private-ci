//! Exact model-port execution of frozen encoder coefficients.
use crate::measure;
use crate::model;
use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use std::time::Instant;
pub struct Port {
    pub profile: model::Profile,
    pub config: NeuronRuntimeConfigV1,
}
impl NeuronInferenceControlPort for Port {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let started = Instant::now();
        let baseline = measure::start_window();
        let c = &self.config;
        if request.generation != c.generation
            || request.model_id != c.model_id
            || request.encoder_digest != c.encoder_digest
            || request.head_digest != c.head_digest
            || request.weights_digest != c.weights_digest
            || request.expected_output_width != c.state_width
        {
            return Err(NeuronModelError::Rejected);
        }
        let drive = self
            .profile
            .encode(&request.feature_vector_q24)
            .map_err(|_| NeuronModelError::Rejected)?;
        build_neuron_feature_receipt_v1(
            request,
            NeuronModelRuntimeTupleV1 {
                model_id: c.model_id.clone(),
                model_manifest_digest: c.model_manifest_digest,
                weights_digest: c.weights_digest,
                tokenizer_digest: c.tokenizer_digest,
                preprocessor_digest: c.preprocessor_digest,
                quantization_digest: c.quantization_digest,
                runtime_digest: c.runtime_digest,
                device_digest: c.device_digest,
            },
            NeuronFeatureObservationV1 {
                encoder_digest: c.encoder_digest,
                head_digest: c.head_digest,
                drive_q24: drive.clone(),
                prediction_q24: drive,
                observed_memory_bytes: measure::live_bytes() as u64,
                transient_allocation_bytes: measure::peak_delta(baseline) as u64,
                queue_age_micros: 0,
                latency_micros: started.elapsed().as_micros() as u64,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        )
        .map_err(|_| NeuronModelError::Rejected)
    }
}
