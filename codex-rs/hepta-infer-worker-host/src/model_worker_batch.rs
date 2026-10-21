//! Research-only batch-admission seam for the existing loaded Neuron model.
//! External crates cannot invoke this new batch path until an independent,
//! exact-binding signed Final-use owner is part of the execution API.
//!
//! This module NEVER fakes backend batching by repeatedly calling the V1
//! single-request driver. A backend must implement one batch invocation; absent
//! that implementation, the API is not available. Outputs remain non-authorizing
//! worker observations subject to inference-control receipt verification.

use std::collections::BTreeSet;

use super::DriverModelHandle;
use super::DriverNeuronFeatureObservation;
use super::Error;
use super::ExecutionStatus;
use super::InferenceWorker;
use super::MAX_ACTIVE_REQUESTS;
use super::ModelDriver;
use super::NeuronFeatureDriver;
use super::NeuronFeatureExecutionObservation;
use super::NeuronFeatureRequest;
use super::canonical_neuron_feature_payload_digest;
use super::validate_identity;
use super::validate_neuron_feature_output;
use super::validate_neuron_feature_request;
use super::validate_request;

/// Each batch row binds the exact request ID AND payload identity; without
/// these fields two same-head/same-width requests could be silently swapped.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronFeatureBatchItemObservationV2 {
    pub request_id: String,
    pub payload_digest: String,
    pub feature: DriverNeuronFeatureObservation,
}

/// A research-only, crate-private backend seam. It is intentionally not
/// a public execution capability until an independently signed final-use
/// admission API is present. Never implement by looping over V1 requests.
/// A physical backend implements one batch forward over compatible requests.
pub(crate) trait NeuronFeatureBatchDriver: ModelDriver + NeuronFeatureDriver {
    fn run_neuron_features_batch(
        &mut self,
        handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<Vec<NeuronFeatureBatchItemObservationV2>, Error>;
}

/// Admission floor for independent Q24 drive/prediction output buffers.
/// This is a pre-dispatch lower bound, not measured backend RSS.
fn minimum_neuron_batch_output_bytes(requests: &[NeuronFeatureRequest]) -> Result<u64, Error> {
    requests.iter().try_fold(0_u64, |total, item| {
        let width =
            u64::try_from(item.expected_output_width).map_err(|_| Error::ArithmeticOverflow)?;
        let bytes = width
            .checked_mul(2)
            .and_then(|elements| elements.checked_mul(8))
            .ok_or(Error::ArithmeticOverflow)?;
        total.checked_add(bytes).ok_or(Error::ArithmeticOverflow)
    })
}

/// Independent V1 Q24 input Vec allocations are not shared Arc buffers.
/// Charge every request once; do not deduplicate by equal bytes or digest.
fn minimum_neuron_batch_input_bytes(requests: &[NeuronFeatureRequest]) -> Result<u64, Error> {
    requests.iter().try_fold(0_u64, |total, item| {
        let length =
            u64::try_from(item.feature_vector_q24.len()).map_err(|_| Error::ArithmeticOverflow)?;
        let bytes = length.checked_mul(8).ok_or(Error::ArithmeticOverflow)?;
        total.checked_add(bytes).ok_or(Error::ArithmeticOverflow)
    })
}

impl<D: ModelDriver + NeuronFeatureDriver + NeuronFeatureBatchDriver> InferenceWorker<D> {
    /// Admit the entire batch before dispatch and reject partial/aliased results.
    /// Every item binds an independently admitted request, lease and reservation;
    /// requests share the loaded model, encoder and tensor shapes, not authority.
    pub(crate) fn run_neuron_features_batch(
        &mut self,
        now_ms: u64,
        model_id: &str,
        requests: Vec<NeuronFeatureRequest>,
    ) -> Result<Vec<NeuronFeatureExecutionObservation>, Error> {
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        if requests.is_empty() || requests.len() > 32 {
            return Err(Error::FeatureLimit);
        }
        let request_limit = self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS);
        let next_active = self
            .active_requests
            .len()
            .checked_add(requests.len())
            .ok_or(Error::ArithmeticOverflow)?;
        if next_active > request_limit {
            return Err(Error::RequestCapacity);
        }
        let selected = self.models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        let batch_encoder = &requests[0].encoder_digest;
        let input_width = requests[0].feature_vector_q24.len();
        let output_width = requests[0].expected_output_width;
        let mut ids = BTreeSet::new();
        let mut reservation_ids = BTreeSet::new();
        for item in &requests {
            validate_request(now_ms, &item.authorization)?;
            validate_neuron_feature_request(item)?;
            if item.authorization.cancelled {
                // A cancelled item must never sneak into an admitted batch.
                return Err(Error::FeatureContract);
            }
            if item.authorization.model_digest != selected.manifest.model_digest
                || item.authorization.reservation_model_digest != selected.manifest.model_digest
                || item.weights_digest != selected.manifest.weights_digest
            {
                return Err(Error::ModelMismatch);
            }
            if item.authorization.maximum_tokens > selected.manifest.maximum_tokens
                || item.authorization.maximum_tokens > item.authorization.reservation_maximum_tokens
            {
                return Err(Error::TokenLimit);
            }
            if item.encoder_digest != *batch_encoder
                || item.feature_vector_q24.len() != input_width
                || item.expected_output_width != output_width
            {
                return Err(Error::FeatureContract);
            }
            if !ids.insert(&item.authorization.request_id)
                || self
                    .active_requests
                    .contains_key(&item.authorization.request_id)
            {
                return Err(Error::RequestCapacity);
            }
            // One reservation must not be double-spent by different batch rows.
            if !reservation_ids.insert(item.authorization.reservation_id.as_str()) {
                return Err(Error::FeatureContract);
            }
            let actual = canonical_neuron_feature_payload_digest(item);
            if item.authorization.payload_digest != actual
                || item.authorization.lease_payload_digest != actual
            {
                return Err(Error::PayloadMismatch);
            }
        }

