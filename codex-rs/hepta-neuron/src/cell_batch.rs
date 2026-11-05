//! Shared compute batching. State and commits remain independently owned.

use std::collections::VecDeque;

use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;
use codex_hepta_types::StableId;

use crate::InferenceControlModelPort;
use crate::NeuronModelError;
use crate::NeuronModelPort;
use crate::cell_types::*;
use crate::cell_inference::ReceiptPort;
use crate::cell_inference::admission_for_step;
use crate::cell_inference::feature_request;
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

    /// Read the owner's monotonic clock before admission and again after all
    /// durable admissions. Expiry or clock rollback retains pending state and
    /// never sends that request to the shared inference facility.
    pub fn dispatch_next(
        &mut self,
        owner: &mut impl CellStateOwnerV1,
        model: &mut impl CellMicrobatchInferenceControlPortV1,
        mut clock_micros: impl FnMut() -> u64,
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
        let mut admitted = Vec::new();
        let admitted_at_micros = clock_micros();
        for queued in group {
            let prepared = queued.prepared;
            let result = queue_age_at(&prepared, queued.enqueued_at_micros, admitted_at_micros)
                .and_then(|_| admission_for_step(&prepared, admitted_at_micros))
                .and_then(|admission| owner.admit_inference(admission));
            match result {
                Ok(()) => admitted.push((prepared, queued.enqueued_at_micros)),
                Err(error) => completed.push(CellBatchResultV1 {
                    scope: prepared.input.scope,
                    operation_id: prepared.input.operation_id,
                    result: Err(error),
                }),
            }
        }
        if admitted.is_empty() {
            return completed;
        }
        // Admission can fsync a shared journal and its independent witness.
        // This fresh sample includes that elapsed time. No durable I/O occurs
        // between this check and the batch call. Rejected admissions stay held;
        // a timeout does not prove that the original request made no contact.
        let dispatch_at_micros = clock_micros();
        let mut ready = Vec::new();
        for (prepared, enqueued_at_micros) in admitted {
            let result = if dispatch_at_micros < admitted_at_micros {
                Err(CellExecutionError::DeadlineExceeded)
            } else {
                queue_age_at(&prepared, enqueued_at_micros, dispatch_at_micros)
            };
            match result {
                Ok(queue_age) => ready.push((prepared, queue_age)),
                Err(error) => completed.push(CellBatchResultV1 {
                    scope: prepared.input.scope,
                    operation_id: prepared.input.operation_id,
                    result: Err(error),
                }),
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
                                    .map(|()| InferredCellStepV1 { prepared, output, not_before_micros: dispatch_at_micros })
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

fn queue_age_at(
    prepared: &PreparedCellStepV1,
    enqueued_at_micros: u64,
    now_micros: u64,
) -> Result<u64, CellExecutionError> {
    let age = now_micros.checked_sub(enqueued_at_micros)
        .ok_or(CellExecutionError::DeadlineExceeded)?;
    if now_micros < prepared.input.monotonic_micros
        || now_micros >= prepared.input.deadline_micros
        || age > prepared.definition.max_queue_age_micros
    {
        return Err(CellExecutionError::DeadlineExceeded);
    }
    Ok(age)
}
