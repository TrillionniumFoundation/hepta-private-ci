//! Computation admissions and receipt binding for the bounded V2 profile.

use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;

use crate::BoundedCircuitDefinitionV2;
use crate::CircuitActivationStatusV2 as Status;
use crate::CircuitBudgetV2;
use crate::CircuitCompletionV2;
use crate::CircuitDispatchV2;
use crate::CircuitExitV2;
use crate::CircuitNodeKindV2;
use crate::CircuitRunV2;
use crate::CircuitStopReasonV2 as Stop;
use crate::TaskFlowError;
use crate::circuit_budget::CircuitWorkSettlementV2;
use crate::circuit_profile::digest;
use crate::circuit_profile::hash;
use crate::circuit_profile::invalid;
use crate::circuit_state::CircuitInstanceV2;
use crate::circuit_state::CircuitNodeProgressV2;

impl CircuitRunV2 {
    pub(crate) fn dispatch(&self, definition: &BoundedCircuitDefinitionV2, id: u64) -> Result<CircuitDispatchV2, TaskFlowError> {
        let activation = self.activations.get(&id).ok_or_else(|| invalid("unknown activation"))?;
        let instance = &self.instances[&activation.instance_id];
        let program = definition.program(&instance.program_id)?;
        let node = program.node(&activation.node_id)?;
        let max_work = match node.kind {
            CircuitNodeKindV2::Compute { max_work } | CircuitNodeKindV2::Decide { max_work } => max_work,
            CircuitNodeKindV2::Subcircuit { .. } | CircuitNodeKindV2::Join { .. } | CircuitNodeKindV2::Exit { .. } =>
                return Err(invalid("node is not an external computation")),
        };
        let candidate_edges: Vec<_> = program.edges.iter().filter(|e| e.from == node.node_id)
            .map(|e| e.edge_id.clone()).collect();
        let invocation_digest = hash("hepta.circuit.invocation.v2", &(
            &self.owner_agent_id, &self.run_id, &self.definition_digest, &self.scope_digest,
            id, &instance.program_id, &node.node_id, activation.round, &activation.input_digest,
            &candidate_edges, max_work,
        ))?;
        Ok(CircuitDispatchV2 {
            run_id: self.run_id.clone(), activation_id: id, program_id: instance.program_id.clone(),
            node_id: node.node_id.clone(), round: activation.round, input_digest: activation.input_digest.clone(),
            input_schema: node.input_schema.clone(), output_schema: node.output_schema.clone(),
            scope_digest: self.scope_digest.clone(), parameter_bundle_digest: definition.parameter_bundle_digest.clone(),
            route_policy_digest: definition.route_policy_digest.clone(), max_work, candidate_edges, invocation_digest,
        })
    }

    pub(crate) fn activate(
        &mut self, definition: &BoundedCircuitDefinitionV2, id: u64, dispatches: &mut Vec<CircuitDispatchV2>,
    ) -> Result<(), TaskFlowError> {
        let activation = self.activations[&id].clone();
        let instance = &self.instances[&activation.instance_id];
        let program = definition.program(&instance.program_id)?;
        let node = program.node(&activation.node_id)?.clone();
        match node.kind {
            CircuitNodeKindV2::Compute { max_work } | CircuitNodeKindV2::Decide { max_work } => {
                if self.instances.get_mut(&activation.instance_id).ok_or_else(|| invalid("unknown instance"))?
                    .budget.reserve(id, max_work).is_err()
                {
                    return self.stop(definition, Stop::WorkBudget);
                }
                self.activations.get_mut(&id).ok_or_else(|| invalid("unknown activation"))?.status = Status::InFlight;
                dispatches.push(self.dispatch(definition, id)?);
            }
            CircuitNodeKindV2::Subcircuit { program, max_work } => {
                let child_depth = instance.child_depth + 1;
                if child_depth > definition.limits.max_child_depth {
                    return self.stop(definition, Stop::DepthLimit);
                }
                if self.instances.get_mut(&activation.instance_id).ok_or_else(|| invalid("unknown instance"))?
                    .budget.reserve(id, max_work).is_err()
                {
                    return self.stop(definition, Stop::WorkBudget);
                }
                let entry = definition.program(&program)?.entry_node.clone();
                self.instances.insert(id, CircuitInstanceV2 {
                    program_id: program, parent_activation: Some(id), child_depth,
                    budget: CircuitBudgetV2::new(max_work), exit: None, returned: false,
                    progress: BTreeMap::new(),
                });
                self.activations.get_mut(&id).ok_or_else(|| invalid("unknown activation"))?.status = Status::ChildRunning;
                self.enqueue(definition, id, &entry, /*round*/ 0, vec![id], activation.input_digest,
                    self.last_observed_ms, /*edge_id*/ None)?;
            }
            CircuitNodeKindV2::Join { .. } => {
                self.complete_internal(id, activation.input_digest.clone())?;
                let edges: Vec<_> = program.edges.iter().filter(|e| e.from == node.node_id)
                    .map(|e| e.edge_id.clone()).collect();
                self.route(definition, id, &edges)?;
            }
            CircuitNodeKindV2::Exit { outcome } => {
                self.complete_internal(id, activation.input_digest.clone())?;
                self.exit_instance(definition, activation.instance_id, outcome, activation.input_digest)?;
            }
        }
        Ok(())
    }

