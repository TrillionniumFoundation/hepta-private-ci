//! Explicit physical neuron-feature batch dispatch. Source admission, model
//! identity and resource budgets are validated before any model effect.
//! Unsupported drivers never silently simulate batching.

use super::*;
use std::collections::BTreeSet;

impl<D: ModelDriver + NeuronFeatureDriver> InferenceWorker<D> {
    pub(crate) fn supports_native_neuron_batch(&self) -> bool {
        self.driver.supports_native_neuron_batch()
    }

    pub(crate) fn run_neuron_features_receipts_batch(
        &mut self,
        now_ms: u64,
        model_id: &str,
        requests: Vec<NeuronFeatureRequest>,
    ) -> Result<Vec<NeuronFeatureReceiptV1>, Error> {
        if requests.len() < 2
            || requests.len() > MAX_ACTIVE_REQUESTS
            || !self.driver.supports_native_neuron_batch()
        {
            return Err(Error::FeatureContract);
        }
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        let limit = self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS);
        if self.active_requests.len().saturating_add(requests.len()) > limit {
            return Err(Error::RequestCapacity);
        }
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        let new_active = loaded
            .active_requests
            .checked_add(requests.len())
            .ok_or(Error::ArithmeticOverflow)?;
        if new_active > limit {
            return Err(Error::RequestCapacity);
        }
        let mut ids = BTreeSet::new();
        for request in &requests {
            validate_request(now_ms, &request.authorization)?;
            validate_neuron_feature_request(request)?;
            if request.authorization.cancelled {
                return Err(Error::InvalidGrant);
            }
            if !ids.insert(request.authorization.request_id.clone())
                || self.active_requests.contains_key(&request.authorization.request_id)
            {
                return Err(Error::RequestCapacity);
            }
            if request.authorization.model_digest != loaded.manifest.model_digest
                || request.authorization.reservation_model_digest != loaded.manifest.model_digest
                || request.weights_digest != loaded.manifest.weights_digest
            {
                return Err(Error::ModelMismatch);
            }
            let payload = canonical_neuron_feature_payload_digest(request);
            if request.authorization.payload_digest != payload
                || request.authorization.lease_payload_digest != payload
            {
                return Err(Error::PayloadMismatch);
            }
        }
        loaded.active_requests = new_active;
        for request in &requests {
            self.active_requests.insert(
                request.authorization.request_id.clone(),
                model_id.to_string(),
            );
        }
        // This is ONE driver entry; an opt-in backend may submit one physical
        // CPU/GPU batch. Failure is terminal/indeterminate, never auto-retried.
        let observed = self
            .driver
            .run_neuron_features_batch(&loaded.handle, &requests);
        for request in &requests {
            self.active_requests.remove(&request.authorization.request_id);
        }
        loaded.active_requests -= requests.len();
        let observed = observed?;
        if observed.len() != requests.len() {
            return Err(Error::FeatureOutputMismatch);
        }
        let mut receipts = Vec::with_capacity(requests.len());
        for (request, observed) in requests.into_iter().zip(observed) {
            if observed.observed_memory_bytes > self.grant.maximum_memory_bytes {
                return Err(Error::ModelCapacity);
            }
            let status = if !observed.terminal_observed {
                ExecutionStatus::Indeterminate
            } else if observed.succeeded {
                validate_neuron_feature_output(&request, &observed)?;
                ExecutionStatus::Succeeded
            } else {
                ExecutionStatus::Failed
            };
            let terminal = NeuronFeatureExecutionObservation {
                request_id: request.authorization.request_id.clone(),
                reservation_id: request.authorization.reservation_id.clone(),
                worker_generation: self.generation,
                manifest: loaded.manifest.clone(),
                encoder_digest: observed.encoder_digest,
                head_digest: observed.head_digest,
                input_digest: request.input_digest.clone(),
                status,
                drive_q24: observed.drive_q24,
                prediction_q24: observed.prediction_q24,
                observed_memory_bytes: observed.observed_memory_bytes,
                transient_allocation_bytes: observed.transient_allocation_bytes,
                queue_age_micros: observed.queue_age_micros,
                latency_micros: observed.latency_micros,
                terminal_observed: observed.terminal_observed,
            };
            receipts.push(project_neuron_receipt(request, terminal)?);
        }
        Ok(receipts)
    }
}
