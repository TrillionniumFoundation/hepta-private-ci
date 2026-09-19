//! Adapter from the registered inference-control feature contract to the
//! neuron runtime's local model port.

use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::verify_neuron_feature_receipt_v1;
use codex_hepta_types::StableId;

use crate::LocalModelRuntimeReceiptV1;
use crate::NeuronModelError;
use crate::NeuronModelOutputV1;
use crate::NeuronModelPort;
use crate::NeuronModelRequestV1;
use crate::canonical_model_output_digest_v1;

/// Product hosts implement this port using the inference.control owner. The
/// implementation may dispatch to a local worker, but this module never depends
/// on worker-private APIs or grants.
pub trait NeuronInferenceControlPort {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError>;
}

pub struct InferenceControlModelPort<'a, P: NeuronInferenceControlPort> {
    control: &'a mut P,
}

impl<'a, P: NeuronInferenceControlPort> InferenceControlModelPort<'a, P> {
    pub fn new(control: &'a mut P) -> Self {
        Self { control }
    }
}

impl<P: NeuronInferenceControlPort> NeuronModelPort for InferenceControlModelPort<'_, P> {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let control_request = NeuronFeatureRequestV1 {
            request_id: request.request_id.clone(),
            generation: request.generation,
            model_id: request.model_id.clone(),
            encoder_digest: request.encoder_digest,
            head_digest: request.head_digest,
            weights_digest: request.weights_digest,
            input_digest: request.input_digest,
            feature_vector_q24: request.feature_vector_q24.clone(),
            expected_output_width: request.expected_output_width,
        };
        let receipt = self.control.execute_feature(&control_request)?;
        verify_neuron_feature_receipt_v1(&control_request, &receipt)
            .map_err(|_| NeuronModelError::Rejected)?;
        match receipt.status {
            NeuronFeatureTerminalStatusV1::Succeeded => {}
            NeuronFeatureTerminalStatusV1::Indeterminate => {
                return Err(NeuronModelError::Indeterminate);
            }
            NeuronFeatureTerminalStatusV1::Failed
            | NeuronFeatureTerminalStatusV1::Cancelled => {
                return Err(NeuronModelError::Rejected);
            }
        }
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id: receipt.runtime_tuple.model_id.clone(),
            model_manifest_digest: receipt.runtime_tuple.model_manifest_digest,
            weights_digest: receipt.runtime_tuple.weights_digest,
            tokenizer_digest: receipt.runtime_tuple.tokenizer_digest,
            preprocessor_digest: receipt.runtime_tuple.preprocessor_digest,
            quantization_id: digest_id("quantization", receipt.runtime_tuple.quantization_digest)?,
            quantization_digest: receipt.runtime_tuple.quantization_digest,
            backend_id: digest_id("runtime", receipt.runtime_tuple.runtime_digest)?,
            runtime_digest: receipt.runtime_tuple.runtime_digest,
            device_identity_digest: receipt.runtime_tuple.device_digest,
            latency_micros: receipt.latency_micros,
            resident_bytes: receipt.observed_memory_bytes,
        };
        let output_digest = canonical_model_output_digest_v1(
            &receipt.drive_q24,
            &receipt.prediction_q24,
            &runtime_receipt,
        )
        .map_err(|_| NeuronModelError::Rejected)?;
        Ok(NeuronModelOutputV1 {
            encoder_digest: receipt.encoder_digest,
            head_digest: receipt.head_digest,
            output_digest,
            drive_q24: receipt.drive_q24,
            prediction_q24: receipt.prediction_q24,
            queue_age_micros: receipt.queue_age_micros,
            transient_allocation_bytes: receipt.transient_allocation_bytes,
            runtime_receipt,
        })
    }
}

fn digest_id(prefix: &str, digest: codex_hepta_types::Digest32) -> Result<StableId, NeuronModelError> {
    StableId::new(format!("{prefix}:{digest}")).map_err(|_| NeuronModelError::Rejected)
}

#[cfg(test)]
#[path = "inference_control_tests.rs"]
mod tests;
