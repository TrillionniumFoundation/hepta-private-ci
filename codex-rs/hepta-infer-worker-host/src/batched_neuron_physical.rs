//! One-call physical batch admission path.
//!
//! A full batch either crosses its final-use fence once with all independently
//! claimed nonces, or none of its members invoke the backend. Failed/unknown
//! effects are terminal in this in-memory owner; no automatic retries occur.

use super::*;
use crate::model_worker::NeuronPhysicalBatchDriver;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;

impl<D: ModelDriver + NeuronFeatureDriver + NeuronPhysicalBatchDriver>
    AuthenticatedNeuronMicrobatchWorkerV1<D>
{
    /// One physical backend batch call instead of sequential single-item runs.
    /// No installed model backend is implied by availability of this API.
    pub fn poll_and_execute_physical(
        &mut self,
        now_ms: u64,
    ) -> Result<BatchWorkerPollV1, BatchWorkerErrorV1> {
        // Physical serving requires a healthy evidence-owned metric sink.
        // Failed persistence cannot justify retrying a completed model call;
        // subsequent admissions are fenced instead.
        if self.metrics_poisoned || self.metric_sink.as_ref().is_none_or(|sink| !sink.healthy()) {
            return Err(BatchWorkerErrorV1::TelemetryUnavailable);
        }
        if self.scope_currentness.is_none() {
            return Err(BatchWorkerErrorV1::ScopeFenceUnavailable);
        }
        let poll = self
            .scheduler
            .poll_physical_compatible(now_ms)
            .map_err(BatchWorkerErrorV1::Scheduler)?;
        for id in &poll.expired_request_ids {
            self.pending.remove(id);
            self.retired.insert(id.clone());
        }
        let Some(batch) = poll.batch else {
            return Ok(BatchWorkerPollV1 {
                expired: poll.expired_request_ids,
                outcomes: Vec::new(),
                scanned_lanes: poll.scanned_lanes,
                pending: self.pending.len(),
            });
        };
        // Preserve all exact per-Cell bindings even when inference computation
        // is coalesced across scopes. These must be fenced at effect entry.
        let scope_bindings: Vec<MicrobatchKeyV1> = batch
            .requests
            .iter()
            .map(|intent| intent.key.clone())
            .collect();
        let mut ids = Vec::with_capacity(batch.requests.len());
        let mut items = Vec::with_capacity(batch.requests.len());
        let mut scope_bytes = b"hepta.worker.physical-batch-scopes.v1".to_vec();
        scope_bytes.extend_from_slice(&(batch.requests.len() as u64).to_be_bytes());
        let mut failure = None;
        for intent in batch.requests {
            let scope = intent.key.scope_id.as_str().as_bytes();
            scope_bytes.extend_from_slice(&(scope.len() as u64).to_be_bytes());
            scope_bytes.extend_from_slice(scope);
            let expected_encoder = batch.compatibility.encoder_digest.to_string();
            let incompatible = intent.key.model_digest != batch.compatibility.model_digest
                || intent.key.generation != batch.compatibility.generation
                || intent.key.authority_epoch != batch.compatibility.authority_epoch
                || intent.encoder_digest != Some(batch.compatibility.encoder_digest);
            let id = intent.request_id;
            self.retired.insert(id.clone());
            ids.push(id.clone());
            match self.pending.remove(&id) {
                None => failure = Some(BatchWorkerErrorV1::NoAdmission),
                Some(pending) => {
                    if incompatible
                        || pending.feature.digest() != intent.feature_digest
                        || pending.signed.grant.authority_epoch != intent.key.authority_epoch
                        || pending.request.encoder_digest != expected_encoder
                        || pending.binding.subject_id != intent.key.scope_id.to_string()
                        || pending.request.authorization.cancelled
                    {
                        failure = Some(BatchWorkerErrorV1::InvalidBinding);
                    }
                    items.push(pending);
                }
            }
        }
        if let Some(error) = failure {
            return Ok(failed_poll(
                ids,
                error,
                poll.expired_request_ids,
                poll.scanned_lanes,
                self.pending.len(),
            ));
        }
        let Some(first) = items.first() else {
            return Ok(failed_poll(
                ids,
                BatchWorkerErrorV1::NoAdmission,
                poll.expired_request_ids,
                poll.scanned_lanes,
                self.pending.len(),
            ));
        };
        let model_id = first.model_id.clone();
        if items.iter().any(|item| item.model_id != model_id) {
            return Ok(failed_poll(
                ids,
                BatchWorkerErrorV1::InvalidBinding,
                poll.expired_request_ids,
                poll.scanned_lanes,
                self.pending.len(),
            ));
        }

        // Claims consume durable nonces independently. If one fails, earlier
        // claims remain spent but NO physical batch is submitted.
        let mut claims = Vec::with_capacity(items.len());
        for pending in &items {
            match FinalUseAuthority::claim(&self.authority, &pending.signed, &pending.binding) {
                Ok(token) => claims.push((token, pending.binding.clone())),
                Err(_) => {
                    return Ok(failed_poll(
                        ids,
                        BatchWorkerErrorV1::Authority,
                        poll.expired_request_ids,
                        poll.scanned_lanes,
                        self.pending.len(),
                    ));
                }
            }
        }
        let requests = items
            .into_iter()
            .map(|mut pending| {
                pending.request.feature_vector_q24 = pending.feature.as_slice().to_vec();
                pending.request
            })
            .collect();
        let start = Instant::now();
        let currentness = self
            .scope_currentness
            .as_ref()
            .ok_or(BatchWorkerErrorV1::ScopeFenceUnavailable)?;
        let execution =
            FinalUseAuthority::with_verified_batch_effect(&self.authority, claims, || {
                // All route heads must still be current after durable nonce
                // claims. The CNS read guard lives across the actual forward,
                // preventing route cutover while any input is in flight.
                let guard = currentness
                    .enter_current(&scope_bindings)
                    .map_err(|_| BatchWorkerErrorV1::ScopeFenceDenied)?;
                let result = self
                    .worker
                    .run_physical_batch_receipts(now_ms, &model_id, requests)
                    .map_err(|_| BatchWorkerErrorV1::Worker);
                drop(guard);
                result
            });
        let completed = match execution {
            Ok(Ok(receipts)) if receipts.len() == ids.len() => ids
                .into_iter()
                .zip(receipts.into_iter().map(Ok))
                .map(|(request_id, result)| BatchWorkerItemOutcomeV1 { request_id, result })
                .collect::<Vec<_>>(),
            Ok(Err(error)) => failed_outcomes(ids, error),
            Err(_) => failed_outcomes(ids, BatchWorkerErrorV1::Authority),
        };
        if let Some(sink) = &self.metric_sink {
            let mut group_digest = b"hepta.worker.physical-batch.v1".to_vec();
            for item in &completed {
                group_digest.extend_from_slice(item.request_id.as_str().as_bytes());
                group_digest.push(0);
            }
            if sink.record(PhaseMetricEventV1 {
                scope_digest: Digest32::of_bytes(&scope_bytes),
                operation_digest: Digest32::of_bytes(&group_digest),
                phase: PhaseMetricKindV1::NeuronFeature,
                latency_micros: u64::try_from(start.elapsed().as_micros()).unwrap_or(u64::MAX),
                succeeded: completed.iter().all(|item| {
                    matches!(
                        &item.result,
                        Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
                    )
                }),
            }).is_err() {
                self.metrics_poisoned = true;
            }
        }
        Ok(BatchWorkerPollV1 {
            expired: poll.expired_request_ids,
            outcomes: completed,
            scanned_lanes: poll.scanned_lanes,
            pending: self.pending.len(),
        })
    }
}

fn failed_outcomes(ids: Vec<StableId>, error: BatchWorkerErrorV1) -> Vec<BatchWorkerItemOutcomeV1> {
    ids.into_iter()
        .map(|request_id| BatchWorkerItemOutcomeV1 {
            request_id,
            result: Err(error),
        })
        .collect()
}

fn failed_poll(
    ids: Vec<StableId>,
    error: BatchWorkerErrorV1,
    expired: Vec<StableId>,
    scanned_lanes: usize,
    pending: usize,
) -> BatchWorkerPollV1 {
    BatchWorkerPollV1 {
        expired,
        outcomes: failed_outcomes(ids, error),
        scanned_lanes,
        pending,
    }
}