        // Every row allocates its own drive/prediction outputs, even though
        // the backend receives just one batch call. Reject a batch whose
        // minimum simultaneous output footprint exceeds the worker grant
        // before reserving request slots or invoking the driver.
        let resident_bytes = self
            .models
            .values()
            .try_fold(0_u64, |total, loaded| {
                total.checked_add(loaded.handle.observed_memory_bytes)
            })
            .ok_or(Error::ArithmeticOverflow)?;
        let input_bytes = minimum_neuron_batch_input_bytes(&requests)?;
        let minimum_bytes = resident_bytes
            .checked_add(minimum_neuron_batch_output_bytes(&requests)?)
            .and_then(|total| total.checked_add(input_bytes))
            .ok_or(Error::ArithmeticOverflow)?;
        if minimum_bytes > self.grant.maximum_memory_bytes {
            return Err(Error::ModelCapacity);
        }

        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        loaded.active_requests = loaded
            .active_requests
            .checked_add(requests.len())
            .ok_or(Error::ArithmeticOverflow)?;
        for item in &requests {
            self.active_requests
                .insert(item.authorization.request_id.clone(), model_id.to_string());
        }

        // Exactly one backend batch call, without serial fallback.
        let driver_result = self
            .driver
            .run_neuron_features_batch(&loaded.handle, &requests);

        // Release reservations on success AND on backend error or missing output.
        for item in &requests {
            self.active_requests.remove(&item.authorization.request_id);
        }
        loaded.active_requests = loaded.active_requests.saturating_sub(requests.len());

