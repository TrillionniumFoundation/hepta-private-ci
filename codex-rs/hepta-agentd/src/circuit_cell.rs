//! Shared Agentd composition: a durable Circuit admission enters the native
//! Cell pipeline, then returns a completion only after the Cell owner commits.
//! This computation facility never invokes tools or publishes external effects.

use std::error::Error;
use std::fmt;

use codex_hepta_automation::CircuitCompletionV2;
use codex_hepta_automation::CircuitComputationAdmissionV2;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_neuron::CellCandidateKindV1;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::CellExecutionError;
use codex_hepta_neuron::CellInferenceReadbackPortV1;
use codex_hepta_neuron::CellInputEncoderV1;
use codex_hepta_neuron::CellStateOwnerV1;
use codex_hepta_neuron::CellStepEntryV1;
use codex_hepta_neuron::CellStepInputV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::canonical_cell_step_request_digest_v1;
use codex_hepta_neuron::commit_cell_step;
use codex_hepta_neuron::decide_cell;
use codex_hepta_neuron::enter_cell_step;
use codex_hepta_neuron::infer_cell;
use codex_hepta_neuron::recover_cell_inference;
use codex_hepta_types::AuthorityPosture;

use crate::CircuitCellBindingV1;
use crate::CircuitCellRegistryV1;
use crate::circuit_cell_dispatch::GuardedCellDispatchV1;
use crate::circuit_cell_output::encode_output;
use crate::circuit_cell_output::encode_receipt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CircuitCellErrorV1 {
    InvalidBinding,
    ScopeMismatch,
    InputMismatch,
    InvalidReceipt,
    ReconciliationRequired,
    Cell(CellExecutionError),
}

impl fmt::Display for CircuitCellErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result { write!(formatter, "{self:?}") }
}
impl Error for CircuitCellErrorV1 {}
impl From<CellExecutionError> for CircuitCellErrorV1 {
    fn from(error: CellExecutionError) -> Self { Self::Cell(error) }
}

/// The two owners use explicit time units. Their clock epochs need not match.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CircuitCellTimeV1 {
    pub circuit_millis: u64,
    pub cell_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitCellExecutionV1 {
    pub completion: CircuitCompletionV2,
    pub decision: CellDecisionReceiptV1,
    /// Exact canonical bytes named by completion.output_digest.
    pub output: Vec<u8>,
}

/// One long-lived owner for many cells. O owns partitioned state, P owns the
/// shared inference facility, and E resolves frozen encoders. Construction
/// does not activate this facility in the daemon's ordinary startup path.
pub struct AgentdCircuitCellOwnerV1<O, P, E> {
    registry: CircuitCellRegistryV1,
    state_owner: O,
    inference_control: P,
    encoder: E,
}

impl<O, P, E> AgentdCircuitCellOwnerV1<O, P, E>
where
    O: CellStateOwnerV1,
    P: NeuronInferenceControlPort + CellInferenceReadbackPortV1,
    E: CellInputEncoderV1,
{
    pub fn new(registry: CircuitCellRegistryV1, state_owner: O, inference_control: P, encoder: E) -> Self {
        Self { registry, state_owner, inference_control, encoder }
    }

    pub fn registry(&self) -> &CircuitCellRegistryV1 { &self.registry }
    pub fn state_owner(&self) -> &O { &self.state_owner }
    pub fn state_owner_mut(&mut self) -> &mut O { &mut self.state_owner }

    /// Consume an owner-issued admission. Raw dispatch DTOs cannot call this
    /// entry point. On any error the Circuit keeps its reservation; neither a
    /// missing response nor an absent Cell receipt proves no computation.
    ///
    /// The caller commits the returned completion with its existing Circuit
    /// fence/CAS. Losing that acknowledgement is recovered from the same Cell
    /// operation and never repeats encoding, inference or state advancement.
    pub fn execute(
        &mut self,
        admission: CircuitComputationAdmissionV2,
        input: CellStepInputV1,
        mut clock: impl FnMut() -> CircuitCellTimeV1,
    ) -> Result<CircuitCellExecutionV1, CircuitCellErrorV1> {
        let dispatch = admission.dispatch();
        let binding = self.registry.bind_input(dispatch, &input)?;
        let request_digest = canonical_cell_step_request_digest_v1(&binding.cell, &input)?;
        if admission.owner_agent_id().as_str() != input.scope.agent_id.as_str()
            || admission.definition_digest() != self.registry.definition_digest()
            || admission.execution_request_digest().is_none_or(|digest| digest.as_str() != request_digest.to_string())
        {
            return Err(CircuitCellErrorV1::ScopeMismatch);
        }
        let time = clock();
        if time.circuit_millis < admission.observed_at_ms() {
            return Err(CircuitCellErrorV1::ReconciliationRequired);
        }
        let admission_deadline = admission.lease_expires_at_ms().min(admission.run_deadline_ms());
        let read_only = admission.reconciliation_only()
            || time.circuit_millis >= admission_deadline;
        let committed = match self.state_owner.lookup(&input.scope, &input.operation_id, request_digest) {
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
                    &binding.cell, &self.state_owner, &self.encoder, input.clone(),
                    &mut self.inference_control, time.cell_micros,
                )?
            } else {
                if read_only { return Err(CircuitCellErrorV1::ReconciliationRequired); }
                match enter_cell_step(
                    &binding.cell, &self.state_owner, &self.encoder, input.clone(), time.cell_micros,
                )? {
                    CellStepEntryV1::Ready(prepared) => {
                        let before_infer = clock();
                        if before_infer.circuit_millis < time.circuit_millis
                            || before_infer.cell_micros < time.cell_micros
                            || before_infer.circuit_millis >= admission_deadline
                        {
                            return Err(CircuitCellErrorV1::ReconciliationRequired);
                        }
                        let mut guarded = GuardedCellDispatchV1::new(
                            &mut self.inference_control, &mut clock, before_infer,
                            admission_deadline, input.deadline_micros,
                        );
                        let inferred = infer_cell(prepared, &mut self.state_owner, &mut guarded, before_infer.cell_micros)?;
                        last_time = guarded.observed_at().ok_or(CircuitCellErrorV1::ReconciliationRequired)?;
                        inferred
                    }
                    CellStepEntryV1::Replayed(receipt) => return finish(binding, dispatch, &input, receipt),
                }
            };
            let decided_at = clock();
            if decided_at.circuit_millis < last_time.circuit_millis
                || decided_at.cell_micros < last_time.cell_micros
            {
                return Err(CircuitCellErrorV1::ReconciliationRequired);
            }
            let proposal = decide_cell(inferred, decided_at.cell_micros)?;
            let committed_at = clock();
            if committed_at.circuit_millis < decided_at.circuit_millis
                || committed_at.cell_micros < decided_at.cell_micros
            {
                return Err(CircuitCellErrorV1::ReconciliationRequired);
            }
            commit_cell_step(&mut self.state_owner, proposal, committed_at.cell_micros)?
        };
        finish(binding, dispatch, &input, decision)
    }
}

