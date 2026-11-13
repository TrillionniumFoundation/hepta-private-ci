//! Root's original Cell pipeline with one private remote admission loan.
//! The daemon retains the actual non-Clone admission; this method cannot be
//! called with a dispatch DTO or a deserialized AutomationStore capability.

use super::*;
use crate::circuit_task::remote::OriginalRemoteAdmission;

impl<O, P, E> AgentdCircuitCellOwnerV1<O, P, E>
where
    O: CellStateOwnerV1,
    P: NeuronInferenceControlPort + CellInferenceReadbackPortV1,
    E: CellInputEncoderV1,
{
    pub(crate) fn execute_original_remote(
        &mut self,
        admission: OriginalRemoteAdmission,
        input: CellStepInputV1,
        mut clock: impl FnMut() -> CircuitCellTimeV1,
    ) -> Result<CircuitCellExecutionV1, CircuitCellErrorV1> {
        admission.require_current().map_err(|_| CircuitCellErrorV1::ReconciliationRequired)?;
        let original_clock = &mut clock;
        let loan_failed = Cell::new(false);
        let mut clock = || {
            if !loan_failed.get() {
                if let Ok(now_ms) = admission.require_current() {
                    let sampled = original_clock();
                    return CircuitCellTimeV1 {
                        circuit_millis: sampled.circuit_millis.max(now_ms),
                        cell_micros: sampled.cell_micros,
                    };
                }
                loan_failed.set(true);
            }
            CircuitCellTimeV1 { circuit_millis: u64::MAX, cell_micros: u64::MAX }
        };
        let dispatch = admission.dispatch();
        let binding = self.registry.bind_input(dispatch, &input)?;
        let request_digest = canonical_cell_step_request_digest_v1(&binding.cell, &input)?;
        if admission.owner_agent_id() != input.scope.agent_id.as_str()
            || admission.definition_digest() != self.registry.definition_digest()
            || admission
                .execution_request_digest()
                .is_none_or(|digest| digest.as_str() != request_digest.to_string())
        {
            return Err(CircuitCellErrorV1::ScopeMismatch);
        }
        let time = clock();
        if time.circuit_millis == u64::MAX
            || time.cell_micros == u64::MAX
            || time.circuit_millis < admission.observed_at_ms()
        {
            return Err(CircuitCellErrorV1::ReconciliationRequired);
        }
        let admission_deadline = admission
            .lease_expires_at_ms()
            .min(admission.run_deadline_ms());
        let read_only =
            admission.reconciliation_only() || time.circuit_millis >= admission_deadline;
        let committed =
            match self
                .state_owner
                .lookup(&input.scope, &input.operation_id, request_digest)
            {
                Ok(receipt) => receipt,
                Err(CellExecutionError::InferencePending) => None,
                Err(error) => return Err(error.into()),
            };
        let mut last_time = time;
        let decision = if let Some(receipt) = committed {
            receipt
        } else {
            let pending = self.state_owner.pending_inference(&input.scope)?;
            let inferred = if pending.is_some() {
                recover_cell_inference(
                    &binding.cell,
                    &self.state_owner,
                    &self.encoder,
                    input.clone(),
                    &mut self.inference_control,
                    time.cell_micros,
                )?
            } else {
                if read_only {
                    return Err(CircuitCellErrorV1::ReconciliationRequired);
                }
                match enter_cell_step(
                    &binding.cell,
                    &self.state_owner,
                    &self.encoder,
                    input.clone(),
                    time.cell_micros,
                )? {
                    CellStepEntryV1::Ready(prepared) => {
                        let sampled = Cell::new(time);
                        // The inference entry samples immediately after durable
                        // admission. Use that same live sample for the Circuit
                        // guard so its queue measurement ends at this boundary.
                        let mut dispatch_clock = || sampled.get();
                        let mut guarded = GuardedCellDispatchV1::new(
                            &mut self.inference_control,
                            &mut dispatch_clock,
                            time,
                            admission_deadline,
                            input.deadline_micros,
                        );
                        let mut invalid_clock = false;
                        let inferred = infer_cell_with_clock(
                            *prepared,
                            &mut self.state_owner,
                            &mut guarded,
                            || {
                                let before = sampled.get();
                                let now = clock();
                                if now.circuit_millis == u64::MAX
                                    || now.cell_micros == u64::MAX
                                    || now.circuit_millis < before.circuit_millis
                                    || now.cell_micros < before.cell_micros
                                    || now.circuit_millis >= admission_deadline
                                {
                                    invalid_clock = true;
                                    return u64::MAX;
                                }
                                sampled.set(now);
                                now.cell_micros
                            },
                        );
                        if invalid_clock {
                            return Err(CircuitCellErrorV1::ReconciliationRequired);
                        }
                        let inferred = inferred?;
                        last_time = guarded
                            .observed_at()
                            .ok_or(CircuitCellErrorV1::ReconciliationRequired)?;
                        inferred
                    }
                    CellStepEntryV1::Replayed(receipt) => {
                        if loan_failed.get() {
                            return Err(CircuitCellErrorV1::ReconciliationRequired);
                        }
                        admission.require_current().map_err(|_| CircuitCellErrorV1::ReconciliationRequired)?;
                        return finish(binding, dispatch, &input, *receipt);
                    }
                }
            };
            let decided_at = clock();
            if decided_at.circuit_millis == u64::MAX
                || decided_at.cell_micros == u64::MAX
                || decided_at.circuit_millis < last_time.circuit_millis
                || decided_at.cell_micros < last_time.cell_micros
            {
                return Err(CircuitCellErrorV1::ReconciliationRequired);
            }
            let proposal = decide_cell(inferred, decided_at.cell_micros)?;
            let committed_at = clock();
            if committed_at.circuit_millis == u64::MAX
                || committed_at.cell_micros == u64::MAX
                || committed_at.circuit_millis < decided_at.circuit_millis
                || committed_at.cell_micros < decided_at.cell_micros
            {
                return Err(CircuitCellErrorV1::ReconciliationRequired);
            }
            commit_cell_step(&mut self.state_owner, proposal, committed_at.cell_micros)?
        };
        if loan_failed.get() {
            return Err(CircuitCellErrorV1::ReconciliationRequired);
        }
        admission.require_current().map_err(|_| CircuitCellErrorV1::ReconciliationRequired)?;
        finish(binding, dispatch, &input, decision)
    }
}