    pub(crate) fn complete(
        &mut self, definition: &BoundedCircuitDefinitionV2, completion: &CircuitCompletionV2, expected: Status,
    ) -> Result<(), TaskFlowError> {
        digest(&completion.output_digest)?;
        digest(&completion.receipt_digest)?;
        let id = completion.activation_id;
        let activation = self.activations.get(&id).ok_or_else(|| invalid("unknown completion"))?.clone();
        if activation.status != expected || completion.invocation_digest != self.dispatch(definition, id)?.invocation_digest {
            return Err(invalid("completion status or invocation binding mismatch"));
        }
        let program = definition.program(&self.instances[&activation.instance_id].program_id)?;
        let candidates: Vec<_> = program.edges.iter().filter(|e| e.from == activation.node_id)
            .map(|e| e.edge_id.clone()).collect();
        if completion.outcome != CircuitExitV2::Succeeded {
            if !completion.selected_edges.is_empty() {
                return Err(invalid("failed computation cannot select a success route"));
            }
        } else {
            match program.node(&activation.node_id)?.kind {
                CircuitNodeKindV2::Compute { .. } if completion.selected_edges != candidates =>
                    return Err(invalid("compute must deliver to its declared branches")),
                CircuitNodeKindV2::Decide { .. } if completion.selected_edges.len() != 1
                    || !candidates.contains(&completion.selected_edges[0]) =>
                    return Err(invalid("decision must select exactly one admitted candidate")),
                CircuitNodeKindV2::Compute { .. } | CircuitNodeKindV2::Decide { .. } => {}
                CircuitNodeKindV2::Subcircuit { .. } | CircuitNodeKindV2::Join { .. } | CircuitNodeKindV2::Exit { .. } =>
                    return Err(invalid("completion is not for a computation")),
            }
        }
        let instance = self.instances.get_mut(&activation.instance_id).ok_or_else(|| invalid("unknown instance"))?;
        let settlement = instance.budget.settle(id, completion.actual_work)?;
        let no_progress = self.observe_output(activation.instance_id, &activation.node_id, &completion.output_digest)?;
        let completed = self.activations.get_mut(&id).ok_or_else(|| invalid("unknown completion"))?;
        completed.status = Status::Completed;
        completed.output_digest = Some(completion.output_digest.clone());
        completed.receipt_digest = Some(completion.receipt_digest.clone());
        completed.selected_edges.clone_from(&completion.selected_edges);
        if settlement == CircuitWorkSettlementV2::Overrun {
            return self.stop(definition, Stop::WorkBudget);
        }
        if activation.cancel_requested || self.instances[&activation.instance_id].exit.is_some() {
            return Ok(());
        }
        if completion.outcome != CircuitExitV2::Succeeded {
            return self.fallback_instance(definition, activation.instance_id, completion.output_digest.clone());
        }
        if no_progress >= definition.limits.max_no_progress {
            return self.stop(definition, Stop::NoProgress);
        }
        self.route(definition, id, &completion.selected_edges)
    }

    /// Different cells can alternate stable outputs. Keep observations local
    /// to each (instance, node), including a returning composite computation.
    pub(crate) fn observe_output(
        &mut self, instance_id: u64, node_id: &str, output: &Sha256Digest,
    ) -> Result<u32, TaskFlowError> {
        let instance = self.instances.get_mut(&instance_id).ok_or_else(|| invalid("unknown progress instance"))?;
        let no_progress = match instance.progress.get(node_id) {
            Some(previous) if previous.last_output == *output =>
                previous.no_progress.checked_add(1).ok_or_else(|| invalid("progress counter overflow"))?,
            _ => 0,
        };
        instance.progress.insert(node_id.to_string(), CircuitNodeProgressV2 {
            last_output: output.clone(), no_progress,
        });
        Ok(no_progress)
    }

    pub(crate) fn complete_internal(
        &mut self, id: u64, output: codex_hepta_contracts::Sha256Digest,
    ) -> Result<(), TaskFlowError> {
        let activation = self.activations.get_mut(&id).ok_or_else(|| invalid("unknown internal activation"))?;
        activation.status = Status::Completed;
        activation.output_digest = Some(output);
        activation.receipt_digest = Some(hash("hepta.circuit.internal.v2",
            &(&self.run_id, activation.activation_id, &activation.input_digest, &activation.output_digest))?);
        Ok(())
    }
}
