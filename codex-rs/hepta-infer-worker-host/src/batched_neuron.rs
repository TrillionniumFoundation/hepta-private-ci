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
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;

// This is a generation-lifetime deduplication bound, not the concurrent
// scheduler max_pending. Exhaustion requires an externally fenced rollover.
const MAX_WORKER_RETIRED_IDS: usize = 1_048_576;

fn retired_identity(id: &StableId) -> Digest32 {
    Digest32::of_parts(&[b"hepta.worker.retired-request.v1", id.as_str().as_bytes()])
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BatchWorkerErrorV1 {
    InvalidRequest,
    InvalidBinding,
    Duplicate,
    NoAdmission,
    Scheduler(SchedulerErrorV1),
    Authority,
    Worker,
    BatchUnsupported,
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
    retired: BTreeSet<Digest32>,
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
    // Exact-request final use must also cover quota, reservation model, and
    // cancellation state. A signed feature payload alone does not authorize
    // changes to the surrounding worker/reservation claims.
    let authorization = &request.authorization;
    let mut request_bytes = b"hepta.worker.batch-request.v1".to_vec();
    for field in [
        authorization.request_id.as_bytes(),
        authorization.reservation_id.as_bytes(),
        authorization.model_digest.as_bytes(),
        authorization.reservation_model_digest.as_bytes(),
    ] {
        request_bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
        request_bytes.extend_from_slice(field);
    }
    request_bytes.extend_from_slice(&authorization.deadline_ms.to_be_bytes());
    request_bytes.extend_from_slice(&authorization.maximum_tokens.to_be_bytes());
    request_bytes.extend_from_slice(&authorization.reservation_maximum_tokens.to_be_bytes());
    request_bytes.push(u8::from(authorization.cancelled));
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
            maximum_ids: MAX_WORKER_RETIRED_IDS,
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
        request: NeuronFeatureRequest,
        key: MicrobatchKeyV1,
        signed: SignedFinalUseGrant,
    ) -> Result<(), BatchWorkerErrorV1> {
        let started = Instant::now();
        let scope_digest = Digest32::of_bytes(key.scope_id.as_str().as_bytes());
        let operation_digest = Digest32::of_bytes(request.authorization.request_id.as_bytes());
        let result = self.enqueue_inner(now_ms, model_id, request, key, signed);
        if let Some(sink) = &self.metric_sink {
            let _ = sink.record(PhaseMetricEventV1 {
                scope_digest,
                operation_digest,
                phase: PhaseMetricKindV1::Admission,
                latency_micros: u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX),
                succeeded: result.is_ok(),
            });
        }
        result
    }

    fn enqueue_inner(
        &mut self,
        now_ms: u64,
        model_id: String,
        mut request: NeuronFeatureRequest,
        key: MicrobatchKeyV1,
        signed: SignedFinalUseGrant,
    ) -> Result<(), BatchWorkerErrorV1> {
        let id = StableId::new(request.authorization.request_id.clone())
            .map_err(|_| BatchWorkerErrorV1::InvalidRequest)?;
        if self.retired.contains(&retired_identity(&id)) || self.pending.contains_key(&id) {
            return Err(BatchWorkerErrorV1::Duplicate);
        }
        if self.retired.len() + self.pending.len() >= self.maximum_ids {
            return Err(BatchWorkerErrorV1::Capacity);
        }
        if key.generation.get() != self.worker.worker_generation()
            || key.authority_epoch != self.worker.authority_epoch()
            || signed.grant.authority_epoch != key.authority_epoch
            || !self
                .worker
                .model_matches_digest(&model_id, key.model_digest)
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
        let started = Instant::now();
        let poll = self
            .scheduler
            .poll_physically_compatible(now_ms)
            .map_err(BatchWorkerErrorV1::Scheduler)?;
        if let (Some(sink), Some(batch)) = (&self.metric_sink, &poll.batch) {
            // One phase sample per admitted request, not just the first
            // member of a batch (which would silently undercount throughput).
            for intent in &batch.requests {
                let _ = sink.record(PhaseMetricEventV1 {
                    scope_digest: Digest32::of_bytes(intent.key.scope_id.as_str().as_bytes()),
                    operation_digest: Digest32::of_bytes(intent.request_id.as_str().as_bytes()),
                    phase: PhaseMetricKindV1::Microbatch,
                    latency_micros: u64::try_from(started.elapsed().as_micros())
                        .unwrap_or(u64::MAX),
                    succeeded: true,
                });
            }
        }
        for id in &poll.expired_request_ids {
            self.pending.remove(id);
            self.retired.insert(retired_identity(&id));
        }
        let mut outcomes = Vec::new();
        if let Some(batch) = poll.batch {
            if batch.requests.len() > 1 {
                outcomes.extend(self.execute_native_batch(now_ms, &batch.key, batch.requests));
            } else {
                for intent in batch.requests {
                    let id = intent.request_id;
                    self.retired.insert(retired_identity(&id));
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
                                        operation_digest: Digest32::of_bytes(
                                            id.as_str().as_bytes(),
                                        ),
                                        phase: PhaseMetricKindV1::NeuronFeature,
                                        latency_micros: u64::try_from(start.elapsed().as_micros())
                                            .unwrap_or(u64::MAX),
                                        succeeded: matches!(
                                            &result,
                                            Ok(receipt) if receipt.status
                                                == NeuronFeatureTerminalStatusV1::Succeeded
                                        ),
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
        }
        Ok(BatchWorkerPollV1 {
            expired: poll.expired_request_ids,
            outcomes,
            scanned_lanes: poll.scanned_lanes,
            pending: self.pending.len(),
        })
    }

    /// One physical model-driver call for the entire homogeneous batch. If
    /// any member cannot be authenticated/fenced, none crosses the model
    /// boundary. All dequeued identities are terminal, even after unknown
    /// backend outcomes: replay requires external reconciliation.
    fn execute_native_batch(
        &mut self,
        now_ms: u64,
        key: &MicrobatchKeyV1,
        intents: Vec<InferenceIntentV1>,
    ) -> Vec<BatchWorkerItemOutcomeV1> {
        let started = Instant::now();
        let mut items = Vec::with_capacity(intents.len());
        for intent in intents {
            self.retired.insert(retired_identity(&intent.request_id));
            let pending = self.pending.remove(&intent.request_id);
            items.push((intent, pending));
        }

        let executed = (|| -> Result<Vec<NeuronFeatureReceiptV1>, BatchWorkerErrorV1> {
            let mut model_id: Option<&str> = None;
            let mut requests = Vec::with_capacity(items.len());
            for (intent, pending) in &items {
                let pending = pending.as_ref().ok_or(BatchWorkerErrorV1::NoAdmission)?;
                if pending.feature.digest() != intent.feature_digest
                    || !intent.key.physical_compatible_with(key)
                    || pending.signed.grant.authority_epoch != intent.key.authority_epoch
                    || pending.request.authorization.request_id != intent.request_id.as_str()
                {
                    return Err(BatchWorkerErrorV1::InvalidBinding);
                }
                if let Some(previous) = model_id {
                    if previous != pending.model_id {
                        return Err(BatchWorkerErrorV1::InvalidBinding);
                    }
                } else {
                    model_id = Some(&pending.model_id);
                }
                let mut request = pending.request.clone();
                request.feature_vector_q24 = pending.feature.as_slice().to_vec();
                if neuron_batch_final_use_binding_v1(
                    self.worker.worker_id(),
                    &intent.key,
                    &request,
                )? != pending.binding
                {
                    return Err(BatchWorkerErrorV1::InvalidBinding);
                }
                requests.push(request);
            }
            let model_id = model_id.ok_or(BatchWorkerErrorV1::NoAdmission)?.to_owned();
            // Prevalidate all members before one durable nonce-group claim.
            // A denied member never causes a partially dispatched model batch.
            let entries = items
                .iter()
                .map(|(_, pending)| {
                    let pending = pending.as_ref().ok_or(BatchWorkerErrorV1::NoAdmission)?;
                    Ok((&pending.signed, &pending.binding))
                })
                .collect::<Result<Vec<_>, BatchWorkerErrorV1>>()?;
            let tokens = self
                .authority
                .claim_batch(&entries)
                .map_err(|_| BatchWorkerErrorV1::Authority)?;
            let claimed = tokens
                .into_iter()
                .zip(items.iter())
                .map(|(token, (_, pending))| {
                    let pending = pending.as_ref().ok_or(BatchWorkerErrorV1::NoAdmission)?;
                    Ok((token, pending.binding.clone()))
                })
                .collect::<Result<Vec<_>, BatchWorkerErrorV1>>()?;
            FinalUseAuthority::with_verified_effect_batch(&self.authority, claimed, || {
                self.worker
                    .run_neuron_features_batch_receipts(now_ms, &model_id, requests)
            })
            .map_err(|_| BatchWorkerErrorV1::Authority)?
            .map_err(|error| match error {
                crate::model_worker::Error::BatchUnsupported => {
                    BatchWorkerErrorV1::BatchUnsupported
                }
                _ => BatchWorkerErrorV1::Worker,
            })
        })();

        let mut results = match executed {
            Ok(receipts) if receipts.len() == items.len() => {
                receipts.into_iter().map(Ok).collect::<Vec<_>>()
            }
            Ok(_) => vec![Err(BatchWorkerErrorV1::Worker); items.len()],
            Err(error) => vec![Err(error); items.len()],
        };
        items
            .into_iter()
            .zip(results.drain(..))
            .map(|((intent, _), result)| {
                if let Some(sink) = &self.metric_sink {
                    let _ = sink.record(PhaseMetricEventV1 {
                        scope_digest: Digest32::of_bytes(intent.key.scope_id.as_str().as_bytes()),
                        operation_digest: Digest32::of_bytes(intent.request_id.as_str().as_bytes()),
                        phase: PhaseMetricKindV1::NeuronFeature,
                        latency_micros: u64::try_from(started.elapsed().as_micros())
                            .unwrap_or(u64::MAX),
                        succeeded: matches!(
                            &result,
                            Ok(receipt) if receipt.status
                                == NeuronFeatureTerminalStatusV1::Succeeded
                        ),
                    });
                }
                BatchWorkerItemOutcomeV1 {
                    request_id: intent.request_id,
                    result,
                }
            })
            .collect()
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
            self.retired.insert(retired_identity(&id));
        }
        removed
    }
}

#[cfg(test)]
#[path = "batched_neuron_tests.rs"]
mod tests;
