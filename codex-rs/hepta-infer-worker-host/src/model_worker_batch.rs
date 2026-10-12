//! Bounded, explicitly native backend-batch boundary for Neuron feature execution.
//!
//! A batch is one driver invocation, never an implicit loop over the
//! single-request entrypoint. Driver instrumentation is NOT a production
//! attestation of a fused tensor kernel, scope admission, WAL durability,
//! or independent utility. The owning inference control must supply those.

use std::collections::BTreeSet;

use super::*;

const MAX_NEURON_BACKEND_BATCH: usize = 32;

/// A driver must echo the exact identity of every submitted batch member.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverNeuronBatchMember {
    pub request_id: String,
    pub input_digest: String,
    pub observation: DriverNeuronFeatureObservation,
}

/// Backend-observed resource counters; not an independently signed measurement.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverNeuronBackendBatch {
    pub batch_digest: String,
    pub members: Vec<DriverNeuronBatchMember>,
    pub observed_peak_memory_bytes: u64,
    pub backend_elapsed_micros: u64,
}

/// Only a backend with a real batch implementation may implement this trait.
/// There is deliberately no default that sequentially calls run_neuron_features.
pub trait NeuronBackendBatchDriver: NeuronFeatureDriver {
    fn run_neuron_backend_batch(
        &mut self,
        handle: &DriverModelHandle,
        batch_digest: &str,
        requests: &[NeuronFeatureRequest],
    ) -> Result<DriverNeuronBackendBatch, Error>;
}

/// Typed, separately bound model receipts from a single backend-batch call.
/// It carries no authority to select, promote, sign, commit state or execute tools.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronBackendBatchReceipt {
    pub batch_digest: String,
    pub receipts: Vec<NeuronFeatureReceiptV1>,
    pub observed_peak_memory_bytes: u64,
    pub backend_elapsed_micros: u64,
}

fn length_prefixed(bytes: &mut Vec<u8>, field: &str) {
    bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
    bytes.extend_from_slice(field.as_bytes());
}

/// Content-derived grouping identity, *not* a signature or proof of computation.
#[must_use]
pub fn canonical_neuron_batch_digest(
    model_id: &str,
    generation: u64,
    requests: &[NeuronFeatureRequest],
) -> String {
    let mut bytes = b"hepta.infer-worker.neuron-backend-batch.v1".to_vec();
    length_prefixed(&mut bytes, model_id);
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(&(requests.len() as u64).to_be_bytes());
    for request in requests {
        length_prefixed(&mut bytes, &request.authorization.request_id);
        length_prefixed(&mut bytes, &request.authorization.reservation_id);
        length_prefixed(&mut bytes, &request.authorization.payload_digest);
        length_prefixed(&mut bytes, &request.input_digest);
        length_prefixed(&mut bytes, &request.encoder_digest);
        length_prefixed(&mut bytes, &request.head_digest);
    }
    Digest32::of_bytes(&bytes).to_string()
}

impl<D: ModelDriver + NeuronBackendBatchDriver> InferenceWorker<D> {
    /// Preflight every member before dispatch. Either every validated member
    /// receives an individually bound receipt, or no receipts are returned.
    /// The caller must separately record true enqueue/start/end clock readings.
    pub fn run_neuron_features_backend_batch(
        &mut self,
        now_ms: u64,
        model_id: &str,
        requests: Vec<NeuronFeatureRequest>,
    ) -> Result<NeuronBackendBatchReceipt, Error> {
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        if !(2..=MAX_NEURON_BACKEND_BATCH).contains(&requests.len()) {
            return Err(Error::FeatureBatchLimit);
        }
        let limit = self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS);
        if self
            .active_requests
            .len()
            .checked_add(requests.len())
            .ok_or(Error::ArithmeticOverflow)?
            > limit
        {
            return Err(Error::RequestCapacity);
        }
        let loaded = self.models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.unload_indeterminate {
            return Err(Error::ModelUnloadIndeterminate);
        }
        let exemplar = &requests[0];
        let encoder = &exemplar.encoder_digest;
        let input_width = exemplar.feature_vector_q24.len();
        let output_width = exemplar.expected_output_width;
        let mut seen = BTreeSet::new();
        let mut seen_reservations = BTreeSet::new();
        for request in &requests {
            validate_request(now_ms, &request.authorization)?;
            validate_neuron_feature_request(request)?;
            // Each WorkerRequest binds one reservation to one request. A batch
            // must not double-spend that reservation even with distinct request
            // IDs and independently computed per-input payload digests.
            if !seen.insert(request.authorization.request_id.clone())
                || !seen_reservations.insert(request.authorization.reservation_id.clone())
                || self
                    .active_requests
                    .contains_key(&request.authorization.request_id)
                || request.authorization.cancelled
                || &request.encoder_digest != encoder
                || request.feature_vector_q24.len() != input_width
                || request.expected_output_width != output_width
            {
                return Err(Error::FeatureBatchMismatch);
            }
            if request.authorization.model_digest != loaded.manifest.model_digest
                || request.authorization.reservation_model_digest != loaded.manifest.model_digest
                || request.weights_digest != loaded.manifest.weights_digest
            {
                return Err(Error::ModelMismatch);
            }
            if request.authorization.maximum_tokens > loaded.manifest.maximum_tokens {
                return Err(Error::TokenLimit);
            }
            let canonical_payload = canonical_neuron_feature_payload_digest(request);
            if request.authorization.payload_digest != canonical_payload
                || request.authorization.lease_payload_digest != canonical_payload
            {
                return Err(Error::PayloadMismatch);
            }
        }