fn finish(
    binding: &CircuitCellBindingV1,
    dispatch: &codex_hepta_automation::CircuitDispatchV2,
    input: &CellStepInputV1,
    decision: CellDecisionReceiptV1,
) -> Result<CircuitCellExecutionV1, CircuitCellErrorV1> {
    let selected = binding.cell.candidates.iter()
        .position(|candidate| candidate.candidate_id == decision.selected_candidate)
        .ok_or(CircuitCellErrorV1::InvalidReceipt)?;
    if decision.operation_id != input.operation_id
        || decision.scope != input.scope || decision.bundle_digest != binding.cell.bundle_digest
        || decision.source_frontier != input.source_frontier
        || decision.semantic_request_digest != canonical_cell_step_request_digest_v1(&binding.cell, input)?
        || decision.authority != AuthorityPosture::DENY_ALL
        || decision.operation_digest.is_zero() || decision.model_output_digest.is_zero()
        || decision.checkpoint_after.is_zero()
        || decision.confidence_ppm > 1_000_000 || decision.ood_ppm > 1_000_000
        || decision.cost.consumed_input_bytes.checked_add(decision.cost.truncated_input_bytes) != Some(input.observation.len())
        || decision.policy.len() != binding.cell.candidates.len()
        || input.candidates.len() != decision.policy.len()
        || (decision.deadline_exceeded && binding.cell.candidates[selected].kind != CellCandidateKindV1::Abstain)
    {
        return Err(CircuitCellErrorV1::InvalidReceipt);
    }
    for (index, ((policy, mask), candidate)) in decision.policy.iter()
        .zip(&input.candidates).zip(&binding.cell.candidates).enumerate()
    {
        if policy.candidate_id != candidate.candidate_id || mask.candidate_id != candidate.candidate_id
            || policy.allowed != mask.allowed
            || policy.probability_ppm != if index == selected { 1_000_000 } else { 0 }
            || (index == selected && !policy.allowed)
        {
            return Err(CircuitCellErrorV1::InvalidReceipt);
        }
    }
    let route = &binding.routes[selected];
    let output = encode_output(&decision)?;
    let output_digest = Sha256Digest::for_bytes(&output);
    let mut receipt_bytes = b"hepta.circuit.cell-completion.v1\0".to_vec();
    receipt_bytes.extend_from_slice(dispatch.invocation_digest.as_str().as_bytes());
    receipt_bytes.extend_from_slice(output_digest.as_str().as_bytes());
    receipt_bytes.extend_from_slice(&encode_receipt(&decision)?);
    let completion = CircuitCompletionV2 {
        activation_id: dispatch.activation_id,
        invocation_digest: dispatch.invocation_digest.clone(),
        output_digest,
        receipt_digest: Sha256Digest::for_bytes(&receipt_bytes),
        // Preserve actual work, including an overrun. The Circuit owner records
        // the full charge and takes WorkBudget fallback instead of clamping it.
        actual_work: decision.cost.model_latency_micros,
        outcome: route.outcome,
        selected_edges: route.selected_edges.clone(),
    };
    Ok(CircuitCellExecutionV1 { completion, decision, output })
}

#[cfg(test)]
#[path = "circuit_cell_tests.rs"]
mod tests;