        // Once physical dispatch was attempted, a missing/invalid receipt
        // cannot prove that no Cell execution occurred. The worker stays
        // fenced until the owner reconciles or starts a new generation.
        let observations = match driver_result {
            Ok(observations) => observations,
            Err(error) => {
                self.poisoned = true;
                return Err(error);
            }
        };
        if observations.len() != requests.len() {
            self.poisoned = true;
            return Err(Error::FeatureOutputMismatch);
        }
        let mut result = Vec::with_capacity(requests.len());
        for (request, batch_item) in requests.iter().zip(observations) {
            if batch_item.request_id != request.authorization.request_id
                || batch_item.payload_digest != request.authorization.payload_digest
            {
                self.poisoned = true;
                return Err(Error::PayloadMismatch);
            }
            let observed = batch_item.feature;
            if observed.observed_memory_bytes > self.grant.maximum_memory_bytes
                || observed.encoder_digest != request.encoder_digest
                || observed.head_digest != request.head_digest
            {
                self.poisoned = true;
                return Err(Error::FeatureOutputMismatch);
            }
            let status = if !observed.terminal_observed {
                ExecutionStatus::Indeterminate
            } else if observed.succeeded {
                if let Err(error) = validate_neuron_feature_output(request, &observed) {
                    self.poisoned = true;
                    return Err(error);
                }
                ExecutionStatus::Succeeded
            } else {
                ExecutionStatus::Failed
            };
            // No unverifiable output is published for failure/unknown terminality.
            if status != ExecutionStatus::Succeeded
                && (!observed.drive_q24.is_empty() || !observed.prediction_q24.is_empty())
            {
                self.poisoned = true;
                return Err(Error::FeatureOutputMismatch);
            }
            if status == ExecutionStatus::Indeterminate {
                self.poisoned = true;
            }
            result.push(NeuronFeatureExecutionObservation {
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
            });
        }
        Ok(result)
    }

    /// Project the entire physical batch through the same exact V1 typed
    /// receipt verifier used by the single-request production boundary.
    /// V1 owns a Vec per request; this compatibility bridge intentionally
    /// still clones those vectors. A true zero-copy V2 transport is separate.
    pub(crate) fn run_neuron_features_batch_receipts(
        &mut self,
        now_ms: u64,
        model_id: &str,
        requests: Vec<NeuronFeatureRequest>,
    ) -> Result<Vec<codex_hepta_infer_core::NeuronFeatureReceiptV1>, Error> {
        let copies = requests.clone();
        let outcomes = self.run_neuron_features_batch(now_ms, model_id, requests)?;
        let receipts: Result<Vec<codex_hepta_infer_core::NeuronFeatureReceiptV1>, Error> = copies
            .into_iter()
            .zip(outcomes)
            .map(|(request, outcome)| super::project_neuron_feature_receipt_v1(request, outcome))
            .collect();
        if receipts.is_err() {
            self.poisoned = true;
        }
        receipts
    }
}

#[cfg(test)]
mod tests {
    use super::super::DriverRunObservation;
    use super::super::ModelManifest;
    use super::super::ResourceGrant;
    use super::super::WorkerRequest;
    use super::*;

    #[derive(Default)]
    struct BatchMock {
        batches: usize,
        single_calls: usize,
        truncated: bool,
        corrupt_head: bool,
        indeterminate_with_output: bool,
        swap_items: bool,
        fail_batch: bool,
    }

    impl ModelDriver for BatchMock {
        fn load(&mut self, _: &ModelManifest) -> Result<DriverModelHandle, Error> {
            Ok(DriverModelHandle {
                opaque_id: "model.handle".to_string(),
                observed_memory_bytes: 1024,
            })
        }
        fn run(
            &mut self,
            _: &DriverModelHandle,
            _: &WorkerRequest,
        ) -> Result<DriverRunObservation, Error> {
            self.single_calls += 1;
            Err(Error::FeatureContract)
        }
        fn unload(&mut self, _: DriverModelHandle) -> Result<(), Error> {
            Ok(())
        }
    }

    impl NeuronFeatureDriver for BatchMock {
        fn run_neuron_features(
            &mut self,
            _: &DriverModelHandle,
            _: &NeuronFeatureRequest,
        ) -> Result<DriverNeuronFeatureObservation, Error> {
            self.single_calls += 1;
            Err(Error::FeatureContract)
        }
    }

