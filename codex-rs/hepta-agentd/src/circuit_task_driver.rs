//! Concrete task pump. Only sealed AutomationStore admissions enter a Cell;
//! only that Cell owner's committed decision can settle the Circuit.

use std::collections::BTreeMap;
use std::time::Duration;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitActivationStatusV2;
use codex_hepta_automation::CircuitCommandV2;
use codex_hepta_automation::CircuitCommittedTraceV2;
use codex_hepta_automation::CircuitComputationClaimV2;
use codex_hepta_automation::CircuitEventV2;
use codex_hepta_automation::TaskFlowError;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_neuron::CellInferenceReadbackPortV1;
use codex_hepta_neuron::CellInputEncoderV1;
use codex_hepta_neuron::CellStateOwnerV1;
use codex_hepta_neuron::CellStepInputV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::canonical_cell_step_request_digest_v1;

use super::CircuitTaskErrorV1 as Error;
use super::CircuitTaskInputModeV1;
use super::CircuitTaskInputProviderV1;
use super::CircuitTaskModeV1;
use super::CircuitTaskReceiptV1;
use super::CircuitTaskRequestV1;
use crate::AgentdCircuitCellOwnerV1;
use crate::CircuitCellErrorV1;
use crate::CircuitCellExecutionV1;
use crate::CircuitCellTimeV1;
use crate::circuit_cell::finish;

pub(super) struct CircuitTaskDriverV1<O, P, E, I> {
    pub(super) store: AutomationStore,
    pub(super) fence: TaskFlowFence,
    pub(super) cells: AgentdCircuitCellOwnerV1<O, P, E>,
    pub(super) inputs: I,
}

