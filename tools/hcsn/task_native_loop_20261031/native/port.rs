//! Autonomous decision runs inside the actual Hepta NeuronModelPort.
use crate::cell::Cell;
use crate::policy::Controller;
use crate::policy::Policy;
use crate::policy::{self};
use crate::task::Action;
use crate::task::State;
use codex_hepta_neuron::*;
use serde::Deserialize;
use serde::Serialize;
use std::time::Instant;

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
pub struct Costs {
    pub query_nanos: u64,
    pub critic_nanos: u64,
    pub decision_nanos: u64,
    pub propagation_nanos: u64,
    pub content_nanos: u64,
    pub persist_nanos: u64,
}

pub fn nanos(start: Instant) -> u64 {
    start.elapsed().as_nanos().try_into().unwrap_or(u64::MAX)
}

pub struct DecisionPort<'a> {
    pub config: NeuronRuntimeConfigV1,
    pub expected_input: Vec<i64>,
    pub public_features: Vec<f64>,
    pub cell: &'a Cell,
    pub policy: &'a Policy,
    pub state: &'a State,
    pub legal: [bool; 4],
    pub driver: f64,
    pub horizon_micros: u64,
    pub action: Option<Action>,
    pub features: Option<[f64; 5]>,
    pub q: Option<[f64; 4]>,
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
        let action = match self.policy.controller {
            Controller::Value => {
                let query_start = Instant::now();
                let features = self
                    .cell
                    .query(self.driver, self.horizon_micros)
                    .map_err(|_| NeuronModelError::Rejected)?;
                self.costs.query_nanos = nanos(query_start);
                let critic_start = Instant::now();
                let q = self
                    .policy
                    .predict(&self.public_features, features)
                    .map_err(|_| NeuronModelError::Rejected)?;
                self.costs.critic_nanos = nanos(critic_start);
                self.features = Some(features);
                self.q = Some(q);
                let decision_start = Instant::now();
                let action = policy::select(q, self.legal);
                self.costs.decision_nanos = nanos(decision_start);
                action
            }
            Controller::Fixed | Controller::DirectFixed => {
                let decision_start = Instant::now();
                let action = policy::fixed(self.state, self.legal);
                self.costs.decision_nanos = nanos(decision_start);
                action
            }
        };
        if !self.legal[action.index()] {
            return Err(NeuronModelError::Rejected);
        }
        self.action = Some(action);
        // This is the selected-action signal, not a quantized substitute critic.
        let mut drive = vec![0; 5];
        drive[action.index()] = crate::native::Q;
        let receipt = LocalModelRuntimeReceiptV1 {
            model_id: self.config.model_id.clone(),
            model_manifest_digest: self.config.model_manifest_digest,
            weights_digest: self.config.weights_digest,
            tokenizer_digest: self.config.tokenizer_digest,
            preprocessor_digest: self.config.preprocessor_digest,
            quantization_id: crate::native::id("task-selected-action.q24.v1"),
            quantization_digest: self.config.quantization_digest,
            backend_id: crate::native::id("rust.factorial-native-task.v1"),
            runtime_digest: self.config.runtime_digest,
            device_identity_digest: self.config.device_digest,
            latency_micros: start.elapsed().as_micros().try_into().unwrap_or(u64::MAX),
            resident_bytes: ((67 * 24 + 24 * 4 + 24 + 4 + 134) * 8) as u64,
        };
        let prediction = vec![0; 5];
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