    impl NeuronFeatureBatchDriver for BatchMock {
        fn run_neuron_features_batch(
            &mut self,
            _: &DriverModelHandle,
            requests: &[NeuronFeatureRequest],
        ) -> Result<Vec<NeuronFeatureBatchItemObservationV2>, Error> {
            self.batches += 1;
            if self.fail_batch {
                return Err(Error::DriverFailure(
                    "batch terminality unknown".to_string(),
                ));
            }
            let mut outputs: Vec<_> = requests
                .iter()
                .map(|req| NeuronFeatureBatchItemObservationV2 {
                    request_id: req.authorization.request_id.clone(),
                    payload_digest: req.authorization.payload_digest.clone(),
                    feature: DriverNeuronFeatureObservation {
                        terminal_observed: !self.indeterminate_with_output,
                        succeeded: true,
                        encoder_digest: req.encoder_digest.clone(),
                        head_digest: if self.corrupt_head {
                            "f".repeat(64)
                        } else {
                            req.head_digest.clone()
                        },
                        drive_q24: vec![1 << 24; req.expected_output_width],
                        prediction_q24: vec![0; req.expected_output_width],
                        observed_memory_bytes: 2048,
                        transient_allocation_bytes: 128,
                        queue_age_micros: 3,
                        latency_micros: 10,
                    },
                })
                .collect();
            if self.truncated {
                outputs.pop();
            }
            if self.swap_items {
                outputs.reverse();
            }
            Ok(outputs)
        }
    }

    fn worker(driver: BatchMock) -> InferenceWorker<BatchMock> {
        worker_with_memory_budget(driver, 4096)
    }

    fn worker_with_memory_budget(
        driver: BatchMock,
        maximum_memory_bytes: u64,
    ) -> InferenceWorker<BatchMock> {
        let grant = ResourceGrant {
            grant_id: "grant.v2".into(),
            authority_epoch: 3,
            generation: 5,
            expires_at_ms: 10_000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 4,
            maximum_memory_bytes,
            semantic_digest: "1".repeat(64),
        };
        let mut worker =
            InferenceWorker::new(1, "worker.v2".into(), 5, grant, driver).expect("worker");
        worker
            .load_model(
                1,
                ModelManifest {
                    model_id: "model.v2".into(),
                    model_digest: "2".repeat(64),
                    weights_digest: "3".repeat(64),
                    tokenizer_digest: "4".repeat(64),
                    preprocessor_digest: "5".repeat(64),
                    quantization_digest: "6".repeat(64),
                    runtime_digest: "7".repeat(64),
                    device_digest: "8".repeat(64),
                    maximum_tokens: 128,
                },
            )
            .expect("load");
        worker
    }

    fn feature(id: &str, head: char) -> NeuronFeatureRequest {
        let mut request = NeuronFeatureRequest {
            authorization: WorkerRequest {
                request_id: id.to_string(),
                reservation_id: format!("reservation.{id}"),
                model_digest: "2".repeat(64),
                payload_digest: "0".repeat(64),
                maximum_tokens: 64,
                deadline_ms: 9000,
                lease_payload_digest: "0".repeat(64),
                reservation_model_digest: "2".repeat(64),
                reservation_maximum_tokens: 64,
                cancelled: false,
            },
            encoder_digest: "a".repeat(64),
            head_digest: head.to_string().repeat(64),
            weights_digest: "3".repeat(64),
            input_digest: "c".repeat(64),
            feature_vector_q24: vec![1 << 22, -(1 << 21)],
            expected_output_width: 3,
        };
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        request
    }

