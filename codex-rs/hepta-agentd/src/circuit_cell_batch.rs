//! Bounded numerical batches behind the existing Circuit and Cell owners.

use std::cell::RefCell;

use codex_hepta_automation::CircuitComputationAdmissionV2;
use codex_hepta_neuron::CellBatchQueueV1;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::CellExecutionError;
use codex_hepta_neuron::CellInferenceReadbackPortV1;
use codex_hepta_neuron::CellInputEncoderV1;
use codex_hepta_neuron::CellMicrobatchInferenceControlPortV1;
use codex_hepta_neuron::CellStateOwnerV1;
use codex_hepta_neuron::CellStepEntryV1;
use codex_hepta_neuron::CellStepInputV1;
use codex_hepta_neuron::InferredCellStepV1;
use codex_hepta_neuron::NeuronFeatureReceiptV1;
use codex_hepta_neuron::NeuronFeatureRequestV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::PreparedCellStepV1;
use codex_hepta_neuron::canonical_cell_step_request_digest_v1;
use codex_hepta_neuron::commit_cell_step;
use codex_hepta_neuron::decide_cell;
use codex_hepta_neuron::enter_cell_step;
use codex_hepta_neuron::recover_cell_inference;
use codex_hepta_types::StableId;

use super::AgentdCircuitCellOwnerV1;
use super::CircuitCellErrorV1;
use super::CircuitCellExecutionV1;
use super::CircuitCellTimeV1;
use super::finish;

enum BatchEntry {
    Ready(Box<PreparedCellStepV1>),
    Committed(Box<CellDecisionReceiptV1>),
}

impl<O, P, E> AgentdCircuitCellOwnerV1<O, P, E>
where
    O: CellStateOwnerV1,
    P: NeuronInferenceControlPort
        + CellInferenceReadbackPortV1
        + CellMicrobatchInferenceControlPortV1,
    E: CellInputEncoderV1,
{
    /// Consume 1..=64 owner-issued admissions and return one result per input,
    /// in the same order. A Cell scope appears at most once in this batch.
    /// Compatible frozen runtime/bundle/schema requests share a numerical call;
    /// every state admission and decision commit remains independently owned.
    /// Pending and committed operations use original-request readback only.
    ///
    /// Each group rechecks both clocks after all durable admissions. If any
    /// group deadline expires, that numerical call is refused and pending state
    /// is retained. Errors never refund unknown work or authorize redispatch.
    /// The caller still commits each successful completion with Circuit CAS.
    pub fn execute_batch(
        &mut self,
        items: Vec<(CircuitComputationAdmissionV2, CellStepInputV1)>,
        clock: impl FnMut() -> CircuitCellTimeV1,
    ) -> Result<Vec<Result<CircuitCellExecutionV1, CircuitCellErrorV1>>, CircuitCellErrorV1> {
        if !(1..=64).contains(&items.len()) {
            return Err(CellExecutionError::CapacityExceeded.into());
        }
        let clock = RefCell::new(BatchClock {
            clock,
            last: None,
            failed: false,
        });
        let mut queue = CellBatchQueueV1::new(items.len(), items.len())?;
        let mut bindings = vec![None; items.len()];
        let mut results = vec![None; items.len()];
        let mut queued = Vec::new();
        let mut deadlines = Vec::new();
        for (index, (admission, input)) in items.iter().enumerate() {
            let entry = (|| {
                if items[..index]
                    .iter()
                    .any(|(_, previous)| previous.scope == input.scope)
                {
                    return Err(CellExecutionError::OperationConflict.into());
                }
                let binding = self.registry.bind_input(admission.dispatch(), input)?;
                bindings[index] = Some(binding);
                if input.observation.len() > binding.cell.max_input_bytes
                    || input.candidates.len() > binding.cell.candidates.len()
                {
                    return Err(CellExecutionError::CapacityExceeded.into());
                }
                let request = canonical_cell_step_request_digest_v1(&binding.cell, input)?;
                if admission.owner_agent_id().as_str() != input.scope.agent_id.as_str()
                    || admission.definition_digest() != self.registry.definition_digest()
                    || admission
                        .execution_request_digest()
                        .is_none_or(|digest| digest.as_str() != request.to_string())
                {
                    return Err(CircuitCellErrorV1::ScopeMismatch);
                }
                let now = clock.borrow_mut().read()?;
                if now.circuit_millis < admission.observed_at_ms() {
                    return Err(CircuitCellErrorV1::ReconciliationRequired);
                }
                match self
                    .state_owner
                    .lookup(&input.scope, &input.operation_id, request)
                {
                    Ok(Some(receipt)) => return Ok(BatchEntry::Committed(Box::new(receipt))),
                    Ok(None) | Err(CellExecutionError::InferencePending) => {}
                    Err(error) => return Err(error.into()),
                }
                if self.state_owner.pending_inference(&input.scope)?.is_some() {
                    let inferred = recover_cell_inference(
                        &binding.cell,
                        &self.state_owner,
                        &self.encoder,
                        input.clone(),
                        &mut self.inference_control,
                        now.cell_micros,
                    )?;
                    return settle(&mut self.state_owner, inferred, &clock)
                        .map(Box::new)
                        .map(BatchEntry::Committed);
                }
                if admission.reconciliation_only()
                    || now.circuit_millis
                        >= admission
                            .lease_expires_at_ms()
                            .min(admission.run_deadline_ms())
                {
                    return Err(CircuitCellErrorV1::ReconciliationRequired);
                }
                match enter_cell_step(
                    &binding.cell,
                    &self.state_owner,
                    &self.encoder,
                    input.clone(),
                    now.cell_micros,
                )? {
                    CellStepEntryV1::Ready(prepared) => Ok(BatchEntry::Ready(prepared)),
                    CellStepEntryV1::Replayed(receipt) => Ok(BatchEntry::Committed(receipt)),
                }
            })();
            match entry {
                Ok(BatchEntry::Ready(prepared)) => {
                    let request_id = prepared.model_request_id().clone();
                    let enqueued = clock.borrow_mut().read().and_then(|now| {
                        queue
                            .enqueue(*prepared, now.cell_micros)
                            .map(|()| now)
                            .map_err(Into::into)
                    });
                    match enqueued {
                        Ok(now) => {
                            queued.push(index);
                            deadlines.push(BatchDeadline {
                                request_id,
                                circuit_millis: admission
                                    .lease_expires_at_ms()
                                    .min(admission.run_deadline_ms()),
                                cell_micros: input.deadline_micros,
                                enqueued_micros: now.cell_micros,
                                max_queue_age_micros: bindings[index]
                                    .ok_or(CircuitCellErrorV1::InvalidBinding)?
                                    .cell
                                    .max_queue_age_micros,
                            });
                        }
                        Err(error) => results[index] = Some(Err(error)),
                    }
                }
                Ok(BatchEntry::Committed(receipt)) => {
                    results[index] = Some(finish(
                        bindings[index].ok_or(CircuitCellErrorV1::InvalidBinding)?,
                        admission.dispatch(),
                        input,
                        *receipt,
                    ));
                }
                Err(error) => results[index] = Some(Err(error)),
            }
        }
        while !queued.is_empty() {
            let batch = {
                let mut guarded = GuardedBatch {
                    control: &mut self.inference_control,
                    clock: &clock,
                    deadlines: &deadlines,
                };
                queue.dispatch_next(&mut self.state_owner, &mut guarded, || {
                    clock
                        .borrow_mut()
                        .read()
                        .map_or(u64::MAX, |now| now.cell_micros)
                })
            };
            if batch.is_empty() {
                for index in queued {
                    results[index] = Some(Err(CircuitCellErrorV1::InvalidReceipt));
                }
                break;
            }
            for item in batch {
                let position = queued
                    .iter()
                    .position(|index| {
                        item.scope == items[*index].1.scope
                            && item.operation_id == items[*index].1.operation_id
                    })
                    .ok_or(CircuitCellErrorV1::InvalidReceipt)?;
                let index = queued.remove(position);
                let (admission, input) = &items[index];
                results[index] = Some(
                    item.result
                        .map_err(Into::into)
                        .and_then(|inferred| settle(&mut self.state_owner, inferred, &clock))
                        .and_then(|receipt| {
                            finish(
                                bindings[index].ok_or(CircuitCellErrorV1::InvalidBinding)?,
                                admission.dispatch(),
                                input,
                                receipt,
                            )
                        }),
                );
            }
        }
        Ok(results
            .into_iter()
            .map(|result| result.unwrap_or(Err(CircuitCellErrorV1::InvalidReceipt)))
            .collect())
    }
}

