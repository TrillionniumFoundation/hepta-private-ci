//! Terminal credit uses both original fact owners: the Circuit's committed
//! trace and the Cell's committed decision. No model, tool, signer or trainer
//! runs here. Pending/Censored observations retain the existing intelligence
//! observed-outcome API; Circuit termination alone never supplies a reward.

use std::collections::BTreeMap;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowError;
use codex_hepta_intelligence::OutcomeCreditClosureErrorV2;
use codex_hepta_learning_ledger::CreditAllocationBatchV1;
use codex_hepta_neuron::CellExecutionError;
use codex_hepta_neuron::CellInferenceReadbackPortV1;
use codex_hepta_neuron::CellInputEncoderV1;
use codex_hepta_neuron::CellStateOwnerV1;
use codex_hepta_neuron::CellStepInputV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::canonical_cell_step_request_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdCircuitCellOwnerV1;
use crate::CircuitCellErrorV1;
use crate::circuit_cell::finish;
use crate::circuit_cell_output::encode_receipt;

#[derive(Debug, thiserror::Error)]
pub enum CircuitCreditErrorV1 {
    #[error("circuit credit binding: {0}")]
    Binding(&'static str),
    #[error(transparent)]
    Circuit(#[from] TaskFlowError),
    #[error(transparent)]
    Cell(#[from] CircuitCellErrorV1),
    #[error(transparent)]
    State(#[from] CellExecutionError),
    #[error(transparent)]
    Closure(#[from] OutcomeCreditClosureErrorV2),
}

/// One executed Cell version, aggregating all its committed activations. The
/// definition digest also binds generation, state schema, encoder and weights.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitCreditTargetV1 {
    pub target_id: StableId,
    pub cell_id: StableId,
    pub bundle_digest: Digest32,
    pub definition_digest: Digest32,
    pub activation_ids: Vec<u64>,
}

/// Constructed only by owner readback. It authenticates no evaluator/allocator
/// and grants no training, publication or external-effect authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitCreditSupportV1 {
    digest: Digest32,
    targets: Vec<CircuitCreditTargetV1>,
}

impl CircuitCreditSupportV1 {
    pub fn digest(&self) -> Digest32 {
        self.digest
    }
    pub fn targets(&self) -> &[CircuitCreditTargetV1] {
        &self.targets
    }

    /// Structural preflight before independent signing. Authentication,
    /// terminality, conservation and episode/correction lineage remain ledger
    /// checks; this method neither assigns credit nor rewrites signed bytes.
    pub fn validate_credit(&self, credit: &CreditAllocationBatchV1) -> Result<(), CircuitCreditErrorV1> {
        if credit.support_digest != self.digest
            || credit.allocations.is_empty()
            || credit.allocations.len() > self.targets.len()
            || credit.allocations.iter().any(|allocation| {
                !self.targets.iter().any(|target| target.target_id == allocation.target_id)
            })
        {
            return Err(CircuitCreditErrorV1::Binding("credit support or unexecuted target"));
        }
        Ok(())
    }
}

impl<O, P, E> AgentdCircuitCellOwnerV1<O, P, E>
where
    O: CellStateOwnerV1,
    P: NeuronInferenceControlPort + CellInferenceReadbackPortV1,
    E: CellInputEncoderV1,
{
    /// Read the terminal run from its durable owner. Inputs are original
    /// readback keys, never caller-selected credit targets: they must cover
    /// exactly every completed computation and match its persisted claim.
    pub async fn terminal_credit_support(
        &self,
        circuit: &AutomationStore,
        run_id: &str,
        inputs: &BTreeMap<u64, CellStepInputV1>,
    ) -> Result<CircuitCreditSupportV1, CircuitCreditErrorV1> {
        let trace = circuit.bounded_circuit_committed_trace(run_id).await?
            .ok_or(CircuitCreditErrorV1::Binding("unknown circuit run"))?;
        let run = trace.run();
        if run.outcome().is_none() || run.unresolved() != 0 {
            return Err(CircuitCreditErrorV1::Binding("circuit is not settled"));
        }
        let dispatches = run.completed_computation_dispatches(self.registry().definition())?;
        if inputs.len() != dispatches.len() || inputs.is_empty() {
            return Err(CircuitCreditErrorV1::Binding("incomplete executed input set"));
        }
        let mut bytes = b"hepta.agentd.circuit-credit-support.v1\0".to_vec();
        bytes.extend_from_slice(trace.history_digest().as_str().as_bytes());
        let mut targets = BTreeMap::<StableId, CircuitCreditTargetV1>::new();
        for dispatch in dispatches {
            let activation_id = dispatch.activation_id;
            let activation = &run.activations()[&activation_id];
            let input = inputs.get(&activation_id)
                .ok_or(CircuitCreditErrorV1::Binding("missing executed input"))?;
            let binding = self.registry().bind_input(&dispatch, input)?;
            let request_digest = canonical_cell_step_request_digest_v1(&binding.cell, input)?;
            if input.scope.agent_id.as_str() != circuit.owner_agent_id().as_str()
                || activation.execution_request_digest()
                    .is_none_or(|digest| digest.as_str() != request_digest.to_string())
            {
                return Err(CircuitCreditErrorV1::Binding("original computation claim"));
            }
            let decision = self.state_owner()
                .lookup(&input.scope, &input.operation_id, request_digest)?
                .ok_or(CircuitCreditErrorV1::Binding("missing committed Cell decision"))?;
            let execution = finish(binding, &dispatch, input, decision)?;
            if trace.completions().get(&activation_id) != Some(&execution.completion) {
                return Err(CircuitCreditErrorV1::Binding("Cell/Circuit completion mismatch"));
            }
            let definition_digest = binding.cell.semantic_digest()?;
            let target_id = StableId::new(format!("circuit-cell-version:{definition_digest}"))
                .map_err(|_| CircuitCreditErrorV1::Binding("target identity"))?;
            targets.entry(target_id.clone()).or_insert_with(|| CircuitCreditTargetV1 {
                target_id,
                cell_id: execution.decision.scope.cell_id.clone(),
                bundle_digest: execution.decision.bundle_digest,
                definition_digest,
                activation_ids: Vec::new(),
            }).activation_ids.push(activation_id);
            bytes.extend_from_slice(&activation_id.to_be_bytes());
            bytes.extend_from_slice(definition_digest.as_array());
            bytes.extend_from_slice(Digest32::of_bytes(&encode_receipt(&execution.decision)?).as_array());
        }
        Ok(CircuitCreditSupportV1 {
            digest: Digest32::of_bytes(&bytes),
            targets: targets.into_values().collect(),
        })
    }

}
