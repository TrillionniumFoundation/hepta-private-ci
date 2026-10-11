//! Opt-in one-call physical feature batch contract.
//!
//! A driver implementing this trait promises one backend batch, not loops
//! over single-item forwards. The host verifies call cardinality here; real
//! target-device forward counts require independent measurement.

use std::collections::BTreeSet;

use super::*;

/// An item carries the exact request and payload identities so a batched
/// backend cannot silently associate one Cell's output with another Cell.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PhysicalBatchItemObservationV1 {
    pub request_id: String,
    pub payload_digest: String,
    pub observation: DriverNeuronFeatureObservation,
}

/// Batch-level observation. All resource numbers are backend-reported until
/// independently attested by a target-host observer.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PhysicalBatchRunObservationV1 {
    /// Canonical identity of this exact ordered request group; not a proof of execution.
    pub submission_digest: String,
    /// Backend-reported identity, not independently attested hardware evidence.
    pub batch_execution_digest: String,
    pub claimed_encoder_forward_count: u32,
    pub observed_peak_memory_bytes: u64,
    pub items: Vec<PhysicalBatchItemObservationV1>,
}

/// Canonical ordered batch identity, distinct from the backend's observation.
/// Hashes each request/reservation ID, original payload, deadline, and worker
/// generation. It cannot attest that a backend physically batched inference.
pub fn canonical_physical_batch_submission_digest_v1(
    worker_id: &str,
    model_id: &str,
    generation: u64,
    requests: &[NeuronFeatureRequest],
) -> Digest32 {
    let mut bytes = b"hepta.worker.physical-batch-submission.v1".to_vec();
    for value in [worker_id, model_id] {
        push_batch_identity(&mut bytes, value);
    }
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(&(requests.len() as u64).to_be_bytes());
    for request in requests {
        for field in [
            request.authorization.request_id.as_str(),
            request.authorization.reservation_id.as_str(),
            request.authorization.model_digest.as_str(),
            request.authorization.payload_digest.as_str(),
        ] {
            push_batch_identity(&mut bytes, field);
        }
        bytes.extend_from_slice(&request.authorization.deadline_ms.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn push_batch_identity(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

/// A reviewed backend must submit the whole slice in one invocation and
/// report the exact item ordering. No sequential fallback is provided.
pub trait NeuronPhysicalBatchDriver: NeuronFeatureDriver {
    fn run_neuron_feature_batch(
        &mut self,
        handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<PhysicalBatchRunObservationV1, Error>;
}

impl<D: NeuronPhysicalBatchDriver> InferenceWorker<D> {
    /// Exactly one backend trait call after complete up-front validation;
    /// caller must wrap this inside a group final-use effect fence.
    pub(crate) fn run_physical_batch_receipts(
        &mut self,
        now_ms: u64,
        model_id: &str,
        requests: Vec<NeuronFeatureRequest>,
    ) -> Result<Vec<NeuronFeatureReceiptV1>, Error> {
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        let size = requests.len();
        let limit = self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS);
        if size == 0 || size > limit || self.active_requests.len().saturating_add(size) > limit {
            return Err(Error::RequestCapacity);
        }
        let loaded = self.models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        let manifest = loaded.manifest.clone();
        let mut identities = BTreeSet::new();
        for request in &requests {
            validate_request(now_ms, &request.authorization)?;
            validate_neuron_feature_request(request)?;
            let auth = &request.authorization;
            if auth.cancelled
                || !identities.insert(auth.request_id.clone())
                || self.active_requests.contains_key(&auth.request_id)
            {
                return Err(Error::RequestCapacity);
            }
            if auth.model_digest != manifest.model_digest
                || auth.reservation_model_digest != manifest.model_digest
                || request.weights_digest != manifest.weights_digest
            {
                return Err(Error::ModelMismatch);
            }
            if auth.maximum_tokens > manifest.maximum_tokens
                || auth.maximum_tokens > auth.reservation_maximum_tokens
            {
                return Err(Error::TokenLimit);
            }
            let digest = canonical_neuron_feature_payload_digest(request);
            if auth.payload_digest != digest || auth.lease_payload_digest != digest {
                return Err(Error::PayloadMismatch);
            }
        }
        let expected_submission_digest = canonical_physical_batch_submission_digest_v1(
            &self.worker_id,
            model_id,
            self.generation,
            &requests,
        );
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        loaded.active_requests = loaded
            .active_requests
            .checked_add(size)
            .ok_or(Error::ArithmeticOverflow)?;
        for request in &requests {
            self.active_requests.insert(
                request.authorization.request_id.clone(),
                model_id.to_owned(),
            );
        }
        // A single driver method call; no sequential fallback is available.
        let result = self
            .driver
            .run_neuron_feature_batch(&loaded.handle, &requests);
        for request in &requests {
            self.active_requests
                .remove(&request.authorization.request_id);
        }
        loaded.active_requests = loaded.active_requests.saturating_sub(size);
        let batch = result?;
        validate_digest(&batch.batch_execution_digest, "physical batch execution")?;
        if batch.submission_digest != expected_submission_digest.to_string()
            || batch.claimed_encoder_forward_count != 1
            || batch.items.len() != size
            || batch.observed_peak_memory_bytes > self.grant.maximum_memory_bytes
        {
            return Err(Error::FeatureContract);
        }
        let mut receipts = Vec::with_capacity(size);
        for (request, item) in requests.into_iter().zip(batch.items) {
            if item.request_id != request.authorization.request_id
                || item.payload_digest != request.authorization.payload_digest
            {
                return Err(Error::FeatureContract);
            }
            let observed = item.observation;
            if observed.observed_memory_bytes > self.grant.maximum_memory_bytes {
                return Err(Error::ModelCapacity);
            }
            let status = if !observed.terminal_observed {
                NeuronFeatureTerminalStatusV1::Indeterminate
            } else if observed.succeeded {
                validate_neuron_feature_output(&request, &observed)?;
                NeuronFeatureTerminalStatusV1::Succeeded
            } else {
                NeuronFeatureTerminalStatusV1::Failed
            };
            let control_request = NeuronFeatureRequestV1 {
                request_id: StableId::new(request.authorization.request_id)
                    .map_err(|_| Error::FeatureContract)?,
                generation: Generation::new(self.generation).map_err(|_| Error::FeatureContract)?,
                model_id: StableId::new(manifest.model_id.clone())
                    .map_err(|_| Error::FeatureContract)?,
                encoder_digest: parse_digest32(&request.encoder_digest)?,
                head_digest: parse_digest32(&request.head_digest)?,
                weights_digest: parse_digest32(&request.weights_digest)?,
                input_digest: parse_digest32(&request.input_digest)?,
                feature_vector_q24: request.feature_vector_q24,
                expected_output_width: request.expected_output_width,
            };
            let runtime_tuple = NeuronModelRuntimeTupleV1 {
                model_id: control_request.model_id.clone(),
                model_manifest_digest: parse_digest32(&manifest.model_digest)?,
                weights_digest: parse_digest32(&manifest.weights_digest)?,
                tokenizer_digest: parse_digest32(&manifest.tokenizer_digest)?,
                preprocessor_digest: parse_digest32(&manifest.preprocessor_digest)?,
                quantization_digest: parse_digest32(&manifest.quantization_digest)?,
                runtime_digest: parse_digest32(&manifest.runtime_digest)?,
                device_digest: parse_digest32(&manifest.device_digest)?,
            };
            receipts.push(
                build_neuron_feature_receipt_v1(
                    &control_request,
                    runtime_tuple,
                    NeuronFeatureObservationV1 {
                        encoder_digest: parse_digest32(&observed.encoder_digest)?,
                        head_digest: parse_digest32(&observed.head_digest)?,
                        drive_q24: observed.drive_q24,
                        prediction_q24: observed.prediction_q24,
                        observed_memory_bytes: observed.observed_memory_bytes,
                        transient_allocation_bytes: observed.transient_allocation_bytes,
                        queue_age_micros: observed.queue_age_micros,
                        latency_micros: observed.latency_micros,
                        status,
                    },
                )
                .map_err(|_| Error::FeatureContract)?,
            );
        }
        Ok(receipts)
    }
}

#[cfg(test)]
#[path = "model_worker_physical_batch_tests.rs"]
mod tests;
