//! On-disk projections reconstruct the original typed receipt and recheck its
//! canonical digest. Serialized values never supply acceptance authority.
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::NeuronFeatureObservationV1;
use crate::NeuronFeatureReceiptV1;
use crate::NeuronFeatureRequestV1;
use crate::NeuronFeatureTerminalStatusV1;
use crate::NeuronModelRuntimeTupleV1;
use crate::build_neuron_feature_receipt_v1;

use super::Error;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Request {
    request_id: String,
    generation: u64,
    model_id: String,
    encoder: String,
    head: String,
    weights: String,
    input: String,
    features: Vec<i64>,
    width: usize,
}
impl From<&NeuronFeatureRequestV1> for Request {
    fn from(value: &NeuronFeatureRequestV1) -> Self {
        Self {
            request_id: value.request_id.to_string(),
            generation: value.generation.get(),
            model_id: value.model_id.to_string(),
            encoder: value.encoder_digest.to_string(),
            head: value.head_digest.to_string(),
            weights: value.weights_digest.to_string(),
            input: value.input_digest.to_string(),
            features: value.feature_vector_q24.clone(),
            width: value.expected_output_width,
        }
    }
}
impl Request {
    pub(super) fn decode(self) -> Result<NeuronFeatureRequestV1, Error> {
        let request = NeuronFeatureRequestV1 {
            request_id: StableId::new(self.request_id).map_err(|_| invalid())?,
            generation: Generation::new(self.generation).map_err(|_| invalid())?,
            model_id: StableId::new(self.model_id).map_err(|_| invalid())?,
            encoder_digest: self.encoder.parse().map_err(|_| invalid())?,
            head_digest: self.head.parse().map_err(|_| invalid())?,
            weights_digest: self.weights.parse().map_err(|_| invalid())?,
            input_digest: self.input.parse().map_err(|_| invalid())?,
            feature_vector_q24: self.features,
            expected_output_width: self.width,
        };
        crate::neuron_feature_request_digest_v1(&request).map_err(|_| invalid())?;
        Ok(request)
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Receipt {
    model_manifest: String,
    weights: String,
    tokenizer: String,
    preprocessor: String,
    quantization: String,
    runtime: String,
    device: String,
    encoder: String,
    head: String,
    drive: Vec<i64>,
    prediction: Vec<i64>,
    resident_bytes: u64,
    transient_bytes: u64,
    queue_age_micros: u64,
    latency_micros: u64,
    status: Status,
    digest: String,
}
#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Status {
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}
impl From<&NeuronFeatureReceiptV1> for Receipt {
    fn from(value: &NeuronFeatureReceiptV1) -> Self {
        let runtime = &value.runtime_tuple;
        Self {
            model_manifest: runtime.model_manifest_digest.to_string(),
            weights: runtime.weights_digest.to_string(),
            tokenizer: runtime.tokenizer_digest.to_string(),
            preprocessor: runtime.preprocessor_digest.to_string(),
            quantization: runtime.quantization_digest.to_string(),
            runtime: runtime.runtime_digest.to_string(),
            device: runtime.device_digest.to_string(),
            encoder: value.encoder_digest.to_string(),
            head: value.head_digest.to_string(),
            drive: value.drive_q24.clone(),
            prediction: value.prediction_q24.clone(),
            resident_bytes: value.observed_memory_bytes,
            transient_bytes: value.transient_allocation_bytes,
            queue_age_micros: value.queue_age_micros,
            latency_micros: value.latency_micros,
            status: match value.status {
                NeuronFeatureTerminalStatusV1::Succeeded => Status::Succeeded,
                NeuronFeatureTerminalStatusV1::Failed => Status::Failed,
                NeuronFeatureTerminalStatusV1::Cancelled => Status::Cancelled,
                NeuronFeatureTerminalStatusV1::Indeterminate => Status::Indeterminate,
            },
            digest: value.receipt_digest.to_string(),
        }
    }
}
impl Receipt {
    pub(super) fn decode(
        self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, Error> {
        let receipt = build_neuron_feature_receipt_v1(
            request,
            NeuronModelRuntimeTupleV1 {
                model_id: request.model_id.clone(),
                model_manifest_digest: self.model_manifest.parse().map_err(|_| invalid())?,
                weights_digest: self.weights.parse().map_err(|_| invalid())?,
                tokenizer_digest: self.tokenizer.parse().map_err(|_| invalid())?,
                preprocessor_digest: self.preprocessor.parse().map_err(|_| invalid())?,
                quantization_digest: self.quantization.parse().map_err(|_| invalid())?,
                runtime_digest: self.runtime.parse().map_err(|_| invalid())?,
                device_digest: self.device.parse().map_err(|_| invalid())?,
            },
            NeuronFeatureObservationV1 {
                encoder_digest: self.encoder.parse().map_err(|_| invalid())?,
                head_digest: self.head.parse().map_err(|_| invalid())?,
                drive_q24: self.drive,
                prediction_q24: self.prediction,
                observed_memory_bytes: self.resident_bytes,
                transient_allocation_bytes: self.transient_bytes,
                queue_age_micros: self.queue_age_micros,
                latency_micros: self.latency_micros,
                status: match self.status {
                    Status::Succeeded => NeuronFeatureTerminalStatusV1::Succeeded,
                    Status::Failed => NeuronFeatureTerminalStatusV1::Failed,
                    Status::Cancelled => NeuronFeatureTerminalStatusV1::Cancelled,
                    Status::Indeterminate => NeuronFeatureTerminalStatusV1::Indeterminate,
                },
            },
        )
        .map_err(|_| invalid())?;
        if receipt.receipt_digest.to_string() != self.digest {
            return Err(invalid());
        }
        Ok(receipt)
    }
}
fn invalid() -> Error {
    Error::CorruptJournal("typed feature receipt or request")
}
