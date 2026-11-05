//! Shared compute batching. State and commits remain independently owned.

use std::collections::VecDeque;

use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;
use codex_hepta_types::StableId;

use crate::InferenceControlModelPort;
use crate::NeuronInferenceControlPort;
use crate::NeuronModelError;
use crate::NeuronModelPort;
use crate::NeuronModelRequestV1;
use crate::cell_types::*;
use crate::runtime_types::validate_model_output;

/// The inference.control owner authenticates observations and retains dispatch
/// reservations. This contract accepts complete request-bound feature receipts;
/// a caller-supplied routing digest cannot bless arbitrary model output.
pub trait CellMicrobatchInferenceControlPortV1 {
    fn execute_feature_batch(
        &mut self,
        requests: &[NeuronFeatureRequestV1],
    ) -> Result<Vec<NeuronFeatureReceiptV1>, NeuronModelError>;
}

struct ReceiptPort(NeuronFeatureReceiptV1);

impl NeuronInferenceControlPort for ReceiptPort {
    fn execute_feature(
        &mut self,
        _: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        Ok(self.0.clone())
    }
}

fn feature_request(request: &NeuronModelRequestV1) -> NeuronFeatureRequestV1 {
    NeuronFeatureRequestV1 {
        request_id: request.request_id.clone(),
        generation: request.generation,
        model_id: request.model_id.clone(),
        encoder_digest: request.encoder_digest,
        head_digest: request.head_digest,
        weights_digest: request.weights_digest,
        input_digest: request.input_digest,
        feature_vector_q24: request.feature_vector_q24.clone(),
        expected_output_width: request.expected_output_width,
    }
}

pub struct CellBatchResultV1 {
    pub scope: CellScopeV1,
    pub operation_id: StableId,
    pub result: Result<InferredCellStepV1, CellExecutionError>,
}

struct QueuedCell {
    prepared: PreparedCellStepV1,
    enqueued_at_micros: u64,
}

pub struct CellBatchQueueV1 {
    queue: VecDeque<QueuedCell>,
    max_queued: usize,
    max_batch: usize,
}

impl CellBatchQueueV1 {
    pub fn new(max_queued: usize, max_batch: usize) -> Result<Self, CellExecutionError> {
        if !(1..=1024).contains(&max_queued)
            || !(1..=64).contains(&max_batch)
            || max_batch > max_queued
        {
            return Err(CellExecutionError::CapacityExceeded);
        }
        Ok(Self { queue: VecDeque::new(), max_queued, max_batch })
    }

    pub fn enqueue(
        &mut self,
        prepared: PreparedCellStepV1,
        now_micros: u64,
    ) -> Result<(), CellExecutionError> {
        if now_micros < prepared.input.monotonic_micros || now_micros >= prepared.input.deadline_micros {
            return Err(CellExecutionError::DeadlineExceeded);
        }
        if self.queue.len() == self.max_queued {
            return Err(CellExecutionError::CapacityExceeded);
        }
        if self.queue.iter().any(|p| {
            p.prepared.input.scope == prepared.input.scope
                && p.prepared.input.operation_id == prepared.input.operation_id
        }) {
            return Err(CellExecutionError::OperationConflict);
        }
        self.queue.push_back(QueuedCell { prepared, enqueued_at_micros: now_micros });
        Ok(())
    }

    pub fn dispatch_next(
        &mut self,
        model: &mut impl CellMicrobatchInferenceControlPortV1,
        now_micros: u64,
    ) -> Vec<CellBatchResultV1> {
        let Some(first) = self.queue.pop_front() else {
            return Vec::new();
        };
        let mut group = vec![first];
        let mut index = 0;
        while index < self.queue.len() && group.len() < self.max_batch {
            let candidate = &self.queue[index].prepared;
            if candidate.definition.runtime == group[0].prepared.definition.runtime
                && candidate.definition.bundle_digest == group[0].prepared.definition.bundle_digest
                && candidate.definition.state_schema_digest == group[0].prepared.definition.state_schema_digest
            {
                if let Some(prepared) = self.queue.remove(index) {
                    group.push(prepared);
                }
            } else {
                index += 1;
            }
        }
        let mut completed = Vec::new();
        let mut ready = Vec::new();
        for queued in group {
            let prepared = queued.prepared;
            let queue_age = now_micros.saturating_sub(queued.enqueued_at_micros);
            if now_micros < queued.enqueued_at_micros
                || now_micros >= prepared.input.deadline_micros
                || queue_age > prepared.definition.max_queue_age_micros
            {
                completed.push(CellBatchResultV1 {
                    scope: prepared.input.scope,
                    operation_id: prepared.input.operation_id,
                    result: Err(CellExecutionError::DeadlineExceeded),
                });
            } else {
                ready.push((prepared, queue_age));
            }
        }
        if ready.is_empty() {
            return completed;
        }
        let requests: Vec<_> = ready.iter()
            .map(|(p, _)| feature_request(&p.model_request))
            .collect();
        match model.execute_feature_batch(&requests) {
            Err(error) => {
                for (prepared, _) in ready {
                    completed.push(CellBatchResultV1 {
                        scope: prepared.input.scope,
                        operation_id: prepared.input.operation_id,
                        result: Err(CellExecutionError::Backend(error)),
                    });
                }
            }
            Ok(mut results) => {
                let valid_membership = results.len() == requests.len()
                    && requests.iter().all(|request| {
                        results.iter().filter(|r| {
                            Some(r.request_digest) == neuron_feature_request_digest_v1(request).ok()
                        }).count() == 1
                    });
                for (prepared, queue_age) in ready {
                    let scope = prepared.input.scope.clone();
                    let operation_id = prepared.input.operation_id.clone();
                    let expected = neuron_feature_request_digest_v1(&feature_request(&prepared.model_request)).ok();
                    let result = if !valid_membership {
                        Err(CellExecutionError::ModelBindingMismatch)
                    } else if let Some(index) = results.iter().position(|r| Some(r.request_digest) == expected) {
                        let mut port = ReceiptPort(results.remove(index));
                        match InferenceControlModelPort::new(&mut port).execute(&prepared.model_request) {
                            Err(error) => Err(CellExecutionError::Backend(error)),
                            Ok(mut output) => {
                                output.queue_age_micros = output.queue_age_micros.saturating_add(queue_age);
                                validate_model_output(&prepared.definition.runtime, &output)
                                    .map_err(|_| CellExecutionError::ModelBindingMismatch)
                                    .map(|()| InferredCellStepV1 { prepared, output })
                            }
                        }
                    } else {
                        Err(CellExecutionError::ModelBindingMismatch)
                    };
                    completed.push(CellBatchResultV1 { scope, operation_id, result });
                }
            }
        }
        completed
    }
}