        let handle = loaded.handle.clone();
        let manifest = loaded.manifest.clone();
        let count = requests.len();
        let already_active = loaded
            .active_requests
            .checked_add(count)
            .ok_or(Error::ArithmeticOverflow)?;
        let batch_digest = canonical_neuron_batch_digest(model_id, self.generation, &requests);

        // Admission is all-or-none, including duplicate-ID and capacity checks.
        self.models
            .get_mut(model_id)
            .ok_or(Error::ModelNotLoaded)?
            .active_requests = already_active;
        for request in &requests {
            self.active_requests.insert(
                request.authorization.request_id.clone(),
                model_id.to_string(),
            );
        }
        let executed = self
            .driver
            .run_neuron_backend_batch(&handle, &batch_digest, &requests);
        // Always release in-flight reservations, including on driver error.
        for request in &requests {
            self.active_requests
                .remove(&request.authorization.request_id);
        }
        self.models
            .get_mut(model_id)
            .ok_or(Error::ModelNotLoaded)?
            .active_requests -= count;
        let executed = match executed {
            Ok(value) => value,
            Err(_) => {
                // A driver error does not prove that the physical batch never
                // began; prevent replay of any member in this generation.
                self.execution_indeterminate = true;
                return Err(Error::ExecutionIndeterminate);
            }
        };

        if executed.batch_digest != batch_digest
            || executed.members.len() != count
            || executed.observed_peak_memory_bytes > self.grant.maximum_memory_bytes
            || executed.observed_peak_memory_bytes < handle.observed_memory_bytes
        {
            self.execution_indeterminate = true;
            return Err(Error::FeatureBatchMismatch);
        }
        if executed
            .members
            .iter()
            .any(|member| !member.observation.terminal_observed)
        {
            // A partially observed batch cannot be split into safe
            // successes/retries without an independent execution ledger.
            self.execution_indeterminate = true;
            return Err(Error::ExecutionIndeterminate);
        }

        let mut receipts = Vec::with_capacity(count);
        for (request, member) in requests.into_iter().zip(executed.members) {
            if member.request_id != request.authorization.request_id
                || member.input_digest != request.input_digest
                || member.observation.observed_memory_bytes > executed.observed_peak_memory_bytes
            {
                self.execution_indeterminate = true;
                return Err(Error::FeatureBatchMismatch);
            }
            let observation = member.observation;
            let status = if observation.succeeded {
                if let Err(error) = validate_neuron_feature_output(&request, &observation) {
                    self.execution_indeterminate = true;
                    return Err(error);
                }
                ExecutionStatus::Succeeded
            } else {
                ExecutionStatus::Failed
            };
            let checked = NeuronFeatureExecutionObservation {
                request_id: request.authorization.request_id.clone(),
                reservation_id: request.authorization.reservation_id.clone(),
                worker_generation: self.generation,
                manifest: manifest.clone(),
                encoder_digest: observation.encoder_digest,
                head_digest: observation.head_digest,
                input_digest: request.input_digest.clone(),
                status,
                drive_q24: observation.drive_q24,
                prediction_q24: observation.prediction_q24,
                observed_memory_bytes: observation.observed_memory_bytes,
                transient_allocation_bytes: observation.transient_allocation_bytes,
                queue_age_micros: observation.queue_age_micros,
                latency_micros: observation.latency_micros,
                terminal_observed: observation.terminal_observed,
            };
            match project_neuron_feature_receipt(request, checked) {
                Ok(receipt) => receipts.push(receipt),
                Err(error) => {
                    self.execution_indeterminate = true;
                    return Err(error);
                }
            }
        }
        Ok(NeuronBackendBatchReceipt {
            batch_digest,
            receipts,
            observed_peak_memory_bytes: executed.observed_peak_memory_bytes,
            backend_elapsed_micros: executed.backend_elapsed_micros,
        })
    }
}