    #[test]
    fn dispatches_exactly_one_backend_batch_and_returns_ordered_outputs() {
        let mut worker = worker(BatchMock::default());
        let results = worker
            .run_neuron_features_batch(
                100,
                "model.v2",
                vec![feature("request.1", 'b'), feature("request.2", 'c')],
            )
            .expect("batch");
        assert_eq!(results.len(), 2);
        assert_eq!(results[0].request_id, "request.1");
        assert_eq!(results[1].head_digest, "c".repeat(64));
        assert!(
            results
                .iter()
                .all(|r| r.status == ExecutionStatus::Succeeded)
        );
        assert_eq!(worker.driver.batches, 1);
        assert_eq!(worker.driver.single_calls, 0);
        assert!(worker.active_requests.is_empty());
        assert_eq!(worker.models["model.v2"].active_requests, 0);
    }

    #[test]
    fn batch_v1_receipts_are_individually_verified_without_single_backend_calls() {
        let mut worker = worker(BatchMock::default());
        let receipts = worker
            .run_neuron_features_batch_receipts(
                100,
                "model.v2",
                vec![feature("request.1", 'b'), feature("request.2", 'c')],
            )
            .expect("batch receipts");
        assert_eq!(receipts.len(), 2);
        assert_eq!(receipts[0].drive_q24, vec![1 << 24; 3]);
        assert_ne!(receipts[0].head_digest, receipts[1].head_digest);
        assert_eq!(worker.driver.batches, 1);
        assert_eq!(worker.driver.single_calls, 0);
        assert!(!receipts[0].authority.grants_any());
    }

    #[test]
    fn duplicate_and_payload_drift_fail_before_dispatch() {
        let mut worker = worker(BatchMock::default());
        assert_eq!(
            worker.run_neuron_features_batch(
                100,
                "model.v2",
                vec![feature("request.1", 'b'), feature("request.1", 'b'),]
            ),
            Err(Error::RequestCapacity)
        );
        let first = feature("request.1", 'b');
        let mut same_reservation = feature("request.2", 'c');
        same_reservation.authorization.reservation_id = first.authorization.reservation_id.clone();
        let digest = canonical_neuron_feature_payload_digest(&same_reservation);
        same_reservation.authorization.payload_digest = digest.clone();
        same_reservation.authorization.lease_payload_digest = digest;
        assert_eq!(
            worker.run_neuron_features_batch(100, "model.v2", vec![first, same_reservation]),
            Err(Error::FeatureContract)
        );
        let mut changed = feature("request.2", 'c');
        changed.feature_vector_q24[0] += 1;
        assert_eq!(
            worker.run_neuron_features_batch(100, "model.v2", vec![changed]),
            Err(Error::PayloadMismatch)
        );
        assert_eq!(worker.driver.batches, 0);
    }

    #[test]
    fn whole_batch_output_floor_rejects_before_mutating_slots_or_dispatch() {
        // Loaded model owns 1024 bytes. Two independent width-3 Q24 output
        // pairs need at least 2 * 3 * 2 * 8 more bytes, not just one pair.
        // Outputs fit at this limit; the additional V1 Vec inputs do not.
        let maximum_memory_bytes = 1024 + (2 * 3 * 2 * 8) + (2 * 2 * 8) - 1;
        let mut worker = worker_with_memory_budget(BatchMock::default(), maximum_memory_bytes);
        assert_eq!(
            worker.run_neuron_features_batch(
                100,
                "model.v2",
                vec![feature("request.1", 'b'), feature("request.2", 'c')],
            ),
            Err(Error::ModelCapacity)
        );
        assert_eq!(worker.driver.batches, 0);
        assert_eq!(worker.driver.single_calls, 0);
        assert!(worker.active_requests.is_empty());
        assert_eq!(worker.models["model.v2"].active_requests, 0);
        assert!(!worker.poisoned);
        assert_eq!(
            minimum_neuron_batch_input_bytes(&[
                feature("request.1", 'b'),
                feature("request.2", 'c'),
            ]),
            Ok(32)
        );
    }

