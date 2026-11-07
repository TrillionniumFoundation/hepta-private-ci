//! Shared compute batching. State and commits remain independently owned.

use std::collections::VecDeque;

use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;
use codex_hepta_types::StableId;

use crate::InferenceControlModelPort;
use crate::NeuronModelError;
use crate::NeuronModelPort;
use crate::cell_inference::ReceiptPort;
use crate::cell_inference::admission_for_step;
use crate::cell_inference::feature_request;
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

pub struct CellBatchResultV1 {
    pub scope: CellScopeV1,
    pub operation_id: StableId,
    pub result: Result<InferredCellStepV1, CellExecutionError>,
}

struct QueuedCell {
    prepared: PreparedCellStepV1,
    enqueued_at_micros: u64,
    payload_bytes: u64,
}

/// Independent count and retained input-buffer limits. These account for the
/// observation, candidate-mask allocation, canonical input identifiers and both
/// owned feature buffers (including spare capacity). Definition, model and
/// checkpoint metadata remain subject to their own limits; this is not RSS.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellBatchQueueLimitsV1 {
    pub max_queued: usize,
    pub max_batch: usize,
    pub max_queued_payload_bytes: u64,
    pub max_batch_payload_bytes: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellBatchQueueObservationV1 {
    pub queued: usize,
    pub retained_payload_bytes: u64,
    pub limits: CellBatchQueueLimitsV1,
}

/// Only a queued item can be cancelled without consulting a durable owner.
/// NotQueued says nothing about an earlier dispatch or an UNKNOWN outcome.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellQueuedCancellationV1 {
    /// Removed before this queue admitted it. Another caller may already have
    /// admitted the same operation; only the durable owner can answer that.
    RemovedBeforeQueueDispatch,
    NotQueued,
}

pub struct CellBatchQueueV1 {
    queue: VecDeque<QueuedCell>,
    limits: CellBatchQueueLimitsV1,
    retained_payload_bytes: u64,
}

impl CellBatchQueueV1 {
    pub fn new(max_queued: usize, max_batch: usize) -> Result<Self, CellExecutionError> {
        Self::with_limits(CellBatchQueueLimitsV1 {
            max_queued,
            max_batch,
            max_queued_payload_bytes: 64 * 1024 * 1024,
            max_batch_payload_bytes: 8 * 1024 * 1024,
        })
    }

    pub fn with_limits(limits: CellBatchQueueLimitsV1) -> Result<Self, CellExecutionError> {
        if !(1..=1024).contains(&limits.max_queued)
            || !(1..=64).contains(&limits.max_batch)
            || limits.max_batch > limits.max_queued
            || !(1..=1024 * 1024 * 1024).contains(&limits.max_queued_payload_bytes)
            || !(1..=64 * 1024 * 1024).contains(&limits.max_batch_payload_bytes)
            || limits.max_batch_payload_bytes > limits.max_queued_payload_bytes
        {
            return Err(CellExecutionError::CapacityExceeded);
        }
        Ok(Self {
            queue: VecDeque::new(),
            limits,
            retained_payload_bytes: 0,
        })
    }

    pub fn observation(&self) -> CellBatchQueueObservationV1 {
        CellBatchQueueObservationV1 {
            queued: self.queue.len(),
            retained_payload_bytes: self.retained_payload_bytes,
            limits: self.limits,
        }
    }

    /// Remove only an unadmitted activation. This cannot cancel an inference
    /// reservation, clear pending state, change a receipt or authorize a retry.
    pub fn cancel_queued(
        &mut self,
        scope: &CellScopeV1,
        operation_id: &StableId,
    ) -> CellQueuedCancellationV1 {
        let index = self.queue.iter().position(|queued| {
            &queued.prepared.input.scope == scope
                && &queued.prepared.input.operation_id == operation_id
        });
        if let Some(queued) = index.and_then(|index| self.queue.remove(index)) {
            self.retained_payload_bytes -= queued.payload_bytes;
            CellQueuedCancellationV1::RemovedBeforeQueueDispatch
        } else {
            CellQueuedCancellationV1::NotQueued
        }
    }

