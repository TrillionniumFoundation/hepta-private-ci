//! Physical one-call batch dispatch guarded by every independently signed
//! Final-use grant. No driver entry happens if any signature or live grant
//! fails: consumed nonces still fence ambiguous retries.

use super::*;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_infer_core::microbatch::MicrobatchPlanV1;

fn run_verified_batch<D: ModelDriver + NeuronFeatureDriver>(
    authority: &FinalUseAuthority,
    worker: &mut InferenceWorker<D>,
    grants: &mut std::vec::IntoIter<(VerifiedUseToken, FinalUseBinding)>,
    now_ms: u64,
    model_id: &str,
    requests: Vec<NeuronFeatureRequest>,
) -> Result<Vec<NeuronFeatureReceiptV1>, BatchWorkerErrorV1> {
    if let Some((token, binding)) = grants.next() {
        FinalUseAuthority::with_verified_effect(authority, token, &binding, || {
            run_verified_batch(authority, worker, grants, now_ms, model_id, requests)
        })
        .map_err(|_| BatchWorkerErrorV1::Authority)?
    } else {
        worker
            .run_neuron_features_receipts_batch(now_ms, model_id, requests)
            .map_err(|_| BatchWorkerErrorV1::Worker)
    }
}

impl<D: ModelDriver + NeuronFeatureDriver> AuthenticatedNeuronMicrobatchWorkerV1<D> {
    fn execute_physical_batch(
        &mut self,
        now_ms: u64,
        batch: MicrobatchPlanV1,
    ) -> Vec<BatchWorkerItemOutcomeV1> {
        let started = Instant::now();
        let mut admitted = Vec::with_capacity(batch.requests.len());
        let mut outcomes = Vec::new();
        let mut rejected = false;
        for intent in batch.requests {
            let id = intent.request_id;
            self.retired.insert(terminal_request_fingerprint(&id));
            let Some(mut pending) = self.pending.remove(&id) else {
                rejected = true;
                outcomes.push(BatchWorkerItemOutcomeV1 {
                    request_id: id,
                    result: Err(BatchWorkerErrorV1::NoAdmission),
                });
                continue;
            };
            if pending.feature.digest() != intent.feature_digest
                || pending.signed.grant.authority_epoch != batch.key.authority_epoch
                || pending.signed.grant.binding != pending.binding
            {
                rejected = true;
                outcomes.push(BatchWorkerItemOutcomeV1 {
                    request_id: id,
                    result: Err(BatchWorkerErrorV1::InvalidBinding),
                });
                continue;
            }
            pending.request.feature_vector_q24 = pending.feature.as_slice().to_vec();
            admitted.push((id, pending));
        }
        if admitted.first().is_some_and(|(_, first)| {
            admitted
                .iter()
                .any(|(_, item)| item.model_id != first.model_id)
        }) {
            rejected = true;
        }
        if rejected {
            for (id, _) in admitted {
                outcomes.push(BatchWorkerItemOutcomeV1 {
                    request_id: id,
                    result: Err(BatchWorkerErrorV1::InvalidBinding),
                });
            }
        } else if let Some((_, first)) = admitted.first() {
            let model_id = first.model_id.clone();
            let mut grants = Vec::with_capacity(admitted.len());
            let claims_valid = admitted.iter().all(|(_, pending)| {
                match FinalUseAuthority::claim(
                    &self.authority,
                    &pending.signed,
                    &pending.binding,
                ) {
                    Ok(token) => {
                        grants.push((token, pending.binding.clone()));
                        true
                    }
                    Err(_) => false,
                }
            });
            let ids: Vec<_> = admitted.iter().map(|(id, _)| id.clone()).collect();
            let result = if claims_valid {
                let requests = admitted.into_iter().map(|(_, item)| item.request).collect();
                let mut grants = grants.into_iter();
                run_verified_batch(
                    &self.authority,
                    &mut self.worker,
                    &mut grants,
                    now_ms,
                    &model_id,
                    requests,
                )
            } else {
                Err(BatchWorkerErrorV1::Authority)
            };
            match result {
                Ok(receipts) if receipts.len() == ids.len() => {
                    outcomes.extend(ids.into_iter().zip(receipts).map(|(id, receipt)| {
                        BatchWorkerItemOutcomeV1 {
                            request_id: id,
                            result: Ok(receipt),
                        }
                    }));
                }
                Ok(_) => {
                    outcomes.extend(ids.into_iter().map(|id| BatchWorkerItemOutcomeV1 {
                        request_id: id,
                        result: Err(BatchWorkerErrorV1::Worker),
                    }));
                }
                Err(error) => {
                    outcomes.extend(ids.into_iter().map(|id| BatchWorkerItemOutcomeV1 {
                        request_id: id,
                        result: Err(error),
                    }));
                }
            }
        }
        for outcome in &outcomes {
            let succeeded = matches!(
                &outcome.result,
                Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
            );
            self.emit_metric(
                &batch.key.scope_id,
                &outcome.request_id,
                PhaseMetricKindV1::NeuronFeature,
                started.elapsed(),
                succeeded,
            );
        }
        outcomes
    }
}
