//! Authenticated bounded worker-side inference microbatch execution.
//!
//! The planner is not an effect owner. Each dequeued item is independently
//! checked against the loaded model and a fresh kernel-authority signed,
//! one-shot final-use grant. The existing real model driver runs each item.
//! This batches admission and shared storage, not GPU execution kernels.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::str::FromStr;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::SharedFeatureBufferV1;
use codex_hepta_infer_core::microbatch::BoundedMicrobatchSchedulerV1;
use codex_hepta_infer_core::microbatch::InferenceIntentV1;
use codex_hepta_infer_core::microbatch::MicrobatchKeyV1;
use codex_hepta_infer_core::microbatch::MicrobatchLimitsV1;
use codex_hepta_infer_core::microbatch::SchedulerErrorV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::PhaseMetricEventV1;
use codex_hepta_types::PhaseMetricKindV1;
use codex_hepta_types::PhaseMetricSinkV1;
use codex_hepta_types::StableId;

use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelDriver;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::canonical_neuron_feature_payload_digest;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BatchWorkerErrorV1 {
    InvalidRequest,
    InvalidBinding,
    Duplicate,
    NoAdmission,
    Scheduler(SchedulerErrorV1),
    Authority,
    Worker,
    Capacity,
}

#[derive(Debug)]
pub struct BatchWorkerItemOutcomeV1 {
    pub request_id: StableId,
    pub result: Result<NeuronFeatureReceiptV1, BatchWorkerErrorV1>,
}

#[derive(Debug)]
pub struct BatchWorkerPollV1 {
    pub expired: Vec<StableId>,
    pub outcomes: Vec<BatchWorkerItemOutcomeV1>,
    pub scanned_lanes: usize,
    pub pending: usize,
}

struct PendingV1 {
    model_id: String,
    request: NeuronFeatureRequest,
    feature: SharedFeatureBufferV1,
    signed: SignedFinalUseGrant,
    binding: FinalUseBinding,
}

/// One exclusive batch owner; no API exposes its underlying worker mutably.
/// Recovered durable control state must independently resolve all orphaned
/// requests before constructing this in-memory queue again.
pub struct AuthenticatedNeuronMicrobatchWorkerV1<D: ModelDriver + NeuronFeatureDriver> {
    scheduler: BoundedMicrobatchSchedulerV1,
    worker: InferenceWorker<D>,
    authority: FinalUseAuthority,
    pending: BTreeMap<StableId, PendingV1>,
    retired: BTreeSet<StableId>,
    metric_sink: Option<Arc<dyn PhaseMetricSinkV1>>,
    maximum_ids: usize,
}

pub fn neuron_batch_final_use_binding_v1(
    worker_id: &str,
    key: &MicrobatchKeyV1,
    request: &NeuronFeatureRequest,
) -> Result<FinalUseBinding, BatchWorkerErrorV1> {
    let payload_hex = canonical_neuron_feature_payload_digest(request);
    if request.authorization.payload_digest != payload_hex
        || request.authorization.lease_payload_digest != payload_hex
        || Digest32::from_str(&request.authorization.model_digest).ok() != Some(key.model_digest)
    {
        return Err(BatchWorkerErrorV1::InvalidBinding);
    }
    let payload_digest =
        Digest32::from_str(&payload_hex).map_err(|_| BatchWorkerErrorV1::InvalidBinding)?;
    let request_id = request.authorization.request_id.as_bytes();
    let reservation_id = request.authorization.reservation_id.as_bytes();
    let model_id = request.authorization.model_digest.as_bytes();
    let mut request_bytes = b"hepta.worker.batch-request.v1".to_vec();
    for field in [request_id, reservation_id, model_id] {
        request_bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
        request_bytes.extend_from_slice(field);
    }
    request_bytes.extend_from_slice(&request.authorization.deadline_ms.to_be_bytes());
    request_bytes.extend_from_slice(payload_digest.as_array());

    let mut scope_bytes = b"hepta.worker.batch-scope.v1".to_vec();
    for field in [key.scope_id.as_str().as_bytes(), worker_id.as_bytes()] {
        scope_bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
        scope_bytes.extend_from_slice(field);
    }
    scope_bytes.extend_from_slice(key.model_digest.as_array());
    scope_bytes.extend_from_slice(&key.generation.get().to_be_bytes());
    scope_bytes.extend_from_slice(&key.route_fence.to_be_bytes());
    scope_bytes.extend_from_slice(&key.authority_epoch.to_be_bytes());
    Ok(FinalUseBinding {
        subject_id: key.scope_id.to_string(),
        destination_id: worker_id.to_string(),
        request_sha256: *Digest32::of_bytes(&request_bytes).as_array(),
        scope_sha256: *Digest32::of_bytes(&scope_bytes).as_array(),
        payload_sha256: *payload_digest.as_array(),
    })
}

impl<D: ModelDriver + NeuronFeatureDriver> AuthenticatedNeuronMicrobatchWorkerV1<D> {
    pub fn new(
        worker: InferenceWorker<D>,
        authority: FinalUseAuthority,
        limits: MicrobatchLimitsV1,
    ) -> Result<Self, BatchWorkerErrorV1> {
        let scheduler =
            BoundedMicrobatchSchedulerV1::new(limits).map_err(BatchWorkerErrorV1::Scheduler)?;
        Ok(Self {
            scheduler,
            worker,
            authority,
            pending: BTreeMap::new(),
            retired: BTreeSet::new(),
            metric_sink: None,
            maximum_ids: limits.max_pending,
        })
    }

    pub fn with_metric_sink(mut self, sink: Arc<dyn PhaseMetricSinkV1>) -> Self {
        self.metric_sink = Some(sink);
        self
    }