struct BatchClock<C> {
    clock: C,
    last: Option<CircuitCellTimeV1>,
    failed: bool,
}

impl<C: FnMut() -> CircuitCellTimeV1> BatchClock<C> {
    fn read(&mut self) -> Result<CircuitCellTimeV1, CircuitCellErrorV1> {
        let now = (self.clock)();
        if self.failed
            || self.last.is_some_and(|last| {
                now.circuit_millis < last.circuit_millis || now.cell_micros < last.cell_micros
            })
        {
            self.failed = true;
            return Err(CircuitCellErrorV1::ReconciliationRequired);
        }
        self.last = Some(now);
        Ok(now)
    }
}

fn settle<O: CellStateOwnerV1, C: FnMut() -> CircuitCellTimeV1>(
    owner: &mut O,
    inferred: InferredCellStepV1,
    clock: &RefCell<BatchClock<C>>,
) -> Result<CellDecisionReceiptV1, CircuitCellErrorV1> {
    let decided = clock.borrow_mut().read()?;
    let proposal = decide_cell(inferred, decided.cell_micros)?;
    let committed = clock.borrow_mut().read()?;
    Ok(commit_cell_step(owner, proposal, committed.cell_micros)?)
}

struct BatchDeadline {
    request_id: StableId,
    circuit_millis: u64,
    cell_micros: u64,
    enqueued_micros: u64,
    max_queue_age_micros: u64,
}

struct GuardedBatch<'a, P, C> {
    control: &'a mut P,
    clock: &'a RefCell<BatchClock<C>>,
    deadlines: &'a [BatchDeadline],
}

impl<P: CellMicrobatchInferenceControlPortV1, C: FnMut() -> CircuitCellTimeV1>
    CellMicrobatchInferenceControlPortV1 for GuardedBatch<'_, P, C>
{
    fn execute_feature_batch(
        &mut self,
        requests: &[NeuronFeatureRequestV1],
    ) -> Result<Vec<NeuronFeatureReceiptV1>, NeuronModelError> {
        let now = self
            .clock
            .borrow_mut()
            .read()
            .map_err(|_| NeuronModelError::Rejected)?;
        if requests.is_empty()
            || requests.len() > 64
            || requests.iter().any(|request| {
                let mut matched = self
                    .deadlines
                    .iter()
                    .filter(|item| item.request_id == request.request_id);
                let Some(deadline) = matched.next() else {
                    return true;
                };
                matched.next().is_some()
                    || now.circuit_millis >= deadline.circuit_millis
                    || now.cell_micros >= deadline.cell_micros
                    || now
                        .cell_micros
                        .checked_sub(deadline.enqueued_micros)
                        .is_none_or(|age| age > deadline.max_queue_age_micros)
            })
        {
            return Err(NeuronModelError::Rejected);
        }
        self.control.execute_feature_batch(requests)
    }
}