    pub fn enqueue(
        &mut self,
        mut prepared: PreparedCellStepV1,
        now_micros: u64,
    ) -> Result<(), CellExecutionError> {
        if now_micros < prepared.input.monotonic_micros
            || now_micros >= prepared.input.deadline_micros
        {
            return Err(CellExecutionError::DeadlineExceeded);
        }
        // StableId bounds logical length, but its input String may have spare
        // capacity. Rebuild these bounded identifiers before retaining them;
        // their bytes and the prepared operation digest remain unchanged.
        for id in [
            &mut prepared.input.operation_id,
            &mut prepared.input.scope.agent_id,
            &mut prepared.input.scope.cell_id,
            &mut prepared.input.scope.run_id,
        ]
        .into_iter()
        .chain(
            prepared
                .input
                .candidates
                .iter_mut()
                .map(|mask| &mut mask.candidate_id),
        ) {
            *id = StableId::new(id.as_str()).map_err(|_| CellExecutionError::InvalidInput)?;
        }
        let payload_bytes = retained_input_bytes(&prepared)?;
        let retained_payload_bytes = self
            .retained_payload_bytes
            .checked_add(payload_bytes)
            .ok_or(CellExecutionError::CapacityExceeded)?;
        if self.queue.len() == self.limits.max_queued
            || payload_bytes > self.limits.max_batch_payload_bytes
            || retained_payload_bytes > self.limits.max_queued_payload_bytes
        {
            return Err(CellExecutionError::CapacityExceeded);
        }
        if self.queue.iter().any(|p| {
            p.prepared.input.scope == prepared.input.scope
                && p.prepared.input.operation_id == prepared.input.operation_id
        }) {
            return Err(CellExecutionError::OperationConflict);
        }
        self.queue.push_back(QueuedCell {
            prepared,
            enqueued_at_micros: now_micros,
            payload_bytes,
        });
        self.retained_payload_bytes = retained_payload_bytes;
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
        let mut batch_payload_bytes = first.payload_bytes;
        self.retained_payload_bytes -= first.payload_bytes;
        let mut group = vec![first];
        let mut index = 0;
        while index < self.queue.len() && group.len() < self.limits.max_batch {
            let candidate = &self.queue[index].prepared;
            if candidate.definition.runtime == group[0].prepared.definition.runtime
                && candidate.definition.bundle_digest == group[0].prepared.definition.bundle_digest
                && candidate.definition.state_schema_digest
                    == group[0].prepared.definition.state_schema_digest
                && self.queue[index].payload_bytes
                    <= self.limits.max_batch_payload_bytes - batch_payload_bytes
            {
                if let Some(prepared) = self.queue.remove(index) {
                    batch_payload_bytes += prepared.payload_bytes;
                    self.retained_payload_bytes -= prepared.payload_bytes;
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
        let requests: Vec<_> = ready
            .iter()
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
                        results
                            .iter()
                            .filter(|r| {
                                Some(r.request_digest)
                                    == neuron_feature_request_digest_v1(request).ok()
                            })
                            .count()
                            == 1
                    });
                for (prepared, queue_age) in ready {
                    let scope = prepared.input.scope.clone();
                    let operation_id = prepared.input.operation_id.clone();
                    let expected =
                        neuron_feature_request_digest_v1(&feature_request(&prepared.model_request))
                            .ok();
                    let result = if !valid_membership {
                        Err(CellExecutionError::ModelBindingMismatch)
                    } else if let Some(index) = results
                        .iter()
                        .position(|r| Some(r.request_digest) == expected)
                    {
                        let mut port = ReceiptPort(results.remove(index));
                        match InferenceControlModelPort::new(&mut port)
                            .execute(&prepared.model_request)
                        {
                            Err(error) => Err(CellExecutionError::Backend(error)),
                            Ok(mut output) => {
                                output.queue_age_micros =
                                    output.queue_age_micros.saturating_add(queue_age);
                                validate_model_output(&prepared.definition.runtime, &output)
                                    .map_err(|_| CellExecutionError::ModelBindingMismatch)
                                    .map(|()| InferredCellStepV1 {
                                        prepared,
                                        output,
                                        not_before_micros: dispatch_at_micros,
                                    })
                            }
                        }
                    } else {
                        Err(CellExecutionError::ModelBindingMismatch)
                    };
                    completed.push(CellBatchResultV1 {
                        scope,
                        operation_id,
                        result,
                    });
                }
            }
        }
        completed
    }
}

fn retained_input_bytes(prepared: &PreparedCellStepV1) -> Result<u64, CellExecutionError> {
    let observation = u64::try_from(prepared.input.observation.capacity());
    let encoded = u64::try_from(prepared.encoded.feature_vector_q24.capacity());
    let request = u64::try_from(prepared.model_request.feature_vector_q24.capacity());
    let candidates = u64::try_from(prepared.input.candidates.capacity())
        .ok()
        .and_then(|count| count.checked_mul(std::mem::size_of::<CellCandidateMaskV1>() as u64));
    let identifiers = [
        &prepared.input.operation_id,
        &prepared.input.scope.agent_id,
        &prepared.input.scope.cell_id,
        &prepared.input.scope.run_id,
    ]
    .into_iter()
    .chain(
        prepared
            .input
            .candidates
            .iter()
            .map(|mask| &mask.candidate_id),
    )
    .try_fold(0_u64, |total, id| {
        u64::try_from(id.as_str().len())
            .ok()
            .and_then(|bytes| total.checked_add(bytes))
    });
    observation
        .ok()
        .zip(encoded.ok())
        .zip(request.ok())
        .zip(candidates)
        .zip(identifiers)
        .and_then(
            |((((observation, encoded), request), candidates), identifiers)| {
                encoded
                    .checked_add(request)
                    .and_then(|features| features.checked_mul(8))
                    .and_then(|features| observation.checked_add(features))
                    .and_then(|buffers| buffers.checked_add(candidates))
                    .and_then(|buffers| buffers.checked_add(identifiers))
            },
        )
        .ok_or(CellExecutionError::CapacityExceeded)
}

fn queue_age_at(
    prepared: &PreparedCellStepV1,
    enqueued_at_micros: u64,
    now_micros: u64,
) -> Result<u64, CellExecutionError> {
    let age = now_micros
        .checked_sub(enqueued_at_micros)
        .ok_or(CellExecutionError::DeadlineExceeded)?;
    if now_micros < prepared.input.monotonic_micros
        || now_micros >= prepared.input.deadline_micros
        || age > prepared.definition.max_queue_age_micros
    {
        return Err(CellExecutionError::DeadlineExceeded);
    }
    Ok(age)
}

#[cfg(test)]
#[path = "cell_batch_budget_tests.rs"]
mod budget_tests;