    pub fn pending(&self) -> usize {
        self.pending.len()
    }

    /// Admission copies no feature vector; queued payloads share Arc<[i64]>.
    /// Final-use signature verification and durable nonce claim occur only at
    /// actual worker execution, immediately before the model driver is called.
    pub fn enqueue(
        &mut self,
        now_ms: u64,
        model_id: String,
        mut request: NeuronFeatureRequest,
        key: MicrobatchKeyV1,
        signed: SignedFinalUseGrant,
    ) -> Result<(), BatchWorkerErrorV1> {
        let id = StableId::new(request.authorization.request_id.clone())
            .map_err(|_| BatchWorkerErrorV1::InvalidRequest)?;
        if self.retired.contains(&id) || self.pending.contains_key(&id) {
            return Err(BatchWorkerErrorV1::Duplicate);
        }
        if self.retired.len() + self.pending.len() >= self.maximum_ids {
            return Err(BatchWorkerErrorV1::Capacity);
        }
        if key.generation.get() != self.worker.worker_generation()
            || key.authority_epoch != self.worker.authority_epoch()
            || signed.grant.authority_epoch != key.authority_epoch
            || request.authorization.cancelled
        {
            return Err(BatchWorkerErrorV1::InvalidBinding);
        }
        let binding = neuron_batch_final_use_binding_v1(self.worker.worker_id(), &key, &request)?;
        if signed.grant.binding != binding {
            return Err(BatchWorkerErrorV1::InvalidBinding);
        }
        let feature =
            SharedFeatureBufferV1::from_vec(std::mem::take(&mut request.feature_vector_q24))
                .map_err(|_| BatchWorkerErrorV1::InvalidRequest)?;
        self.scheduler
            .enqueue(
                now_ms,
                InferenceIntentV1 {
                    request_id: id.clone(),
                    key,
                    feature_digest: feature.digest(),
                    shared_features: Some(feature.clone()),
                    deadline_ms: request.authorization.deadline_ms,
                },
            )
            .map_err(BatchWorkerErrorV1::Scheduler)?;
        self.pending.insert(
            id,
            PendingV1 {
                model_id,
                request,
                feature,
                signed,
                binding,
            },
        );
        Ok(())
    }

    /// Never replay an unknown or failed external effect. Every result,
    /// including authority denial, is terminal within this local generation.
    pub fn poll_and_execute(
        &mut self,
        now_ms: u64,
    ) -> Result<BatchWorkerPollV1, BatchWorkerErrorV1> {
        let poll = self
            .scheduler
            .poll(now_ms)
            .map_err(BatchWorkerErrorV1::Scheduler)?;
        for id in &poll.expired_request_ids {
            self.pending.remove(id);
            self.retired.insert(id.clone());
        }
        let mut outcomes = Vec::new();
        if let Some(batch) = poll.batch {
            for intent in batch.requests {
                let id = intent.request_id;
                self.retired.insert(id.clone());
                let outcome = match self.pending.remove(&id) {
                    None => Err(BatchWorkerErrorV1::NoAdmission),
                    Some(mut pending) => {
                        if pending.feature.digest() != intent.feature_digest
                            || pending.signed.grant.authority_epoch != batch.key.authority_epoch
                        {
                            Err(BatchWorkerErrorV1::InvalidBinding)
                        } else {
                            pending.request.feature_vector_q24 =
                                pending.feature.as_slice().to_vec();
                            let start = Instant::now();
                            let result = FinalUseAuthority::claim(
                                &self.authority,
                                &pending.signed,
                                &pending.binding,
                            )
                            .map_err(|_| BatchWorkerErrorV1::Authority)
                            .and_then(|token| {
                                FinalUseAuthority::with_verified_effect(
                                    &self.authority,
                                    token,
                                    &pending.binding,
                                    || {
                                        self.worker.run_neuron_features_receipt(
                                            now_ms,
                                            &pending.model_id,
                                            pending.request,
                                        )
                                    },
                                )
                                .map_err(|_| BatchWorkerErrorV1::Authority)
                                .and_then(|inner| inner.map_err(|_| BatchWorkerErrorV1::Worker))
                            });
                            if let Some(sink) = &self.metric_sink {
                                let _ = sink.record(PhaseMetricEventV1 {
                                    scope_digest: Digest32::of_bytes(
                                        batch.key.scope_id.as_str().as_bytes(),
                                    ),
                                    operation_digest: Digest32::of_bytes(id.as_str().as_bytes()),
                                    phase: PhaseMetricKindV1::NeuronFeature,
                                    latency_micros: u64::try_from(start.elapsed().as_micros())
                                        .unwrap_or(u64::MAX),
                                    succeeded: result.is_ok(),
                                });
                            }
                            result
                        }
                    }
                };
                outcomes.push(BatchWorkerItemOutcomeV1 {
                    request_id: id,
                    result: outcome,
                });
            }
        }
        Ok(BatchWorkerPollV1 {
            expired: poll.expired_request_ids,
            outcomes,
            scanned_lanes: poll.scanned_lanes,
            pending: self.pending.len(),
        })
    }

    /// Cutover drops all stale queued requests without ever invoking a driver.
    pub fn fence_scope(
        &mut self,
        scope: &StableId,
        generation: codex_hepta_types::Generation,
        fence: u64,
        authority_epoch: u64,
    ) -> Vec<StableId> {
        let removed =
            self.scheduler
                .retain_scope_binding(scope, generation, fence, authority_epoch);
        for id in &removed {
            self.pending.remove(id);
            self.retired.insert(id.clone());
        }
        removed
    }
}

#[cfg(test)]
#[path = "batched_neuron_tests.rs"]
mod tests;