impl<O, P, E, I> CircuitTaskDriverV1<O, P, E, I>
where
    O: CellStateOwnerV1 + Send,
    P: NeuronInferenceControlPort + CellInferenceReadbackPortV1 + Send,
    E: CellInputEncoderV1 + Send,
    I: CircuitTaskInputProviderV1,
{
    pub(super) async fn execute(
        &mut self,
        request: &CircuitTaskRequestV1,
        mode: CircuitTaskModeV1,
        mut clock: impl FnMut() -> Result<CircuitCellTimeV1, Error> + Send,
    ) -> Result<CircuitTaskReceiptV1, Error> {
        let circuit_deadline = request
            .start
            .created_at_ms
            .checked_add(self.cells.registry().definition().limits.max_elapsed_ms)
            .ok_or(Error::InvalidBinding)?;
        clock()?;
        let existing = self
            .store
            .read_bounded_circuit_task(
                self.cells.registry().definition(),
                &request.start,
                &self.fence,
            )
            .await?;
        let before_create = clock()?;
        let mut run = match &existing {
            Some(trace) => trace.run().clone(),
            None => {
                if matches!(mode, CircuitTaskModeV1::Readback) {
                    return Err(Error::ReconciliationRequired);
                }
                require_before_deadline(request, before_create)?;
                self.store
                    .create_bounded_circuit_run(
                        self.cells.registry().definition(),
                        &request.start,
                        &self.fence,
                    )
                    .await
                    .map_err(mutation_error)?
                    .run
            }
        };
        let mut completed = match (existing, run.outcome(), mode) {
            (Some(trace), None, CircuitTaskModeV1::Drive) => self.materialize(request, &trace)?,
            _ => BTreeMap::new(),
        };
        loop {
            let time = clock()?;
            if run.outcome().is_some() || matches!(mode, CircuitTaskModeV1::Readback) {
                let trace = self
                    .store
                    .read_bounded_circuit_task(
                        self.cells.registry().definition(),
                        &request.start,
                        &self.fence,
                    )
                    .await?
                    .ok_or(Error::ReconciliationRequired)?;
                let executions = self.materialize(request, &trace)?;
                clock()?;
                return Ok(CircuitTaskReceiptV1 { trace, executions });
            }
            require_before_deadline(request, time)?;
            if let Some(pending) = run.activations().values().find(|activation| {
                matches!(
                    activation.status,
                    CircuitActivationStatusV2::InFlight | CircuitActivationStatusV2::Indeterminate
                )
            }) {
                let activation_id = pending.activation_id;
                let status = pending.status;
                let observed = self
                    .store
                    .recover_circuit_computation(
                        &request.start.run_id,
                        activation_id,
                        &self.fence,
                        time.circuit_millis,
                    )
                    .await?;
                let input_mode = if observed.execution_request_digest().is_some() {
                    CircuitTaskInputModeV1::Readback
                } else {
                    CircuitTaskInputModeV1::Prepare
                };
                let input =
                    self.inputs
                        .resolve(request, observed.dispatch(), &completed, input_mode)?;
                self.validate_input(request, &input)?;
                let binding = self
                    .cells
                    .registry()
                    .bind_input(observed.dispatch(), &input)?;
                let digest = canonical_cell_step_request_digest_v1(&binding.cell, &input)
                    .map_err(CircuitCellErrorV1::from)?;
                let execution_request_digest =
                    Sha256Digest::parse(digest.to_string()).map_err(|_| Error::InvalidBinding)?;
                let before_claim = clock()?;
                require_before_deadline(request, before_claim)?;
                let admission = if observed.execution_request_digest().is_none() {
                    self.store
                        .claim_circuit_computation(&CircuitComputationClaimV2 {
                            run_id: request.start.run_id.clone(),
                            activation_id,
                            command_id: format!("task-cell-claim:{activation_id}"),
                            fence: self.fence.clone(),
                            expected_revision: observed.observed_revision(),
                            now_ms: before_claim.circuit_millis,
                            execution_request_digest,
                        })
                        .await
                        .map_err(mutation_error)?
                } else {
                    observed
                };
                let expected_revision = admission.observed_revision();
                // Synchronous inference stays on the one owned blocking lane.
                // Once authority or time fails, every remaining clock sample
                // is fenced; returning authority later cannot revive this call.
                let mut clock_error = None;
                let execution = self.cells.execute(admission, input, || {
                    if clock_error.is_none() {
                        match clock().and_then(|time| {
                            require_before_deadline(request, time)?;
                            Ok(time)
                        }) {
                            Ok(time) => return time,
                            Err(error) => clock_error = Some(error),
                        }
                    }
                    CircuitCellTimeV1 {
                        circuit_millis: u64::MAX,
                        cell_micros: u64::MAX,
                    }
                });
                if let Some(error) = clock_error {
                    return Err(error);
                }
                let execution = execution?;
                let after = clock()?;
                require_before_deadline(request, after)?;
                let event = if status == CircuitActivationStatusV2::Indeterminate {
                    CircuitEventV2::Reconcile {
                        completion: execution.completion.clone(),
                    }
                } else {
                    CircuitEventV2::Complete {
                        completion: execution.completion.clone(),
                    }
                };
                run = self
                    .store
                    .apply_bounded_circuit_command(&CircuitCommandV2 {
                        run_id: request.start.run_id.clone(),
                        command_id: format!("task-cell-complete:{activation_id}"),
                        fence: self.fence.clone(),
                        expected_revision,
                        now_ms: after.circuit_millis,
                        event,
                    })
                    .await
                    .map_err(mutation_error)?
                    .run;
                completed.insert(activation_id, execution);
                continue;
            }
            let wake_at = run
                .activations()
                .values()
                .filter_map(|activation| match activation.status {
                    CircuitActivationStatusV2::Ready => Some(activation.ready_at_ms),
                    CircuitActivationStatusV2::Joining => activation.join_deadline_ms(),
                    CircuitActivationStatusV2::InFlight
                    | CircuitActivationStatusV2::Indeterminate
                    | CircuitActivationStatusV2::ChildRunning
                    | CircuitActivationStatusV2::Completed
                    | CircuitActivationStatusV2::Cancelled => None,
                })
                .min()
                .unwrap_or(circuit_deadline)
                .min(circuit_deadline);
            if wake_at > time.circuit_millis {
                // Waiting does not append empty Advance events or spend event
                // budget. Revalidate generation, trust and cancellation often.
                let delay = wake_at
                    .min(request.deadline_ms)
                    .saturating_sub(time.circuit_millis)
                    .min(250);
                tokio::time::sleep(Duration::from_millis(delay)).await;
                run = self
                    .store
                    .bounded_circuit_run(&request.start.run_id)
                    .await?
                    .ok_or(Error::ReconciliationRequired)?;
                continue;
            }
            let before_advance = clock()?;
            require_before_deadline(request, before_advance)?;
            run = self
                .store
                .apply_bounded_circuit_command(&CircuitCommandV2 {
                    run_id: request.start.run_id.clone(),
                    command_id: format!("task-advance:{}", run.revision()),
                    fence: self.fence.clone(),
                    expected_revision: run.revision(),
                    now_ms: before_advance.circuit_millis,
                    event: CircuitEventV2::Advance { quantum: 1 },
                })
                .await
                .map_err(mutation_error)?
                .run;
        }
    }

    fn materialize(
        &mut self,
        request: &CircuitTaskRequestV1,
        trace: &CircuitCommittedTraceV2,
    ) -> Result<BTreeMap<u64, CircuitCellExecutionV1>, Error> {
        let dispatches = trace
            .run()
            .completed_computation_dispatches(self.cells.registry().definition())?;
        if dispatches.len() != trace.completions().len() {
            return Err(Error::ReconciliationRequired);
        }
        let mut executions = BTreeMap::new();
        for dispatch in dispatches {
            let input = self.inputs.resolve(
                request,
                &dispatch,
                &executions,
                CircuitTaskInputModeV1::Readback,
            )?;
            self.validate_input(request, &input)?;
            let binding = self.cells.registry().bind_input(&dispatch, &input)?;
            let digest = canonical_cell_step_request_digest_v1(&binding.cell, &input)
                .map_err(CircuitCellErrorV1::from)?;
            let decision = self
                .cells
                .state_owner()
                .lookup(&input.scope, &input.operation_id, digest)
                .map_err(CircuitCellErrorV1::from)?
                .ok_or(Error::ReconciliationRequired)?;
            let execution = finish(binding, &dispatch, &input, decision)?;
            if trace.completions().get(&dispatch.activation_id) != Some(&execution.completion)
                || trace.run().activations()[&dispatch.activation_id]
                    .execution_request_digest()
                    .is_none_or(|retained| retained.as_str() != digest.to_string())
            {
                return Err(Error::ReconciliationRequired);
            }
            executions.insert(dispatch.activation_id, execution);
        }
        Ok(executions)
    }

    fn validate_input(
        &self,
        request: &CircuitTaskRequestV1,
        input: &CellStepInputV1,
    ) -> Result<(), Error> {
        if input.scope.agent_id.as_str() != self.fence.owner_agent_id.as_str()
            || input.scope.run_id.as_str() != request.start.run_id
            || input.objective_digest != request.objective_digest
        {
            return Err(Error::InvalidBinding);
        }
        Ok(())
    }
}

fn require_before_deadline(
    request: &CircuitTaskRequestV1,
    time: CircuitCellTimeV1,
) -> Result<(), Error> {
    if time.circuit_millis < request.start.created_at_ms {
        return Err(Error::InvalidBinding);
    }
    if time.circuit_millis >= request.deadline_ms {
        return Err(Error::DeadlineExceeded);
    }
    Ok(())
}

fn mutation_error(error: TaskFlowError) -> Error {
    match error {
        TaskFlowError::Unavailable => Error::CommitUncertain,
        error => Error::Circuit(error),
    }
}

#[cfg(test)]
#[path = "circuit_task_driver_tests.rs"]
mod tests;
