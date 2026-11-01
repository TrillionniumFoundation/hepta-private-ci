//! Decisions execute within the pinned Hepta NeuronModelPort before packet access.
use crate::cell;
use crate::policy;
use crate::runtime;
use crate::task;
use codex_hepta_neuron::*;
use serde::Deserialize;
use serde::Serialize;
use std::time::Instant;

pub fn nanos(start: Instant) -> u64 {
    start.elapsed().as_nanos().try_into().unwrap_or(u64::MAX)
}

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
pub struct Costs {
    pub representation_nanos: u64,
    pub neural_nanos: u64,
    pub selection_nanos: u64,
    pub propagation_nanos: u64,
    pub content_nanos: u64,
    pub persist_nanos: u64,
}

pub struct DecisionPort<'a> {
    pub config: NeuronRuntimeConfigV1,
    pub expected_input: Vec<i64>,
    pub public_features: Vec<f64>,
    pub cell: &'a cell::State,
    pub state: &'a task::State,
    pub policy: &'a policy::Policy,
    pub controller: policy::Controller,
    pub legal: [bool; 6],
    pub forced: Option<usize>,
    pub action: Option<usize>,
    pub representation: Option<[f64; 12]>,
    pub scores: Option<policy::Scores>,
    pub costs: Costs,
    pub execution_nanos: u64,
}

impl NeuronModelPort for DecisionPort<'_> {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let start = Instant::now();
        if request.feature_vector_q24 != self.expected_input
            || request.weights_digest != self.config.weights_digest
        {
            return Err(NeuronModelError::Rejected);
        }
        let representation_start = Instant::now();
        let representation = self
            .policy
            .representation(self.state, self.cell)
            .map_err(|_| NeuronModelError::Rejected)?;
        self.costs.representation_nanos = nanos(representation_start);
        let neural_start = Instant::now();
        let scores = self
            .policy
            .predict(&self.public_features, &representation)
            .map_err(|_| NeuronModelError::Rejected)?;
        self.costs.neural_nanos = nanos(neural_start);
        let selection_start = Instant::now();
        let action = match self.forced {
            Some(a) if a < 6 && self.legal[a] => a,
            Some(_) => return Err(NeuronModelError::Rejected),
            None => policy::select(&scores, self.legal, self.state, self.controller)
                .map_err(|_| NeuronModelError::Rejected)?,
        };
        self.costs.selection_nanos = nanos(selection_start);
        self.action = Some(action);
        self.representation = Some(representation);
        self.scores = Some(scores);
        let mut drive = vec![0; 6];
        drive[action] = runtime::Q24;
        let receipt = LocalModelRuntimeReceiptV1 {
            model_id: self.config.model_id.clone(),
            model_manifest_digest: self.config.model_manifest_digest,
            weights_digest: self.config.weights_digest,
            tokenizer_digest: self.config.tokenizer_digest,
            preprocessor_digest: self.config.preprocessor_digest,
            quantization_id: runtime::id("digital.selected-action.q24.v1"),
            quantization_digest: self.config.quantization_digest,
            backend_id: runtime::id("rust.digital.preread.finite17.v1"),
            runtime_digest: self.config.runtime_digest,
            device_identity_digest: self.config.device_digest,
            latency_micros: start.elapsed().as_micros().try_into().unwrap_or(u64::MAX),
            resident_bytes: ((48 * 32 + 32 + 32 * 7 + 7) * 8) as u64,
        };
        let prediction = vec![0; 6];
        let output_digest = canonical_model_output_digest_v1(&drive, &prediction, &receipt)
            .map_err(|_| NeuronModelError::Rejected)?;
        self.execution_nanos = nanos(start);
        Ok(NeuronModelOutputV1 {
            encoder_digest: self.config.encoder_digest,
            head_digest: self.config.head_digest,
            output_digest,
            drive_q24: drive,
            prediction_q24: prediction,
            queue_age_micros: 0,
            transient_allocation_bytes: 4096,
            runtime_receipt: receipt,
        })
    }
}