    #[test]
    fn rejects_token_budget_above_loaded_model_and_reservation() {
        let mut worker = worker(BatchMock::default());
        let mut oversized = feature("request.over", 'b');
        oversized.authorization.maximum_tokens = 129;
        oversized.authorization.reservation_maximum_tokens = 129;
        assert_eq!(
            worker.run_neuron_features_batch(100, "model.v2", vec![oversized]),
            Err(Error::TokenLimit)
        );
        let mut oversubscribed = feature("request.over", 'b');
        oversubscribed.authorization.maximum_tokens = 65;
        assert_eq!(
            worker.run_neuron_features_batch(100, "model.v2", vec![oversubscribed]),
            Err(Error::TokenLimit)
        );
        assert_eq!(worker.driver.batches, 0);
    }

    #[test]
    fn incompatible_encoder_and_cancelled_request_fail_before_dispatch() {
        let mut worker = worker(BatchMock::default());
        let mut changed = feature("request.2", 'c');
        changed.encoder_digest = "d".repeat(64);
        let payload = canonical_neuron_feature_payload_digest(&changed);
        changed.authorization.payload_digest = payload.clone();
        changed.authorization.lease_payload_digest = payload;
        assert_eq!(
            worker.run_neuron_features_batch(
                100,
                "model.v2",
                vec![feature("request.1", 'b'), changed,]
            ),
            Err(Error::FeatureContract)
        );
        let mut cancelled = feature("request.3", 'd');
        cancelled.authorization.cancelled = true;
        assert_eq!(
            worker.run_neuron_features_batch(100, "model.v2", vec![cancelled]),
            Err(Error::FeatureContract)
        );
        assert_eq!(worker.driver.batches, 0);
    }

    #[test]
    fn reordered_identical_head_outputs_are_rejected_as_payload_mismatch() {
        let mut worker = worker(BatchMock {
            swap_items: true,
            ..BatchMock::default()
        });
        let err = worker.run_neuron_features_batch(
            100,
            "model.v2",
            vec![feature("request.1", 'b'), feature("request.2", 'b')],
        );
        assert_eq!(err, Err(Error::PayloadMismatch));
        assert!(worker.active_requests.is_empty());
        assert_eq!(worker.models["model.v2"].active_requests, 0);
        assert!(worker.poisoned);
        assert_eq!(
            worker.run_neuron_features_batch(100, "model.v2", vec![feature("request.3", 'b')]),
            Err(Error::IndeterminateLifecycle)
        );
    }

    #[test]
    fn malformed_driver_results_are_not_published_and_slots_are_released() {
        for driver in [
            BatchMock {
                truncated: true,
                ..BatchMock::default()
            },
            BatchMock {
                corrupt_head: true,
                ..BatchMock::default()
            },
            BatchMock {
                indeterminate_with_output: true,
                ..BatchMock::default()
            },
        ] {
            let mut worker = worker(driver);
            let err = worker.run_neuron_features_batch(
                100,
                "model.v2",
                vec![feature("request.1", 'b'), feature("request.2", 'c')],
            );
            assert_eq!(err, Err(Error::FeatureOutputMismatch));
            assert!(worker.active_requests.is_empty());
            assert_eq!(worker.models["model.v2"].active_requests, 0);
            assert!(worker.poisoned);
        }
    }

    #[test]
    fn driver_error_after_batch_dispatch_fences_worker_and_releases_slots() {
        let mut worker = worker(BatchMock {
            fail_batch: true,
            ..BatchMock::default()
        });
        assert_eq!(
            worker.run_neuron_features_batch(100, "model.v2", vec![feature("request.1", 'b')]),
            Err(Error::DriverFailure(
                "batch terminality unknown".to_string()
            ))
        );
        assert_eq!(worker.driver.batches, 1);
        assert!(worker.active_requests.is_empty());
        assert_eq!(worker.models["model.v2"].active_requests, 0);
        assert!(worker.poisoned);
        assert_eq!(
            worker.run_neuron_features_batch(100, "model.v2", vec![feature("request.2", 'b')]),
            Err(Error::IndeterminateLifecycle)
        );
        assert_eq!(worker.driver.batches, 1);
    }
}
