//! Read-only causal joins of the original Circuit and Cell fact owners.
//! Owner clocks remain separate. These records establish computation history,
//! not external observation freshness, action effects or evaluator truth.

use std::collections::BTreeMap;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitComputationTimesV2;
use codex_hepta_automation::CircuitExitV2;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_neuron::CellInferenceReadbackPortV1;
use codex_hepta_neuron::CellInputEncoderV1;
use codex_hepta_neuron::CellScopeV1;
use codex_hepta_neuron::CellStateOwnerV1;
use codex_hepta_neuron::CellStepInputV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::canonical_cell_step_request_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdCircuitCellOwnerV1;
use crate::CircuitCreditErrorV1;
use crate::circuit_cell::finish;

/// A verified join at one original activation. Digests retain provenance without
/// exposing raw observations. This advisory DTO grants no effect authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitCellCausalRecordV1 {
    pub circuit_run_id: String,
    pub activation_id: u64,
    pub causal_parents: Vec<u64>,
    pub circuit_history_digest: Sha256Digest,
    pub circuit_input_digest: Sha256Digest,
    pub circuit_ready_at_ms: u64,
    pub circuit_times: CircuitComputationTimesV2,
    pub scope: CellScopeV1,
    pub generation: u64,
    pub definition_digest: Digest32,
    pub bundle_digest: Digest32,
    pub source_frontier: Digest32,
    /// Request sample on the Cell clock; not the occurrence time of an external event.
    pub cell_requested_at_micros: u64,
    pub observation_digest: Digest32,
    /// Includes the exact candidate set, masks, source, objective and NDU snapshot.
    pub semantic_request_digest: Digest32,
    pub selected_candidate: StableId,
    pub checkpoint_before: Digest32,
    pub checkpoint_after: Digest32,
    pub model_output_digest: Digest32,
    pub computation_outcome: CircuitExitV2,
}

impl<O, P, E> AgentdCircuitCellOwnerV1<O, P, E>
where
    O: CellStateOwnerV1,
    P: NeuronInferenceControlPort + CellInferenceReadbackPortV1,
    E: CellInputEncoderV1,
{
    /// Reconstruct exactly all completed computations from original readback keys.
    /// No clock is sampled and no inference, state mutation or external check runs.
    /// External occurrence/availability/freshness requires separate host evidence;
    /// this method never substitutes receipt time for such evidence.
    pub async fn committed_causal_records(
        &self,
        circuit: &AutomationStore,
        run_id: &str,
        inputs: &BTreeMap<u64, CellStepInputV1>,
    ) -> Result<Vec<CircuitCellCausalRecordV1>, CircuitCreditErrorV1> {
        let trace = circuit
            .bounded_circuit_committed_trace(run_id)
            .await?
            .ok_or(CircuitCreditErrorV1::Binding("unknown circuit run"))?;
        let run = trace.run();
        let dispatches = run.completed_computation_dispatches(self.registry().definition())?;
        if inputs.len() != dispatches.len() {
            return Err(CircuitCreditErrorV1::Binding("incomplete causal input set"));
        }
        let mut records = Vec::with_capacity(dispatches.len());
        for dispatch in dispatches {
            let activation = &run.activations()[&dispatch.activation_id];
            let input = inputs.get(&dispatch.activation_id)
                .ok_or(CircuitCreditErrorV1::Binding("missing causal input"))?;
            let binding = self.registry().bind_input(&dispatch, input)?;
            let request_digest = canonical_cell_step_request_digest_v1(&binding.cell, input)?;
            if input.scope.agent_id.as_str() != circuit.owner_agent_id().as_str()
                || activation.execution_request_digest()
                    .is_none_or(|digest| digest.as_str() != request_digest.to_string())
            {
                return Err(CircuitCreditErrorV1::Binding("original causal computation claim"));
            }
            let decision = self.state_owner().lookup(&input.scope, &input.operation_id, request_digest)?
                .ok_or(CircuitCreditErrorV1::Binding("missing committed causal decision"))?;
            let execution = finish(binding, &dispatch, input, decision)?;
            if trace.completions().get(&dispatch.activation_id) != Some(&execution.completion) {
                return Err(CircuitCreditErrorV1::Binding("causal Cell/Circuit completion mismatch"));
            }
            let circuit_times = *trace.computation_times().get(&dispatch.activation_id)
                .ok_or(CircuitCreditErrorV1::Binding("missing original causal clock samples"))?;
            let decision = execution.decision;
            records.push(CircuitCellCausalRecordV1 {
                circuit_run_id: run.run_id().to_string(),
                activation_id: dispatch.activation_id,
                causal_parents: activation.causal_parents.clone(),
                circuit_history_digest: trace.history_digest().clone(),
                circuit_input_digest: activation.input_digest.clone(),
                circuit_ready_at_ms: activation.ready_at_ms,
                circuit_times,
                scope: decision.scope,
                generation: binding.cell.runtime.generation.get(),
                definition_digest: binding.cell.semantic_digest()?,
                bundle_digest: decision.bundle_digest,
                source_frontier: decision.source_frontier,
                cell_requested_at_micros: input.monotonic_micros,
                observation_digest: Digest32::of_bytes(&input.observation),
                semantic_request_digest: decision.semantic_request_digest,
                selected_candidate: decision.selected_candidate,
                checkpoint_before: decision.checkpoint_before,
                checkpoint_after: decision.checkpoint_after,
                model_output_digest: decision.model_output_digest,
                computation_outcome: execution.completion.outcome,
            });
        }
        Ok(records)
    }
}
