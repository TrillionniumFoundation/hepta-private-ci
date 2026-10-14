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
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_infer_core::SharedFeatureBufferV1;
use codex_hepta_infer_core::microbatch::BoundedMicrobatchSchedulerV1;
use codex_hepta_infer_core::microbatch::InferenceIntentV1;
use codex_hepta_infer_core::microbatch::MicrobatchKeyV1;
use codex_hepta_infer_core::microbatch::MicrobatchLimitsV1;
use codex_hepta_infer_core::microbatch::MicrobatchPlanV1;
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

const MAX_TERMINAL_REQUEST_IDS: usize = 1_048_576;

/// Fixed-size local replay fingerprint: never evict IDs while an owner lives.
/// A new owner generation must reconcile durable control state before serving;
/// the independent Final-use nonce ledger remains the cross-restart fence.
fn terminal_request_fingerprint(id: &StableId) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.infer-worker.terminal-request-id.v1\0",
        id.as_str().as_bytes(),
    ])
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
    /// A live Control scope fence advanced during an already-started model
    /// effect. Its result must be reconciled, never published or blindly retried.
    StaleAfterEffect,
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

/// Control-owned live route/generation/epoch reader, never a caller hint.
pub trait MicrobatchScopeFrontierV1: std::fmt::Debug + Send + Sync {
    fn current(&self, scope: &StableId) -> Result<MicrobatchKeyV1, BatchWorkerErrorV1>;
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
    scope_frontier: Arc<dyn MicrobatchScopeFrontierV1>,
    pending: BTreeMap<StableId, PendingV1>,
    retired: BTreeSet<Digest32>,
    metric_sink: Option<Arc<dyn PhaseMetricSinkV1>>,
    failed_metrics: AtomicU64,
    maximum_pending: usize,
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

fn with_all_final_use_effects<T, F: FnOnce() -> T>(
    authority: &FinalUseAuthority,
    mut claims: std::vec::IntoIter<(VerifiedUseToken, FinalUseBinding)>,
    effect: &mut Option<F>,
) -> Result<T, FinalUseError> {
    if let Some((claim, binding)) = claims.next() {
        // Nested entry holds every independent signed nonce's revocation
        // fence until the single synchronous physical backend call finishes.
        authority.with_verified_effect(claim, &binding, || {
            with_all_final_use_effects(authority, claims, effect)
        })?
    } else {
        effect
            .take()
            .map(|invoke| invoke())
            .ok_or(FinalUseError::Unavailable)
    }
}

impl<D: ModelDriver + NeuronFeatureDriver> AuthenticatedNeuronMicrobatchWorkerV1<D> {
    pub fn new(
        worker: InferenceWorker<D>,
        authority: FinalUseAuthority,
        scope_frontier: Arc<dyn MicrobatchScopeFrontierV1>,
        limits: MicrobatchLimitsV1,
    ) -> Result<Self, BatchWorkerErrorV1> {
        let scheduler =
            BoundedMicrobatchSchedulerV1::new(limits).map_err(BatchWorkerErrorV1::Scheduler)?;
        Ok(Self {
            scheduler,
            worker,
            authority,
            scope_frontier,
            pending: BTreeMap::new(),
            retired: BTreeSet::new(),
            metric_sink: None,
            failed_metrics: AtomicU64::new(0),
            maximum_pending: limits.max_pending,
        })
    }

    pub fn with_metric_sink(mut self, sink: Arc<dyn PhaseMetricSinkV1>) -> Self {
        self.metric_sink = Some(sink);
        self
    }

    /// Source-side telemetry readiness is a separate acceptance barrier.
    /// An absent, failed, or unflushed Evidence sink never makes this owner ready.
    /// Telemetry failure does not retroactively undo or retry an external effect.
    pub fn production_metrics_ready(&self) -> bool {
        self.metric_sink.as_ref().is_some_and(|sink| sink.healthy())
            && self.failed_metrics.load(Ordering::Acquire) == 0
    }

    /// Call outside a model effect boundary, after all admitted work settles.
    pub fn flush_production_metrics(&self) -> bool {
        let Some(sink) = &self.metric_sink else {
            return false;
        };
        if sink.flush().is_err() {
            self.failed_metrics.fetch_add(1, Ordering::Release);
            return false;
        }
        self.production_metrics_ready()
    }

    pub fn pending(&self) -> usize {
        self.pending.len()
    }

