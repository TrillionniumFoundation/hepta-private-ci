//! Executed, deterministic research projection; not a trained RR-SNN backend.
use codex_hepta_infer_core::{
    NeuronFeatureObservationV1, NeuronFeatureReceiptV1, NeuronFeatureRequestV1,
    NeuronFeatureTerminalStatusV1, NeuronModelRuntimeTupleV1, build_neuron_feature_receipt_v1,
};
use codex_hepta_neuron::{NeuronInferenceControlPort, NeuronModelError};
use codex_hepta_types::{Digest32, StableId};
use std::fs;
use std::time::Instant;

pub const Q: i64 = 1 << 24;
pub const INPUTS: usize = 22;
pub const WIDTH: usize = 8;

pub fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub fn id(value: impl Into<String>) -> StableId {
    StableId::new(value.into()).expect("bounded research identity")
}

pub fn process_memory(field: &str) -> Result<u64, NeuronModelError> {
    let data =
        fs::read_to_string("/proc/self/status").map_err(|_| NeuronModelError::Unavailable)?;
    let line = data
        .lines()
        .find(|line| line.starts_with(field))
        .ok_or(NeuronModelError::Unavailable)?;
    let value = line
        .split_whitespace()
        .nth(1)
        .ok_or(NeuronModelError::Unavailable)?
        .parse::<u64>()
        .map_err(|_| NeuronModelError::Unavailable)?;
    value.checked_mul(1024).ok_or(NeuronModelError::Unavailable)
}

pub struct Projection {
    pub tuple: NeuronModelRuntimeTupleV1,
    pub weights: Vec<i64>,
    pub calls: usize,
    pub queue_started: Instant,
    pub corrupt_receipt: bool,
}

impl Projection {
    pub fn new(binary: &[u8], device: &[u8]) -> Self {
        let weights = (0..WIDTH * INPUTS)
            .map(|i| ((i * 17 % 19) as i64 - 9) * Q / 32)
            .collect::<Vec<_>>();
        let bytes = weights
            .iter()
            .flat_map(|x| x.to_be_bytes())
            .collect::<Vec<_>>();
        Self {
            tuple: NeuronModelRuntimeTupleV1 {
                model_id: id("research.native-owner.fixed-projection.v1"),
                model_manifest_digest: digest(
                    "executed fixed signed Q24 matrix; 8x22; no trained quality claim",
                ),
                weights_digest: Digest32::of_bytes(&bytes),
                tokenizer_digest: digest("numeric features; tokenizer not applicable"),
                preprocessor_digest: digest("identity Q24 feature input v1"),
                quantization_digest: digest("signed Q24; i128 accumulation; clamp +/-2 Q24"),
                runtime_digest: Digest32::of_bytes(binary),
                device_digest: Digest32::of_bytes(device),
            },
            weights,
            calls: 0,
            queue_started: Instant::now(),
            corrupt_receipt: false,
        }
    }
}

impl NeuronInferenceControlPort for Projection {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        if request.expected_output_width != WIDTH
            || request.feature_vector_q24.len() != INPUTS
            || request.model_id != self.tuple.model_id
            || request.weights_digest != self.tuple.weights_digest
        {
            return Err(NeuronModelError::Rejected);
        }
        let queue_age = self
            .queue_started
            .elapsed()
            .as_micros()
            .min(u64::MAX as u128) as u64;
        let started = Instant::now();
        let drive_q24 = self
            .weights
            .chunks_exact(INPUTS)
            .map(|row| {
                let value = row
                    .iter()
                    .zip(&request.feature_vector_q24)
                    .map(|(weight, input)| i128::from(*weight) * i128::from(*input))
                    .sum::<i128>()
                    / i128::from(Q);
                value.clamp(-i128::from(2 * Q), i128::from(2 * Q)) as i64
            })
            .collect::<Vec<_>>();
        let prediction_q24 = vec![0; WIDTH];
        let resident = process_memory("VmRSS:")?;
        let latency = started.elapsed().as_micros().min(u64::MAX as u128) as u64;
        let transient =
            ((drive_q24.capacity() + prediction_q24.capacity()) * size_of::<i64>()) as u64;
        let mut receipt = build_neuron_feature_receipt_v1(
            request,
            self.tuple.clone(),
            NeuronFeatureObservationV1 {
                encoder_digest: request.encoder_digest,
                head_digest: request.head_digest,
                drive_q24,
                prediction_q24,
                observed_memory_bytes: resident,
                transient_allocation_bytes: transient,
                queue_age_micros: queue_age,
                latency_micros: latency,
                status: NeuronFeatureTerminalStatusV1::Succeeded,
            },
        )
        .map_err(|_| NeuronModelError::Rejected)?;
        self.calls += 1;
        if self.corrupt_receipt {
            receipt.receipt_digest = digest("deliberately corrupt research receipt");
        }
        Ok(receipt)
    }
}