    /// Telemetry is non-authorizing. Its sink exposes a separate health and
    /// durable flush barrier to the production acceptance owner.
    fn emit_metric(
        &self,
        scope: &StableId,
        request_id: &StableId,
        phase: PhaseMetricKindV1,
        elapsed: Duration,
        succeeded: bool,
    ) {
        if let Some(sink) = &self.metric_sink {
            if sink
                .record(PhaseMetricEventV1 {
                    scope_digest: Digest32::of_bytes(scope.as_str().as_bytes()),
                    operation_digest: Digest32::of_bytes(request_id.as_str().as_bytes()),
                    phase,
                    latency_micros: u64::try_from(elapsed.as_micros()).unwrap_or(u64::MAX),
                    succeeded,
                })
                .is_err()
            {
                self.failed_metrics.fetch_add(1, Ordering::Release);
            }
        }
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
        let id = StableId::new(request.authorization.request_id.clone())
            .map_err(|_| BatchWorkerErrorV1::InvalidRequest)?;
        let scope = key.scope_id.clone();
        let started = Instant::now();
        let result = self.enqueue_inner(now_ms, model_id, request, key, signed, id.clone());
        self.emit_metric(
            &scope,
            &id,
            PhaseMetricKindV1::Admission,
            started.elapsed(),
            result.is_ok(),
        );
        result
    }

    fn enqueue_inner(
        &mut self,
        now_ms: u64,
        model_id: String,
        mut request: NeuronFeatureRequest,
        key: MicrobatchKeyV1,
        signed: SignedFinalUseGrant,
        id: StableId,
    ) -> Result<(), BatchWorkerErrorV1> {
        if self.retired.contains(&terminal_request_fingerprint(&id))
            || self.pending.contains_key(&id)
        {
            return Err(BatchWorkerErrorV1::Duplicate);
        }
        if self.pending.len() >= self.maximum_pending
            || self.retired.len() + self.pending.len() >= MAX_TERMINAL_REQUEST_IDS
        {
            return Err(BatchWorkerErrorV1::Capacity);
        }
        if key.generation.get() != self.worker.worker_generation()
            || key.authority_epoch != self.worker.authority_epoch()
            || signed.grant.authority_epoch != key.authority_epoch
            || request.authorization.cancelled
        {
            return Err(BatchWorkerErrorV1::InvalidBinding);
        }
        let current = self
            .scope_frontier
            .current(&key.scope_id)
            .map_err(|_| BatchWorkerErrorV1::InvalidBinding)?;
        if current != key {
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
        let scheduled_at = Instant::now();
        let poll = self
            .scheduler
            .poll(now_ms)
            .map_err(BatchWorkerErrorV1::Scheduler)?;
        if let Some(batch) = &poll.batch {
            // One scheduling sample per dequeued request. Emitting only the
            // first member undercounts throughput and hides per-Scope queue
            // latency once native batches become physically coalesced.
            // This does not represent physical backend execution latency.
            for intent in &batch.requests {
                self.emit_metric(
                    &intent.key.scope_id,
                    &intent.request_id,
                    PhaseMetricKindV1::Microbatch,
                    scheduled_at.elapsed(),
                    true,
                );
            }
        }
        for id in &poll.expired_request_ids {
            self.pending.remove(id);
            self.retired.insert(terminal_request_fingerprint(id));
        }
        let outcomes = match poll.batch {
            None => Vec::new(),
            Some(batch)
                if self
                    .scope_frontier
                    .current(&batch.key.scope_id)
                    .ok()
                    .as_ref()
                    != Some(&batch.key) =>
            {
                self.deny_stale_batch(batch)
            }
            Some(batch)
                if batch.requests.len() > 1 && self.worker.supports_physical_neuron_batch() =>
            {
                self.execute_native_batch(now_ms, batch)
            }
            Some(batch) => self.execute_scalar_batch(now_ms, batch),
        };
        Ok(BatchWorkerPollV1 {
            expired: poll.expired_request_ids,
            outcomes,
            scanned_lanes: poll.scanned_lanes,
            pending: self.pending.len(),
        })
    }

    fn deny_stale_batch(&mut self, batch: MicrobatchPlanV1) -> Vec<BatchWorkerItemOutcomeV1> {
        let started = Instant::now();
        batch
            .requests
            .into_iter()
            .map(|intent| {
                let id = intent.request_id;
                self.pending.remove(&id);
                self.retired.insert(terminal_request_fingerprint(&id));
                self.emit_metric(
                    &batch.key.scope_id,
                    &id,
                    PhaseMetricKindV1::NeuronFeature,
                    started.elapsed(),
                    false,
                );
                BatchWorkerItemOutcomeV1 {
                    request_id: id,
                    result: Err(BatchWorkerErrorV1::InvalidBinding),
                }
            })
            .collect()
    }

    fn execute_scalar_batch(
        &mut self,
        now_ms: u64,
        batch: MicrobatchPlanV1,
    ) -> Vec<BatchWorkerItemOutcomeV1> {
        let mut outcomes = Vec::with_capacity(batch.requests.len());
        for intent in batch.requests {
            let id = intent.request_id;
            let started = Instant::now();
            self.retired.insert(terminal_request_fingerprint(&id));
            let outcome = match self.pending.remove(&id) {
                None => Err(BatchWorkerErrorV1::NoAdmission),
                Some(mut pending) => {
                    if pending.feature.digest() != intent.feature_digest
                        || pending.signed.grant.authority_epoch != batch.key.authority_epoch
                    {
                        Err(BatchWorkerErrorV1::InvalidBinding)
                    } else {
                        pending.request.feature_vector_q24 = pending.feature.as_slice().to_vec();
                        FinalUseAuthority::claim(&self.authority, &pending.signed, &pending.binding)
                            .map_err(|_| BatchWorkerErrorV1::Authority)
                            .and_then(|token| {
                                FinalUseAuthority::with_verified_effect(
                                    &self.authority,
                                    token,
                                    &pending.binding,
                                    || {
                                        if self
                                            .scope_frontier
                                            .current(&batch.key.scope_id)
                                            .ok()
                                            .as_ref()
                                            != Some(&batch.key)
                                        {
                                            return Err(BatchWorkerErrorV1::InvalidBinding);
                                        }
                                        let receipt = self
                                            .worker
                                            .run_neuron_features_receipt(
                                                now_ms,
                                                &pending.model_id,
                                                pending.request,
                                            )
                                            .map_err(|_| BatchWorkerErrorV1::Worker);
                                        // A cutover may occur inside the synchronous backend.
                                        // Consumed final-use nonces are never retried, and
                                        // stale results must not become a successful receipt.
                                        if self
                                            .scope_frontier
                                            .current(&batch.key.scope_id)
                                            .ok()
                                            .as_ref()
                                            != Some(&batch.key)
                                        {
                                            return Err(BatchWorkerErrorV1::StaleAfterEffect);
                                        }
                                        receipt
                                    },
                                )
                                .map_err(|_| BatchWorkerErrorV1::Authority)
                                .flatten()
                            })
                    }
                }
            };
            let succeeded = matches!(
                &outcome,
                Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
            );
            self.emit_metric(
                &batch.key.scope_id,
                &id,
                PhaseMetricKindV1::NeuronFeature,
                started.elapsed(),
                succeeded,
            );
            outcomes.push(BatchWorkerItemOutcomeV1 {
                request_id: id,
                result: outcome,
            });
        }
        outcomes
    }

    /// Only called when the loaded driver explicitly advertises physical
    /// batching. Authentication remains per request, not per batch; rejected
    /// grants never enter the device. Each claimed nonce is terminal even if
    /// the physical call fails with an unknown outcome.
    fn execute_native_batch(
        &mut self,
        now_ms: u64,
        batch: MicrobatchPlanV1,
    ) -> Vec<BatchWorkerItemOutcomeV1> {
        let started = Instant::now();
        let mut slots = Vec::with_capacity(batch.requests.len());
        let mut admitted = Vec::with_capacity(batch.requests.len());
        for intent in batch.requests {
            let id = intent.request_id;
            self.retired.insert(terminal_request_fingerprint(&id));
            let result = (|| {
                let mut pending = self
                    .pending
                    .remove(&id)
                    .ok_or(BatchWorkerErrorV1::NoAdmission)?;
                if pending.feature.digest() != intent.feature_digest
                    || pending.signed.grant.authority_epoch != batch.key.authority_epoch
                {
                    return Err(BatchWorkerErrorV1::InvalidBinding);
                }
                pending.request.feature_vector_q24 = pending.feature.as_slice().to_vec();
                let token =
                    FinalUseAuthority::claim(&self.authority, &pending.signed, &pending.binding)
                        .map_err(|_| BatchWorkerErrorV1::Authority)?;
                Ok((pending, token))
            })();
            match result {
                Ok(value) => {
                    slots.push((id, None));
                    admitted.push(value);
                }
                Err(error) => slots.push((id, Some(error))),
            }
        }

        let admitted_count = admitted.len();
        let valid_results: Vec<Result<NeuronFeatureReceiptV1, BatchWorkerErrorV1>> =
            if admitted_count >= 2
                && admitted
                    .iter()
                    .all(|(pending, _)| pending.model_id == admitted[0].0.model_id)
            {
                let model_id = admitted[0].0.model_id.clone();
                let mut claims = Vec::with_capacity(admitted_count);
                let mut requests = Vec::with_capacity(admitted_count);
                for (pending, token) in admitted {
                    claims.push((token, pending.binding));
                    requests.push(pending.request);
                }
                let mut physical = Some(|| {
                    if self
                        .scope_frontier
                        .current(&batch.key.scope_id)
                        .ok()
                        .as_ref()
                        != Some(&batch.key)
                    {
                        return Err(BatchWorkerErrorV1::InvalidBinding);
                    }
                    let receipts = self
                        .worker
                        .run_neuron_features_batch_receipts(now_ms, &model_id, requests)
                        .map_err(|_| BatchWorkerErrorV1::Worker);
                    // One backend call may race CNS cutover. Neither a valid
                    // signature nor a completed GPU batch authorizes old-route
                    // results after the scope frontier has advanced.
                    if self
                        .scope_frontier
                        .current(&batch.key.scope_id)
                        .ok()
                        .as_ref()
                        != Some(&batch.key)
                    {
                        return Err(BatchWorkerErrorV1::StaleAfterEffect);
                    }
                    receipts
                });
                match with_all_final_use_effects(&self.authority, claims.into_iter(), &mut physical)
                {
                    Ok(Ok(receipts)) if receipts.len() == admitted_count => receipts
                        .into_iter()
                        .map(|result| result.map_err(|_| BatchWorkerErrorV1::Worker))
                        .collect(),
                    Ok(Err(error)) => vec![Err(error); admitted_count],
                    Ok(Ok(_)) => vec![Err(BatchWorkerErrorV1::Worker); admitted_count],
                    Err(_) => vec![Err(BatchWorkerErrorV1::Authority); admitted_count],
                }
            } else {
                // Any single accepted request or mixed model-id grouping falls
                // back to independently checked scalar execution, never a
                // falsely labelled physical batch.
                admitted
                    .into_iter()
                    .map(|(pending, token)| {
                        FinalUseAuthority::with_verified_effect(
                            &self.authority,
                            token,
                            &pending.binding,
                            || {
                                if self
                                    .scope_frontier
                                    .current(&batch.key.scope_id)
                                    .ok()
                                    .as_ref()
                                    != Some(&batch.key)
                                {
                                    return Err(BatchWorkerErrorV1::InvalidBinding);
                                }
                                let receipt = self
                                    .worker
                                    .run_neuron_features_receipt(
                                        now_ms,
                                        &pending.model_id,
                                        pending.request,
                                    )
                                    .map_err(|_| BatchWorkerErrorV1::Worker);
                                if self
                                    .scope_frontier
                                    .current(&batch.key.scope_id)
                                    .ok()
                                    .as_ref()
                                    != Some(&batch.key)
                                {
                                    return Err(BatchWorkerErrorV1::StaleAfterEffect);
                                }
                                receipt
                            },
                        )
                        .map_err(|_| BatchWorkerErrorV1::Authority)
                        .flatten()
                    })
                    .collect()
            };

        let mut ready = valid_results.into_iter();
        slots
            .into_iter()
            .map(|(id, denial)| {
                let result = denial.map_or_else(
                    || ready.next().unwrap_or(Err(BatchWorkerErrorV1::Worker)),
                    Err,
                );
                self.emit_metric(
                    &batch.key.scope_id,
                    &id,
                    PhaseMetricKindV1::NeuronFeature,
                    started.elapsed(),
                    matches!(
                        &result,
                        Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
                    ),
                );
                BatchWorkerItemOutcomeV1 {
                    request_id: id,
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
            self.retired.insert(terminal_request_fingerprint(id));
        }
        removed
    }
}

// Unix final-use credentials require a protected uid-owned state directory.
// Unsupported platforms get their own fail-closed test rather than a forged
// positive serving witness.
#[cfg(all(test, unix))]
#[path = "batched_neuron_tests.rs"]
mod tests;

#[cfg(all(test, not(unix)))]
#[path = "batched_neuron_non_unix_tests.rs"]
mod tests_non_unix;
